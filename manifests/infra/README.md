# Infrastructure Layer

The infrastructure layer is provisioned using **AWS CDK (TypeScript)**.

## Prerequisites

Install these tools (or ask your AI to help):
- kubectl, Docker Desktop, aws cli, node, gh (standard cloud dev tools)
- [Tilt](https://tilt.dev) - for local development

## Local Development First

Before deploying to EKS, test locally with Tilt:

```bash
cd rem
tilt up
# Dashboard: http://localhost:10350
```

See [manifests/local/README.md](../local/README.md) for full local dev documentation.
 
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
- ArgoCD (optional, via Helm chart)
- SSM Parameters for External Secrets (optional)

## Quick Start

```bash
cd manifests/infra/cdk-eks
cp .env.example .env
# Edit .env with your AWS account, API keys, etc.

npm install

# Bootstrap CDK (first time only)
npx cdk bootstrap aws://<ACCOUNT_ID>/us-east-1 --profile <profile>

# Deploy (includes ArgoCD + SSM params if enabled)
npx cdk deploy --all --profile <profile>

# Configure kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-east-1 --profile <profile>

# Deploy ArgoCD applications
rem cluster apply
```

## What Gets Provisioned

- **VPC & Networking**: 3 AZs, public/private subnets, NAT gateways
- **EKS Cluster**: Kubernetes control plane with OIDC provider
- **Node Groups**: Initial managed node group for Karpenter bootstrap
- **Karpenter**: Node autoscaling with Spot instance support
- **Storage**: S3 buckets, SQS queues
- **IAM**: Pod Identity roles for all workloads
- **ArgoCD**: GitOps controller (optional via `ENABLE_ARGOCD`)
- **SSM Parameters**: Secrets for External Secrets Operator (optional via `ENABLE_SSM_PARAMETERS`)

## Configuration

All configuration via `.env` file in `cdk-eks/`. See `.env.example` for all options:

```bash
# Required
AWS_ACCOUNT_ID=123456789012
AWS_PROFILE=rem
AWS_REGION=us-east-1

# Cluster
CLUSTER_NAME_PREFIX=rem
ENVIRONMENT=staging

# Optional: SSM Parameters (for External Secrets)
ENABLE_SSM_PARAMETERS=true
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...

# Optional: ArgoCD (disable for management cluster pattern)
ENABLE_ARGOCD=true
```

See `cdk-eks/README.md` for full configuration options.

## Next Steps

After CDK deployment completes:

```bash
# Configure kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-east-1 --profile <profile>

# Deploy ArgoCD applications (platform + rem-stack)
rem cluster apply
```

That's it! The `rem cluster apply` command deploys all platform services and the REM application stack via ArgoCD.
