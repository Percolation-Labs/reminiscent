# REM EKS Infrastructure (AWS CDK)

AWS CDK TypeScript infrastructure for REM EKS clusters with proper namespace separation and Pod Identity.

## Current Architecture

### Deployment Model
- **Single Application Cluster**: `REMApplicationClusterA` (staging)
- **Hardcoded Stack Names**: Simple, explicit deployment
- **Entry Point**: `bin/cdk.ts`

### Namespace Architecture

| Namespace | Purpose | ServiceAccounts | IAM Roles | Status |
|-----------|---------|----------------|-----------|--------|
| **rem** (configurable) | REM application workloads (API, MCP, workers) | `rem-app` | `application-cluster-a-app` | ✅ Implemented |
| **observability** | OpenTelemetry collector | `otel-collector` | `application-cluster-a-otel-collector` | ✅ Implemented |
| **postgres-cluster** | CloudNativePG databases | `postgres-backup` | `application-cluster-a-cnpg-backup` | ✅ Implemented |
| **karpenter** | Node autoscaling | `karpenter` | `application-cluster-a-karpenter` | ✅ Implemented |
| **kube-system** | Kubernetes system components | `ebs-csi-controller-sa`, `aws-load-balancer-controller` | EBS CSI, ALB Controller | ✅ Implemented |
| **external-secrets-system** | Secret management | `external-secrets` | `application-cluster-a-external-secrets` | ✅ Implemented |

### Storage Classes

The cluster includes three EBS-backed storage classes optimized for different workload types:

| StorageClass | Volume Type | IOPS | Throughput | Cost | Use Case | Default |
|--------------|-------------|------|------------|------|----------|---------|
| **gp3** | General Purpose SSD | 3,000 | 125 MB/s | $0.08/GB-month | General purpose workloads | ✅ Yes |
| **gp3-postgres** | General Purpose SSD | 5,000 | 250 MB/s | ~$0.09/GB-month | PostgreSQL databases (data + WAL) | No |
| **io2-postgres** | Provisioned IOPS SSD | 10,000 | N/A | ~$0.19/GB-month | Mission-critical databases | No |

**Key Features:**
- All storage classes use the `ebs.csi.aws.com` provisioner (AWS EBS CSI driver)
- **Encrypted by default**: All volumes created with encryption enabled
- **Volume expansion**: `allowVolumeExpansion: true` enables online volume resizing
- **WaitForFirstConsumer**: Volumes created only when pod is scheduled (ensures correct AZ placement)
- **Cost Optimization**: gp3 provides 60% cost savings vs io2 for similar IOPS levels

**Performance Characteristics:**
- **gp3**: Baseline 3,000 IOPS (free), scalable to 16,000 IOPS
- **gp3-postgres**: Optimized for database workloads with higher IOPS and throughput for WAL writes
- **io2-postgres**: Consistent <1ms latency, 99.999% durability, best for mission-critical databases

**Usage in CloudNativePG:**
```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: pg-cluster
spec:
  storage:
    storageClass: gp3-postgres  # Recommended for most use cases
    size: 20Gi
  walStorage:
    storageClass: gp3-postgres  # Or use gp3 to save costs
    size: 10Gi
```

**When to Use io2-postgres:**
- Ultra-low latency requirements (<1ms)
- Single-threaded database workloads needing consistent performance
- Mission-critical databases requiring 99.999% durability (100x better than gp3)
- Budget allows for 2-3x higher storage costs

**Location in Code:** `lib/worker-cluster-stack.ts:255-321`

### Key Design Decisions

1. **Single Application ServiceAccount**: All REM workloads (FastAPI, FastMCP, workers) use the `rem-app` ServiceAccount with comprehensive permissions (S3, SQS, SSM, Secrets Manager, CloudWatch, X-Ray)

2. **Separation of Concerns**: Platform services (observability, databases) isolated in dedicated namespaces

3. **Configurable App Namespace**: Application namespace defaults to `rem` but can be changed via `APP_NAMESPACE` environment variable

4. **Pod Identity (not IRSA)**: Using AWS EKS Pod Identity for simpler configuration vs OIDC-based IRSA

5. **File Processing**: Integrated S3 + SQS file processing queue in the application cluster

### Configuration

All configuration via environment variables or `.env` file:

```bash
# AWS Configuration
AWS_ACCOUNT_ID=852140462228
AWS_REGION=us-east-1
AWS_PROFILE=rem

# Cluster Configuration
CLUSTER_NAME_PREFIX=rem
ENVIRONMENT=dev
DEPLOYMENT_MODE=minimal
KUBERNETES_VERSION=1.33
APP_NAMESPACE=rem  # Configurable application namespace

# Feature Flags
ENABLE_KARPENTER=true
ENABLE_ALB_CONTROLLER=true
ENABLE_EXTERNAL_SECRETS=true
ENABLE_CERT_MANAGER=true
ENABLE_ADOT=true
ENABLE_POD_IDENTITY=true

# Cost Optimization
USE_SPOT_INSTANCES=true
MGMT_INSTANCE_TYPE=t3.small
WORKER_INSTANCE_TYPE=t3.medium
```

## Deployment

### Prerequisites
```bash
npm install
export AWS_PROFILE=rem
export AWS_REGION=us-east-1
```

### Bootstrap CDK (first time only)
```bash
npx cdk bootstrap aws://852140462228/us-east-1
```

### Deploy

```bash
# IMPORTANT: Always use --profile flag to ensure correct AWS account credentials
# CDK does not respect AWS_PROFILE environment variable alone
npx cdk deploy REMApplicationClusterA --profile rem --require-approval never
```

**Note**: The `--profile rem` flag is **required** even if you have `AWS_PROFILE=rem` set in your environment. CDK CLI does not automatically use the environment variable and will fall back to default credentials, which may be for a different AWS account.

**Tip: Log Output for Monitoring**

For long-running deployments (~20 minutes), capture output to a file for easier monitoring:

```bash
# Recommended: Output to file AND terminal simultaneously
npx cdk deploy REMApplicationClusterA --profile rem --require-approval never 2>&1 | tee deploy.log

# Monitor progress in another terminal
tail -f deploy.log

# Or search for specific events
grep -E "(CREATE_|UPDATE_|DELETE_|FAILED)" deploy.log
```

This is especially useful when:
- Deployment spans multiple terminal sessions
- You need to review errors after the fact
- Debugging Lambda rate limiting or CloudFormation failures

#### What to Expect During Deployment

**Total Deployment Time**: ~18-20 minutes (1157-1200 seconds)

**Deployment Phases**:

1. **Synthesis** (~13 seconds)
   - CDK synthesizes CloudFormation template
   - Validates configuration and resources

2. **VPC & Networking** (~2-3 minutes)
   - Creates VPC with 3 availability zones
   - Public and private subnets in each AZ
   - Internet Gateway, NAT Gateways (1 per AZ)
   - Route tables and associations
   - Security groups for EKS control plane

3. **IAM Roles & Policies** (~1-2 minutes)
   - Cluster role with EKS service principal
   - Node group role with EC2 permissions
   - Karpenter controller role
   - Pod Identity IAM roles for:
     - Application pods (`application-cluster-a-app`)
     - OTEL collector (`application-cluster-a-otel-collector`)
     - CloudNativePG backup (`application-cluster-a-cnpg-backup`)
     - External Secrets operator (`application-cluster-a-external-secrets`)
     - ALB controller (`application-cluster-a-alb-controller`)

4. **EKS Control Plane** (~8-10 minutes)
   - EKS cluster creation (longest phase)
   - Kubernetes API endpoint configuration
   - OIDC provider for Pod Identity
   - Control plane logging enabled

5. **Node Groups** (~3-4 minutes)
   - Initial managed node group for Karpenter
   - Instance type: t3.medium (configurable)
   - ASG configuration

6. **Storage Resources** (~1 minute)
   - S3 bucket: `rem-io-dev` (application storage)
   - S3 bucket: `rem-io-pg-backups-dev` (PostgreSQL backups)
   - Bucket policies for Pod Identity access

7. **Messaging Resources** (~1 minute)
   - SQS queue: File processing queue
   - SQS DLQ: File processing dead letter queue
   - SQS queue: Karpenter interruption handling
   - Queue policies

8. **Kubernetes Resources** (~2-3 minutes)
   - Namespaces: `rem`, `observability`, `postgres-cluster`, `karpenter`
   - ServiceAccounts with Pod Identity associations
   - Karpenter Helm chart installation
   - Karpenter default NodePool and EC2NodeClass

**Total Resources Created**: 117 CloudFormation resources

**Expected Outputs** (saved to CloudFormation stack):
```
ClusterName: application-cluster-a
ClusterEndpoint: https://[random].gr7.us-east-1.eks.amazonaws.com
VpcId: vpc-[id]
AppBucketName: rem-io-dev
PGBackupBucketName: rem-io-pg-backups-dev
FileProcessingQueueUrl: https://sqs.us-east-1.amazonaws.com/[account]/application-cluster-a-file-processing-dev
FileProcessingDLQUrl: https://sqs.us-east-1.amazonaws.com/[account]/application-cluster-a-file-processing-dlq-dev
KarpenterQueueUrl: https://sqs.us-east-1.amazonaws.com/[account]/application-cluster-a-karpenter-interruption
AppPodRoleArn: arn:aws:iam::[account]:role/application-cluster-a-app
OTELCollectorRoleArn: arn:aws:iam::[account]:role/application-cluster-a-otel-collector
CNPGBackupRoleArn: arn:aws:iam::[account]:role/application-cluster-a-cnpg-backup
KarpenterRoleArn: arn:aws:iam::[account]:role/application-cluster-a-karpenter
ALBControllerRoleArn: arn:aws:iam::[account]:role/application-cluster-a-alb-controller
ExternalSecretsRoleArn: arn:aws:iam::[account]:role/application-cluster-a-external-secrets
```

**Monitoring Progress**: Watch CloudFormation events in AWS Console or check `deploy.log` file created during deployment.

### Connect to Cluster

After deployment completes, configure kubectl to connect to your new cluster:

```bash
# Update kubeconfig to add cluster context
aws eks update-kubeconfig --name application-cluster-a --region us-east-1 --profile rem

# This will:
# 1. Add cluster context to ~/.kube/config
# 2. Set current context to application-cluster-a
# 3. Configure authentication via AWS IAM

# Verify connection
kubectl cluster-info

# Expected output:
# Kubernetes control plane is running at https://[random].gr7.us-east-1.eks.amazonaws.com
# CoreDNS is running at https://[random].gr7.us-east-1.eks.amazonaws.com/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

# Check cluster access
kubectl get nodes

# Expected: 2-3 nodes (initial managed node group)
# NAME                          STATUS   ROLES    AGE   VERSION
# ip-10-0-x-x.ec2.internal      Ready    <none>   5m    v1.34.x
```

### Verify Deployment

```bash
# Check namespaces
kubectl get namespaces

# Expected namespaces:
# - rem (application workloads)
# - observability (OTEL collector)
# - postgres-cluster (CloudNativePG)
# - karpenter (node autoscaling)
# - external-secrets-system
# - cert-manager
# - kube-system

# Check ServiceAccounts
kubectl get sa -n rem
# Expected: default, rem-app

kubectl get sa -n observability
# Expected: default, otel-collector

kubectl get sa -n postgres-cluster
# Expected: default, postgres-backup

# Check Pod Identity associations
aws eks list-pod-identity-associations --cluster-name application-cluster-a --profile rem

# Expected: 5 associations (rem-app, otel-collector, postgres-backup, external-secrets, karpenter)

# Check Karpenter installation
kubectl get pods -n karpenter

# Expected: karpenter-[hash] pod running

# Check Karpenter NodePool and EC2NodeClass
kubectl get nodepool
kubectl get ec2nodeclass

# Expected: default nodepool and nodeclass created

# View stack outputs
aws cloudformation describe-stacks \
  --stack-name REMApplicationClusterA \
  --profile rem \
  --query 'Stacks[0].Outputs'
```

### Post-Deployment Setup

1. **Generate and Apply ConfigMaps**:
   ```bash
   cd ../../
   ./generate-configmap.sh | kubectl apply -f -
   ```

2. **Deploy Platform Services** (see `manifests/platform/README.md`):
   - ArgoCD for GitOps
   - CloudNativePG for PostgreSQL
   - OpenTelemetry Collector
   - Arize Phoenix for LLM observability
   - External Secrets Operator
   - Cert Manager

3. **Deploy Applications** (see `manifests/application/README.md`):
   - REM API (FastAPI)
   - REM MCP (FastMCP)
   - File Processor workers

## Stack Outputs

After deployment, the following outputs are available:

- `ClusterName`: EKS cluster name
- `VpcId`: VPC ID for the cluster
- `AppBucketName`: S3 bucket for application storage (`rem-io-{env}`)
- `AppPodRoleArn`: IAM role ARN for application pods (use with Pod Identity)
- `ALBControllerRoleArn`: IAM role ARN for AWS Load Balancer Controller
- `KarpenterRoleArn`: IAM role ARN for Karpenter
- `KarpenterNodeRole`: IAM role name for Karpenter-provisioned nodes
- `OTELCollectorRoleArn`: IAM role ARN for OTEL collector
- `CNPGBackupRoleArn`: IAM role ARN for PostgreSQL backups
- `FileProcessingQueueUrl`: SQS queue URL for file processing
- `FileProcessingDLQUrl`: SQS DLQ URL for failed file processing
- `PGBackupBucketName`: S3 bucket for PostgreSQL backups (`rem-io-pg-backups-{env}`)

### Exporting Outputs for Application Use

To make these outputs available to your Kubernetes applications:

```bash
# Get all stack outputs as JSON
aws cloudformation describe-stacks \
  --stack-name REMApplicationClusterA \
  --profile rem \
  --query 'Stacks[0].Outputs' \
  --output json > stack-outputs.json

# Or get specific outputs
export APP_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name REMApplicationClusterA \
  --profile rem \
  --query 'Stacks[0].Outputs[?OutputKey==`AppBucketName`].OutputValue' \
  --output text)

export QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name REMApplicationClusterA \
  --profile rem \
  --query 'Stacks[0].Outputs[?OutputKey==`FileProcessingQueueUrl`].OutputValue' \
  --output text)
```

### Creating ConfigMaps from Outputs

Use the ConfigMap generator script (located at manifests root) to create Kubernetes ConfigMaps:

```bash
# From the manifests directory
cd ../../
./generate-configmap.sh

# Apply directly to cluster
./generate-configmap.sh | kubectl apply -f -

# Or save to file for ArgoCD
./generate-configmap.sh > application/rem-api/base/configmap.yaml
```

The script bridges infrastructure (CDK stack outputs) and application (REM settings.py):
- **Pulls from CloudFormation**: Bucket names, queue URLs, cluster metadata
- **Pulls from REM settings**: Default values, nested variable patterns, namespace architecture
- **Only overrides infrastructure-specific values**:
  - **S3__BUCKET_NAME**: `rem-io-dev` (overrides default `rem-storage`)
  - **OTEL__ENABLED**: `true` + cluster endpoint (overrides disabled default)
  - **PHOENIX__ENABLED**: `true` + cluster endpoint (overrides disabled default)
  - **POSTGRES__CONNECTION_STRING**: CloudNativePG cluster service (overrides localhost)

**Note**: See comments in generated ConfigMap YAML for REM settings.py line references.

### Using Outputs in Deployments

Reference the ConfigMap in your application Deployments:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rem-api
  namespace: rem
spec:
  template:
    spec:
      serviceAccountName: rem-app  # Uses Pod Identity for AWS access
      containers:
      - name: api
        envFrom:
        - configMapRef:
            name: rem-config
```

**Note**: Pod Identity automatically provides AWS credentials to pods using the `rem-app` ServiceAccount in the `rem` namespace. No need to manage IAM credentials manually.

## Project Structure

```
cdk-eks/
├── bin/
│   └── cdk.ts                    # CDK app entry point
├── lib/
│   ├── config.ts                 # Configuration loading and validation
│   ├── shared-resources-stack.ts # ECR, shared IAM roles
│   ├── management-cluster-stack.ts # Management cluster (future)
│   └── worker-cluster-stack.ts   # Application cluster (current)
├── .env                          # Environment configuration
├── cdk.json                      # CDK configuration
├── package.json                  # Node.js dependencies
└── tsconfig.json                 # TypeScript configuration
```

## Current State vs CLAUDE.md

### ✅ Aligned with CLAUDE.md

- **Namespace separation**: Application (`rem`), observability (`observability`), databases (`postgres-cluster`)
- **Single REM ServiceAccount**: All application workloads use `rem-app`
- **Pod Identity**: Modern AWS authentication for Kubernetes pods
- **Karpenter**: Node autoscaling for cost optimization
- **CloudNativePG**: PostgreSQL with S3 backups
- **OpenTelemetry**: Observability backbone with OTEL collector
- **External Secrets Operator**: Secret management
- **File processing**: S3 + SQS integration

### ⚠️ Not Yet Implemented (from CLAUDE.md)

- **ArgoCD**: GitOps deployment (defined in platform layer, not infra)
- **Management cluster**: Separate cluster for ArgoCD/GitOps
- **Multi-cluster**: Currently single cluster deployment
- **Arize Phoenix**: LLM observability platform

## Future Improvements

### Short Term

1. **Environment-Driven Deployment**
   - Migrate to deployment modes: `minimal`, `standard`, `full`
   - Use `getStackName()` helper for dynamic stack naming
   - Support multiple environments (dev/staging/prod)

2. **Management Cluster**
   - Deploy `ManagementClusterStack` for ArgoCD
   - Separate GitOps concerns from application clusters

3. **Production Cluster**
   - Add production worker cluster (currently commented out)
   - Separate staging and production workloads

### Medium Term

4. **Multi-Region Support**
   - Regional failover
   - Data residency compliance

5. **Advanced Monitoring**
   - Arize Phoenix for LLM observability
   - Grafana/Prometheus stack

6. **Service Mesh**
   - Istio or Linkerd for advanced traffic management
   - mTLS between services

### Long Term

7. **Multi-Cluster Federation**
   - Cross-cluster service discovery
   - Federated ArgoCD

8. **Advanced RBAC**
   - Fine-grained namespace access control
   - Integration with external identity providers

9. **Disaster Recovery**
   - Automated backup/restore procedures
   - Cross-region replication

## Deployment Learnings

### Key Insights from Production Deployment

**Deployment Timing Breakdown** (based on actual deployment):
- Total time: 19 minutes 30 seconds (1170 seconds)
- Longest phase: EKS cluster creation (8-10 minutes)
- Nested stacks: CDK creates 3 nested CloudFormation stacks
  - Main stack: `REMApplicationClusterA`
  - Cluster resource provider: `@aws-cdk--aws-eks.ClusterResourceProvider`
  - Kubectl provider: `@aws-cdk--aws-eks.KubectlProvider`

**Resource Creation Order** (critical for troubleshooting):
1. Networking foundation (VPC, subnets, IGW, NAT gateways)
2. IAM roles and policies (cluster, nodes, Pod Identity roles)
3. EKS control plane (longest wait)
4. Lambda functions for cluster management (kubectl handler, cluster resource provider)
5. Initial managed node group (for Karpenter bootstrap)
6. Kubernetes resources via Custom Resources (namespaces, ServiceAccounts, Helm charts)
7. Pod Identity associations (links ServiceAccounts to IAM roles)
8. Karpenter installation via Helm
9. Karpenter NodePool and EC2NodeClass

**Pod Identity vs IRSA**:
- Pod Identity is simpler (no OIDC thumbprints to manage)
- Associations created with `AWS::EKS::PodIdentityAssociation` resource
- Automatically injects credentials into pods matching ServiceAccount
- Works across all namespaces without annotation complexity

**Karpenter Bootstrap**:
- Requires initial managed node group to run Karpenter controller
- Default NodePool set to not provision nodes automatically (prevents cost surprises)
- EC2NodeClass uses AL2023 EKS-optimized AMI
- Interruption handling configured with SQS queue for Spot instances

**Configuration Philosophy**:
- Environment-driven via `.env` file (12-factor app methodology)
- Feature flags allow incremental enablement (ENABLE_KARPENTER, ENABLE_ADOT, etc.)
- Cost optimization defaults (Spot instances, right-sized instance types)
- Single application namespace (`rem`) consolidates permissions (simpler than per-service accounts)

**Lessons Learned**:
1. Always use `--profile` flag with CDK CLI (doesn't respect `AWS_PROFILE` env var)
2. Deployment log (`deploy.log`) essential for debugging (use `tee` to capture)
3. CloudFormation nested stacks can be confusing - watch main stack progress
4. EKS cluster creation is the bottleneck - be patient
5. Pod Identity associations happen AFTER ServiceAccounts are created
6. Karpenter Helm chart installation can fail if nodes aren't ready - CDK handles retry logic

## Troubleshooting

### Deployment Hangs

**Symptom**: CloudFormation stack shows `CREATE_IN_PROGRESS` for extended period

**Common Causes**:
- **EKS Control Plane**: 8-10 minutes is normal for `AWS::EKS::Cluster` resource
- **Node Group Creation**: 3-5 minutes for managed node group to join cluster
- **Karpenter Helm Chart**: Waits for Karpenter controller pod to be ready

**How to Monitor**:
```bash
# Watch CloudFormation events in real-time
aws cloudformation describe-stack-events \
  --stack-name REMApplicationClusterA \
  --profile rem \
  --max-items 20

# Check deploy.log for progress
tail -f deploy.log

# Check nested stack status
aws cloudformation list-stacks \
  --stack-status-filter CREATE_IN_PROGRESS \
  --profile rem
```

### Pod Identity Issues

**Symptom**: Pods can't access AWS services (S3, SQS, etc.)

**Diagnostics**:
```bash
# Verify Pod Identity associations exist
aws eks list-pod-identity-associations --cluster-name application-cluster-a --profile rem

# Expected: 5 associations
# - rem-app (namespace: rem)
# - otel-collector (namespace: observability)
# - postgres-backup (namespace: postgres-cluster)
# - external-secrets (namespace: external-secrets-system)
# - karpenter (namespace: karpenter)

# Describe specific association
aws eks describe-pod-identity-association \
  --cluster-name application-cluster-a \
  --association-id <association-id> \
  --profile rem

# Check ServiceAccount exists in cluster
kubectl describe sa rem-app -n rem

# Check pod has credentials injected (should see AWS_* env vars)
kubectl exec -n rem <pod-name> -- env | grep AWS
```

**Common Fixes**:
- Ensure pod is using correct ServiceAccount in deployment spec
- Verify namespace matches Pod Identity association
- Check IAM role trust policy allows `pods.eks.amazonaws.com` principal

### Karpenter Not Provisioning Nodes

**Symptom**: Pods remain in `Pending` state, no new nodes created

**Diagnostics**:
```bash
# Check Karpenter controller is running
kubectl get pods -n karpenter

# View Karpenter logs
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100

# Check NodePool configuration
kubectl get nodepool -o yaml

# Check EC2NodeClass configuration
kubectl get ec2nodeclass -o yaml

# Verify pending pods have resource requests
kubectl get pods -A -o wide | grep Pending
kubectl describe pod <pending-pod> -n <namespace>
```

**Common Fixes**:
- Ensure NodePool `limits` are not exceeded
- Check EC2 instance limits in AWS account
- Verify subnet tags for Karpenter discovery
- Check security group allows node-to-control-plane communication

### CDK Deployment Fails with Credential Errors

**Symptom**: `current credentials could not be used to assume 'arn:aws:iam::...:role/cdk-...'`

**Cause**: CDK bootstrap creates IAM roles that require specific permissions

**Fix**:
```bash
# Ensure AWS credentials are for correct account
aws sts get-caller-identity --profile rem

# If bootstrap roles are missing, re-run bootstrap
npx cdk bootstrap aws://852140462228/us-east-1 --profile rem

# Verify bootstrap stack exists
aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --profile rem
```

### kubectl Authentication Errors After Deployment

**Symptom**: `error: You must be logged in to the server (the server has asked for the client to provide credentials)`

**Cause**: EKS clusters restrict access to the IAM principal that created them. If you're using root account credentials or a different IAM user than the one that deployed CDK, you won't have access.

**Diagnostics**:
```bash
# Check which IAM principal kubectl is using
aws sts get-caller-identity --profile rem

# Check kubeconfig uses correct profile
kubectl config view --minify | grep -A 5 "AWS_PROFILE"
```

**Fix Option 1: Use Same AWS Profile (Recommended)**
Ensure the `AWS_PROFILE` env var in kubeconfig matches the profile used for CDK deployment:
```bash
# Re-run update-kubeconfig with correct profile
aws eks update-kubeconfig --name application-cluster-a --region us-east-1 --profile rem

# Verify the profile in kubeconfig
grep -A 10 "arn:aws:eks:us-east-1:852140462228:cluster/application-cluster-a" ~/.kube/config | grep AWS_PROFILE

# Should show: value: rem
```

**Fix Option 2: Add IAM Principal via EKS Access Entries (Recommended)**

The modern way to grant cluster access is through EKS Access Entries API (not aws-auth ConfigMap). This is simpler and more secure.

```bash
# Get your current IAM principal
aws sts get-caller-identity --profile rem

# Create access entry for your IAM user/role
aws eks create-access-entry \
  --cluster-name application-cluster-a \
  --principal-arn arn:aws:iam::852140462228:root \
  --type STANDARD \
  --profile rem \
  --region us-east-1

# Associate cluster admin policy
aws eks associate-access-policy \
  --cluster-name application-cluster-a \
  --principal-arn arn:aws:iam::852140462228:root \
  --access-scope type=cluster \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --profile rem \
  --region us-east-1

# Verify access
kubectl get nodes
```

**Available EKS Access Policies**:
- `AmazonEKSClusterAdminPolicy` - Full cluster admin (like `system:masters`)
- `AmazonEKSAdminPolicy` - Admin access to all namespaces
- `AmazonEKSEditPolicy` - Edit resources in namespaces
- `AmazonEKSViewPolicy` - Read-only access

**Note**: The CDK deployment already configures access for the cluster creator. The issue typically occurs when:
1. You're using a different AWS profile than the one used for deployment
2. Your local AWS credentials have changed/expired
3. You're using root account credentials instead of an IAM user

### Creating a Non-Root IAM User (Best Practice)

**Security Warning**: Using AWS root account credentials is not recommended for daily operations. Create a dedicated IAM user instead.

**Step 1: Create IAM User**
```bash
# Create IAM user for EKS administration
aws iam create-user \
  --user-name eks-admin \
  --profile rem

# Create access key for the user
aws iam create-access-key \
  --user-name eks-admin \
  --profile rem \
  --output json > eks-admin-credentials.json

# IMPORTANT: Save these credentials securely and delete the file after configuring AWS CLI
cat eks-admin-credentials.json
```

**Step 2: Attach Required IAM Policies**
```bash
# Attach policies for EKS and CDK operations
aws iam attach-user-policy \
  --user-name eks-admin \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSClusterPolicy \
  --profile rem

aws iam attach-user-policy \
  --user-name eks-admin \
  --policy-arn arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy \
  --profile rem

aws iam attach-user-policy \
  --user-name eks-admin \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly \
  --profile rem

# For full EKS administration, create custom policy
cat > eks-admin-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "eks:*",
        "ec2:DescribeAccountAttributes",
        "ec2:DescribeAddresses",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeNatGateways",
        "ec2:DescribeRouteTables",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "iam:ListRoles",
        "iam:GetRole",
        "iam:PassRole",
        "cloudformation:*",
        "s3:ListBucket",
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "*"
    }
  ]
}
EOF

aws iam put-user-policy \
  --user-name eks-admin \
  --policy-name EKSAdminPolicy \
  --policy-document file://eks-admin-policy.json \
  --profile rem
```

**Step 3: Configure AWS CLI Profile**
```bash
# Add new profile using the user's credentials
aws configure --profile eks-admin
# Enter AccessKeyId from eks-admin-credentials.json
# Enter SecretAccessKey from eks-admin-credentials.json
# Default region: us-east-1
# Default output: json

# Test the new profile
aws sts get-caller-identity --profile eks-admin

# Should show:
# {
#   "UserId": "AIDAXXXXXXXXXXXXXXXXX",
#   "Account": "852140462228",
#   "Arn": "arn:aws:iam::852140462228:user/eks-admin"
# }
```

**Step 4: Add IAM User to EKS Cluster**
```bash
# Create access entry for IAM user
aws eks create-access-entry \
  --cluster-name application-cluster-a \
  --principal-arn arn:aws:iam::852140462228:user/eks-admin \
  --type STANDARD \
  --profile rem \
  --region us-east-1

# Associate admin policy
aws eks associate-access-policy \
  --cluster-name application-cluster-a \
  --principal-arn arn:aws:iam::852140462228:user/eks-admin \
  --access-scope type=cluster \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --profile rem \
  --region us-east-1
```

**Step 5: Update kubeconfig to Use New Profile**
```bash
# Update kubeconfig with new IAM user profile
aws eks update-kubeconfig \
  --name application-cluster-a \
  --region us-east-1 \
  --profile eks-admin

# Verify access
kubectl get nodes

# Should now work without root credentials
```

**Step 6: Cleanup**
```bash
# Delete the credentials file (sensitive!)
rm eks-admin-credentials.json eks-admin-policy.json

# Store credentials in password manager
# Update .env file to use eks-admin profile instead of rem
```

**Benefits of IAM User over Root Account**:
1. **Granular Permissions**: Only grant necessary permissions
2. **Auditability**: Track actions to specific user in CloudTrail
3. **Revocability**: Disable user without affecting root account
4. **MFA**: Can enforce multi-factor authentication
5. **Credential Rotation**: Easier to rotate access keys

## References

- [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
- [Karpenter Documentation](https://karpenter.sh/)
- [CloudNativePG Documentation](https://cloudnative-pg.io/)
- [AWS CDK Documentation](https://docs.aws.amazon.com/cdk/v2/guide/home.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
