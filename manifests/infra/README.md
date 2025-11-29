# Infrastructure Layer

The infrastructure layer is provisioned using **AWS CDK (TypeScript)**.

## CDK EKS Stack

**Location**: `manifests/infra/cdk-eks/`

AWS CDK TypeScript infrastructure for REM EKS clusters with:
- VPC with public/private subnets across 3 AZs
- EKS cluster with managed node groups
- Karpenter for autoscaling
- Pod Identity for AWS service access
- S3 buckets for application storage and PostgreSQL backups
- SQS queues for file processing
- Storage classes optimized for PostgreSQL

## Quick Start

```bash
cd manifests/infra/cdk-eks
npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap aws://<ACCOUNT_ID>/us-east-1 --profile rem

# Deploy
npx cdk deploy --all --profile rem

# Configure kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-east-1 --profile rem
```

## What Gets Provisioned

- **VPC & Networking**: 3 AZs, public/private subnets, NAT gateways
- **EKS Cluster**: Kubernetes control plane with OIDC provider
- **Node Groups**: Initial managed node group for Karpenter bootstrap
- **Karpenter**: Node autoscaling with Spot instance support
- **Storage**: S3 buckets, SQS queues
- **IAM**: Pod Identity roles for all workloads

## Configuration

All configuration via environment variables or `.env` file in `cdk-eks/`:

```bash
AWS_PROFILE=rem
AWS_REGION=us-east-1
ENVIRONMENT=staging
DEPLOYMENT_MODE=minimal
KUBERNETES_VERSION=1.33
```

See `cdk-eks/README.md` for full configuration options.

## Stack Outputs

After deployment, outputs include:
- `ClusterName`: EKS cluster name
- `AppBucketName`: S3 bucket for application storage
- `FileProcessingQueueUrl`: SQS queue for file processing
- IAM role ARNs for Pod Identity

## Next Steps

After infrastructure deployment:
1. See `manifests/platform/README.md` for platform services (ArgoCD, CloudNativePG, etc.)
2. See `manifests/application/README.md` for REM application deployment
3. Or use `rem cluster apply` to deploy everything via CLI
