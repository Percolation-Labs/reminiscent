# KEDA (Kubernetes Event-Driven Autoscaling)

Event-driven autoscaling for Kubernetes workloads based on external metrics.

## Overview

KEDA enables scaling based on:
- **AWS SQS queue depth** (our use case)
- Kafka topic lag
- Redis list length
- CloudWatch metrics
- Prometheus metrics
- HTTP requests
- Cron schedules
- 60+ other scalers

## Architecture

```
SQS Queue (30 messages)
         │
         │ Metrics API
         ▼
KEDA Operator (polls every 10s)
         │
         │ Scale decision: 30 msgs / 10 target = 3 pods
         ▼
HPA (Horizontal Pod Autoscaler)
         │
         ▼
Deployment: file-processor (3 replicas)
         │
         ▼
Karpenter (provisions nodes if needed)
```

## Installation

### Via ArgoCD (Recommended)

```bash
kubectl apply -f manifests/platform/keda/application.yaml
```

### Manual Helm Install

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update
helm install keda kedacore/keda \
  --namespace keda \
  --create-namespace \
  --version 2.16.0
```

## IRSA Setup for AWS SQS Scaling

KEDA needs AWS permissions to query SQS queue attributes. Two models:

### Model 1: Operator Identity (Simpler)

KEDA operator has IAM permissions, workload pods use separate identity.

**Pulumi (add to `manifests/infra/pulumi/resources.yaml`):**

```yaml
  # IAM Policy for KEDA operator to read SQS metrics
  kedaOperatorPolicy:
    type: aws:iam:Policy
    properties:
      name: keda-operator-sqs-metrics
      description: Allows KEDA to read SQS queue attributes
      policy:
        fn::toJSON:
          Version: "2012-10-17"
          Statement:
            - Sid: AllowSQSMetrics
              Effect: Allow
              Action:
                - sqs:GetQueueAttributes
                - sqs:ListQueues
              Resource: "*"  # Or scope to specific queue ARN
      tags:
        Purpose: keda-sqs-scaler
        Component: keda-iam

  # IAM Role for KEDA operator (IRSA)
  kedaOperatorRole:
    type: aws:iam:Role
    properties:
      name: keda-operator-role
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
                  "${eksCluster.oidcProviderUrl}:sub": "system:serviceaccount:keda:keda-operator"
                  "${eksCluster.oidcProviderUrl}:aud": "sts.amazonaws.com"
      tags:
        Purpose: keda-operator-irsa
        Component: keda-iam

  # Attach policy to role
  kedaPolicyAttachment:
    type: aws:iam:RolePolicyAttachment
    properties:
      role: ${kedaOperatorRole.name}
      policyArn: ${kedaOperatorPolicy.arn}

outputs:
  kedaOperatorRoleArn:
    value: ${kedaOperatorRole.arn}
```

**Update ServiceAccount annotation:**

```bash
kubectl annotate serviceaccount keda-operator \
  -n keda \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/keda-operator-role
```

Or update `manifests/platform/keda/application.yaml`:

```yaml
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT_ID:role/keda-operator-role
```

### Model 2: Pod Identity (More Complex)

Each workload pod has its own IAM role, KEDA assumes that role.

Requires trust relationship between KEDA operator role and workload role. Not recommended for simple use cases.

## Verify IRSA

```bash
# Check ServiceAccount annotation
kubectl get sa keda-operator -n keda -o yaml | grep role-arn

# Check environment variables injected into pod
kubectl get pod -n keda -l app.kubernetes.io/name=keda-operator -o yaml | grep -A5 env:

# Should see:
# - AWS_ROLE_ARN
# - AWS_WEB_IDENTITY_TOKEN_FILE
# - AWS_STS_REGIONAL_ENDPOINTS
```

## Verify Installation

```bash
# Check KEDA pods
kubectl get pods -n keda

# Check CRDs
kubectl get crd | grep keda

# Expected CRDs:
# - scaledobjects.keda.sh
# - scaledjobs.keda.sh
# - triggerauthentications.keda.sh
# - clustertriggerauthentications.keda.sh
```

## Next Steps

After KEDA is installed:

1. Create TriggerAuthentication (if using Pod Identity model)
2. Create ScaledObject for your deployment
3. Deploy your workload

See `manifests/application/file-processor/` for example ScaledObject configuration.

## Troubleshooting

### Access Denied Errors

```bash
# Restart KEDA operator to pick up IRSA changes
kubectl rollout restart deployment/keda-operator -n keda
kubectl rollout restart deployment/keda-metrics-server -n keda
```

### CRD Annotation Length Issues with ArgoCD

If you see errors about annotation length, ensure `ServerSideApply=true` is set in ArgoCD sync options (already configured in application.yaml).

### Check KEDA Logs

```bash
# Operator logs
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=100

# Metrics server logs
kubectl logs -n keda -l app.kubernetes.io/name=keda-metrics-server --tail=100
```

## References

- [KEDA Documentation](https://keda.sh/)
- [AWS SQS Scaler](https://keda.sh/docs/2.16/scalers/aws-sqs/)
- [AWS EKS IRSA](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [AWS Guidance: KEDA on EKS](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/event-driven-auto-scaling-with-eks-pod-identity-and-keda.html)
