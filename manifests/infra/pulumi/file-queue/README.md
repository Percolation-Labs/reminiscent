# File Queue Infrastructure

S3 bucket notifications to SQS for asynchronous file processing in the REM system.

## Architecture

```
S3: s3://rem/uploads/*
         │
         │ ObjectCreated:* event
         ▼
SQS: rem-file-processing (0-30 messages)
         │
         ├──────────────┬─────────────────┐
         │ Metrics      │ Long poll (20s) │
         ▼              ▼                  ▼
KEDA Operator    K8s Pods (0-20)    Dead Letter Queue
         │              │                  │
         │ Scale        │ IRSA             │ Failed (3x)
         ▼              ▼                  ▼
HPA (0-20 pods)  Process + delete    Manual review
         │              │
         │              ▼
         └──────> Karpenter (provisions nodes)
```

## Deployment

```bash
cd manifests/infra/file-queue
pulumi up
```

## Outputs

After deployment, Pulumi exports:
- `queueUrl` - SQS queue URL for Python consumers
- `queueArn` - Queue ARN for IRSA configuration
- `bucketName` - S3 bucket name
- `policyArn` - IAM policy ARN to attach to IRSA role

## Kubernetes Setup (IRSA + KEDA)

To consume the queue from EKS pods with event-driven autoscaling:

### Prerequisites

1. **KEDA installed** - See `manifests/platform/keda/`
2. **OIDC provider configured** - Part of EKS cluster setup
3. **IAM roles created** - Both for KEDA operator and workload pods

### IAM Setup Overview

Two IAM roles needed:
1. **KEDA operator role** - Read SQS metrics (queue attributes)
2. **File processor role** - Consume messages + read S3 objects

### Step 1: Create IAM Roles for Service Accounts

Add to your main EKS Pulumi stack (`manifests/infra/pulumi/resources.yaml`):

```yaml
# Add to manifests/infra/pulumi/resources.yaml

  # IAM Role for file-processor pods (IRSA)
  fileProcessorRole:
    type: aws:iam:Role
    properties:
      name: rem-file-processor-role
      assumeRolePolicy:
        fn::toJSON:
          Version: "2012-10-17"
          Statement:
            - Effect: Allow
              Principal:
                Federated: ${eksCluster.oidcProviderArn}
              Action: sts:AssumeRoleWithWebIdentity
              Condition:
                StringEquals:
                  "${eksCluster.oidcProviderUrl}:sub": "system:serviceaccount:default:file-processor"
                  "${eksCluster.oidcProviderUrl}:aud": "sts.amazonaws.com"
      tags:
        Purpose: file-processor-irsa
        Component: rem-k8s

  # Attach the file processor policy to the role
  fileProcessorPolicyAttachment:
    type: aws:iam:RolePolicyAttachment
    properties:
      role: ${fileProcessorRole.name}
      policyArn: ${fileProcessorPolicyArn}  # Reference from file-queue stack outputs

outputs:
  kedaOperatorRoleArn:
    value: ${kedaOperatorRole.arn}
  fileProcessorRoleArn:
    value: ${fileProcessorRole.arn}
```

**Important**: KEDA uses "operator identity owner" model - KEDA operator role needs SQS read access, workload role needs consume access.

### Step 2: Annotate KEDA ServiceAccount

```bash
# After KEDA is installed via ArgoCD
kubectl annotate serviceaccount keda-operator \
  -n keda \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/keda-operator-role \
  --overwrite
```

Or update `manifests/platform/keda/application.yaml` helm values:

```yaml
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/keda-operator-role
```

### Step 3: Create Application Manifests

See `manifests/application/file-processor/` for complete setup:
- `deployment.yaml` - ServiceAccount + Deployment
- `keda-scaledobject.yaml` - KEDA scaling configuration

The ServiceAccount is defined in `deployment.yaml`:

Deployment and ServiceAccount are in `manifests/application/file-processor/deployment.yaml`:

```yaml
# ServiceAccount with IRSA annotation
apiVersion: v1
kind: ServiceAccount
metadata:
  name: file-processor
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/rem-file-processor-role
---
# Deployment (KEDA manages replicas)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: file-processor
spec:
  replicas: 0  # KEDA scales from 0
  ...
```

KEDA ScaledObject in `manifests/application/file-processor/keda-scaledobject.yaml`:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: file-processor-scaler
spec:
  scaleTargetRef:
    name: file-processor
  minReplicaCount: 0      # Scale to zero
  maxReplicaCount: 20     # Max pods
  pollingInterval: 10     # Check queue every 10s
  cooldownPeriod: 60      # Wait 60s before scale down

  triggers:
  - type: aws-sqs-queue
    metadata:
      queueURL: https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/rem-file-processing
      queueLength: "10"   # 1 pod per 10 messages
      awsRegion: us-east-1
      identityOwner: operator  # Use KEDA operator's IRSA
```

**Scaling example**: 30 messages in queue → KEDA scales to 3 pods (30 / 10)

### Step 4: Deploy Application

```bash
# Deploy file processor (Deployment + ScaledObject)
kubectl apply -f manifests/application/file-processor/

# Verify KEDA created HPA
kubectl get hpa

# Should start at 0 pods (no messages)
kubectl get pods -l app=file-processor
```

### Step 5: Python Consumer Code

Create `rem/src/rem/consumers/s3_file_processor.py`:

```python
"""
S3 file event processor consuming from SQS.

Environment variables:
- SQS_QUEUE_URL: SQS queue URL from Pulumi output
- AWS_REGION: AWS region (automatically set by IRSA)
"""

import os
import json
import logging
from typing import Optional
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3FileProcessor:
    """
    Consumes S3 ObjectCreated events from SQS queue.

    Uses IRSA credentials automatically via pod ServiceAccount.
    No AWS credentials needed in code or environment.
    """

    def __init__(self, queue_url: Optional[str] = None):
        self.queue_url = queue_url or os.environ["SQS_QUEUE_URL"]
        self.sqs = boto3.client("sqs")
        self.s3 = boto3.client("s3")

    def poll_forever(self):
        """
        Long poll SQS queue and process messages.

        Uses long polling (20s WaitTimeSeconds) to reduce API calls.
        Processes up to 10 messages per batch.
        """
        logger.info(f"Starting file processor, polling {self.queue_url}")

        while True:
            try:
                response = self.sqs.receive_message(
                    QueueUrl=self.queue_url,
                    MaxNumberOfMessages=10,
                    WaitTimeSeconds=20,  # Long polling
                    AttributeNames=["All"],
                    MessageAttributeNames=["All"]
                )

                messages = response.get("Messages", [])
                if not messages:
                    continue

                logger.info(f"Received {len(messages)} messages")

                for message in messages:
                    try:
                        self.process_message(message)
                        self.delete_message(message)
                    except Exception as e:
                        logger.error(f"Failed to process message: {e}", exc_info=True)
                        # Message will be redelivered after visibility timeout

            except KeyboardInterrupt:
                logger.info("Shutting down processor")
                break
            except Exception as e:
                logger.error(f"Error polling queue: {e}", exc_info=True)

    def process_message(self, message: dict):
        """
        Process a single SQS message containing S3 event(s).

        S3 notification format:
        {
          "Records": [{
            "eventName": "ObjectCreated:Put",
            "s3": {
              "bucket": {"name": "rem"},
              "object": {"key": "uploads/file.pdf", "size": 12345}
            }
          }]
        }
        """
        body = json.loads(message["Body"])

        for record in body.get("Records", []):
            event_name = record.get("eventName", "")

            if not event_name.startswith("ObjectCreated:"):
                continue

            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
            size = record["s3"]["object"].get("size", 0)

            logger.info(f"Processing {event_name}: s3://{bucket}/{key} ({size} bytes)")

            try:
                # Download file from S3
                obj = self.s3.get_object(Bucket=bucket, Key=key)
                content = obj["Body"].read()

                # TODO: Your file processing logic here
                # - Extract text from PDF
                # - Generate embeddings
                # - Store in PostgreSQL with pgvector
                # - Create graph edges

                logger.info(f"Successfully processed s3://{bucket}/{key}")

            except ClientError as e:
                logger.error(f"Failed to download s3://{bucket}/{key}: {e}")
                raise

    def delete_message(self, message: dict):
        """Delete message from queue after successful processing."""
        self.sqs.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=message["ReceiptHandle"]
        )


def main():
    """Entry point for containerized deployment."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    processor = S3FileProcessor()
    processor.poll_forever()


if __name__ == "__main__":
    main()
```

### Step 6: Container Image

Create `rem/Dockerfile.file-processor`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/rem ./rem

# Run as non-root user
RUN useradd -m -u 1000 processor
USER processor

CMD ["python", "-m", "rem.consumers.s3_file_processor"]
```

## Testing End-to-End

### 1. Upload test files to trigger scaling

```bash
# Get bucket name from Pulumi output
BUCKET=$(pulumi stack output bucketName)

# Upload 25 test files (should scale to ~3 pods)
for i in {1..25}; do
  echo "test content $i" > test-$i.txt
  aws s3 cp test-$i.txt s3://$BUCKET/uploads/test-$i.txt
done

# Check SQS queue depth
QUEUE_URL=$(pulumi stack output queueUrl)
aws sqs get-queue-attributes \
  --queue-url $QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages
```

### 2. Watch KEDA scale up pods

```bash
# Watch pod count (should go 0 → 3 in ~10-20s)
kubectl get pods -l app=file-processor -w

# Check HPA status
kubectl get hpa file-processor-scaler -w
```

### 3. Monitor processing

```bash
# Pod logs (processing messages)
kubectl logs -l app=file-processor -f

# Queue depth (should decrease as pods process)
watch "aws sqs get-queue-attributes --queue-url $QUEUE_URL --attribute-names ApproximateNumberOfMessages"
```

### 4. Watch scale to zero

```bash
# After queue empties, wait 60s cooldown, then pods terminate
kubectl get pods -l app=file-processor -w
```

## IRSA How It Works

1. **Pod starts** with ServiceAccount `file-processor`
2. **ServiceAccount** has annotation pointing to IAM role ARN
3. **EKS injects** AWS credentials as environment variables:
   - `AWS_ROLE_ARN` - The IAM role to assume
   - `AWS_WEB_IDENTITY_TOKEN_FILE` - Path to OIDC token
4. **boto3** automatically uses these credentials (no code changes needed)
5. **Pod assumes role** via OIDC federation
6. **IAM policy** grants permissions to SQS queue and S3 bucket

No AWS access keys or secrets required! All authentication via Kubernetes ServiceAccount tokens.

## Security Notes

- Bucket has versioning enabled for recovery
- Public access blocked by default
- DLQ configured for failed messages (3 retries)
- Principle of least privilege: policy grants only required permissions
- IRSA prevents credential leakage (no long-lived keys)
- Visibility timeout (5 min) prevents duplicate processing
- Messages retained for 24 hours (configurable)

## Cost Optimization

### Scale to Zero
- KEDA scales to 0 pods when queue empty
- No compute cost during idle periods
- Scales up in 10-20s when messages arrive

### Spot Instances
- Deployment prefers spot instances (70-90% cheaper)
- Karpenter provisions spot by default
- Graceful handling of spot interruptions

### Right-Sizing
- Long polling reduces SQS API calls (fewer charges)
- Tune `queueLength` target: higher = fewer pods, lower cost
- Monitor actual resource usage and adjust limits

### Storage
- S3 Intelligent-Tiering for infrequent access (add lifecycle policy)
- Versioning allows recovery but increases storage cost
- Consider expiration policy for old versions

### Observability
- CloudWatch metrics for queue depth monitoring
- Set alarms for sustained high queue depth (may need more capacity)
- Track processing duration to optimize `queueLength` target

## Related Documentation

- **Platform**: `manifests/platform/keda/` - KEDA installation and IRSA setup
- **Application**: `manifests/application/file-processor/` - Complete deployment with KEDA scaling
- **Architecture**: `/CLAUDE.md` - REM system design principles
