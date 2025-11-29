# REM Application Manifests

This directory contains Kubernetes manifests for the REM stack, organized using **Kustomize** for multi-environment deployment with semantic versioning.

## Architecture

The REM stack consists of **2 deployments** in the `rem-app` namespace:

1. **rem-api**: FastAPI server with **MCP server mounted** (not separate)
2. **file-processor**: KEDA-scaled worker for file processing

**Important**: The MCP (Model Context Protocol) server is **not a separate deployment**. It is mounted as part of the rem-api FastAPI application.

## Namespace Structure

The application uses **3 namespaces**:

- **rem-app**: All application components (api + worker)
- **observability**: OpenTelemetry collector (optional, future)
- **postgres**: PostgreSQL cluster (deployed separately)

This keeps infrastructure simple and follows Kubernetes best practices.

## Directory Structure

```
application/
└── rem-stack/                 # Kustomize-based deployment
    ├── components/            # Individual components
    │   ├── api/              # REM API (FastAPI with MCP mounted)
    │   │   ├── deployment.yaml
    │   │   ├── service.yaml
    │   │   ├── ingress.yaml
    │   │   ├── hpa.yaml
    │   │   ├── pdb.yaml
    │   │   ├── serviceaccount.yaml
    │   │   ├── secretstore.yaml       # Shared SecretStore
    │   │   ├── external-secret.yaml   # LLM API keys
    │   │   ├── configmap.yaml
    │   │   └── kustomization.yaml
    │   ├── worker/           # File processor (KEDA-scaled)
    │   │   ├── deployment.yaml
    │   │   ├── keda-scaledobject.yaml
    │   │   ├── serviceaccount.yaml
    │   │   └── kustomization.yaml
    │   └── postgres/         # PostgreSQL cluster (deploy separately)
    │       ├── postgres-cluster.yaml
    │       ├── postgres-init-configmap.yaml  # Generated from SQL
    │       └── kustomization.yaml
    ├── base/                  # Base configuration (references components)
    │   └── kustomization.yaml # Namespace: rem-app, ConfigMapGenerator
    ├── overlays/              # Environment-specific configuration
    │   ├── staging/          # Staging environment (v1.2.3-rc.1)
    │   │   └── kustomization.yaml
    │   └── prod/             # Production environment (v1.2.3)
    │       └── kustomization.yaml
    ├── argocd-staging.yaml   # ArgoCD Application for staging
    ├── argocd-prod.yaml      # ArgoCD Application for production
    └── README.md             # Detailed KEDA + ArgoCD documentation
```

## ConfigMap Automation

The REM application uses ConfigMaps generated from CDK infrastructure outputs. These ConfigMaps eliminate hardcoded values and ensure consistency between infrastructure and application layers.

### ConfigMaps Generated

Three ConfigMaps are automatically generated from the CDK stack:

1. **rem-config** (namespace: rem-api)
   - `S3__BUCKET_NAME`: S3 bucket for file storage
   - `ENVIRONMENT`: Deployment environment
   - `OTEL__*`: OpenTelemetry configuration
   - `PHOENIX__*`: Arize Phoenix configuration
   - `POSTGRES__CONNECTION_STRING`: PostgreSQL connection
   - `CLUSTER_NAME`, `VPC_ID`: Infrastructure metadata

2. **rem-queues** (namespace: rem-api)
   - `FILE_PROCESSING_QUEUE_URL`: SQS queue URL for file processing

3. **rem-postgres-backup** (namespace: rem-api)
   - `BACKUP_BUCKET_NAME`: S3 bucket for PostgreSQL backups

### Generating ConfigMaps

After deploying or updating CDK infrastructure:

```bash
# Generate and apply ConfigMaps from CDK stack outputs
./manifests/generate-configmap.sh | kubectl apply -f -
```

The script:
- Fetches outputs from the CDK CloudFormation stack
- Generates ConfigMaps with appropriate namespace and labels
- Outputs YAML to stdout for kubectl apply

### Deployment Integration

Both API and worker deployments reference these ConfigMaps:

```yaml
# API and Worker use envFrom to import entire ConfigMaps
envFrom:
- configMapRef:
    name: rem-config  # S3, OTEL, Phoenix, Postgres settings
- configMapRef:
    name: rem-queues  # SQS queue URLs (worker only)
```

### KEDA ScaledObject Limitation

⚠️ **Important**: KEDA ScaledObject trigger metadata does **not** support ConfigMap references. The queue URL must be hardcoded:

```yaml
# manifests/application/rem-stack/components/worker/keda-scaledobject.yaml
triggers:
- type: aws-sqs-queue
  metadata:
    queueURL: https://sqs.us-east-1.amazonaws.com/852140462228/application-cluster-a-file-processing-dev
```

**When to update**: After regenerating ConfigMaps from CDK changes, manually verify the KEDA ScaledObject matches:

```bash
# Get queue URL from ConfigMap
kubectl get configmap rem-queues -n rem-api -o jsonpath='{.data.FILE_PROCESSING_QUEUE_URL}'

# Compare with KEDA ScaledObject
kubectl get scaledobject file-processor-scaler -n rem-api -o yaml | grep queueURL
```

### CI/CD Integration

For automated deployments:

```bash
# 1. Deploy/update CDK infrastructure
cd manifests/infra/cdk-eks
cdk deploy

# 2. Regenerate ConfigMaps
cd ../../..
./manifests/generate-configmap.sh | kubectl apply -f -

# 3. Verify KEDA ScaledObject queue URL matches ConfigMap
QUEUE_URL=$(kubectl get configmap rem-queues -n rem-api -o jsonpath='{.data.FILE_PROCESSING_QUEUE_URL}')
echo "ConfigMap queue URL: $QUEUE_URL"
echo "Update keda-scaledobject.yaml if needed"

# 4. Deploy application
kubectl apply -k manifests/application/rem-stack/overlays/staging
```

## Quick Start

### Deploy to Staging

```bash
# Set environment variables
export ECR_REGISTRY="123456789012.dkr.ecr.us-east-1.amazonaws.com"
export IMAGE_TAG="v1.2.3-rc.1"

# Deploy
kubectl apply -k manifests/application/rem-stack/overlays/staging
```

### Deploy to Production

```bash
export ECR_REGISTRY="123456789012.dkr.ecr.us-east-1.amazonaws.com"
export IMAGE_TAG="v1.2.3"

kubectl apply -k manifests/application/rem-stack/overlays/prod
```

### Deploy with ArgoCD (GitOps)

```bash
# 1. Fork this repository
# 2. Update argocd-*.yaml with your fork URL
# 3. Apply ArgoCD Applications
kubectl apply -f manifests/application/rem-stack/argocd-staging.yaml
kubectl apply -f manifests/application/rem-stack/argocd-prod.yaml
```

## Components

### rem-api (Deployment)
- **FastAPI server** with REST and streaming endpoints
- **MCP server mounted** at `/api/v1/mcp` (not separate)
- Horizontal Pod Autoscaler (HPA) for CPU-based scaling
- Pod Disruption Budget (PDB) for high availability
- External Secrets for LLM API keys (Anthropic, OpenAI)
- Ingress for external access

### file-processor (Deployment)
- **KEDA-scaled worker** for file processing
- Scales **0-20 replicas** based on SQS queue depth
- Spot instances preferred (cost optimization)
- Pod anti-affinity for distribution
- Same SecretStore as API (shared AWS resources)

### PostgreSQL (Separate)
- **CloudNativePG cluster** (deployed independently)
- Init scripts via ConfigMap (generated from `rem/sql/migrations/*.sql`)
- pgvector extension for semantic search
- Deployed to `postgres` namespace

## PostgreSQL Separate Deployment

PostgreSQL can be deployed independently:

```bash
# Deploy postgres only
kubectl apply -k manifests/application/rem-stack/components/postgres

# Or include in main stack by uncommenting in base/kustomization.yaml:
# resources:
#   - ../components/postgres
```

### SQL Init Scripts

PostgreSQL initialization scripts are included when generating cluster manifests:

```bash
# Generate all manifests (includes SQL ConfigMap)
rem cluster generate

# The command generates:
# - ArgoCD Application manifests
# - ClusterSecretStore configurations
# - SQL init ConfigMap (from rem/sql/migrations/*.sql)
```

## Features

- **Semantic Versioning**: Tag images with semver (v1.2.3, v1.2.3-rc.1)
- **KEDA Autoscaling**: Worker scales 0-20 based on SQS queue depth
- **ArgoCD Integration**: GitOps with automatic sync
- **Environment Overlays**: Staging vs Production configurations
- **Component-Based**: Deploy individual services or full stack

## Documentation

For detailed documentation, see:
- [rem-stack/README.md](rem-stack/README.md) - Complete deployment guide
- [rem-stack/components/postgres/](rem-stack/components/postgres/) - PostgreSQL setup

## Migration from Old Structure

**Old structure (removed):**
```
application/
├── rem-api/        # Individual manifests
├── rem-mcp/        # Individual manifests
└── file-processor/ # Individual manifests
```

**New structure (current):**
```
application/
└── rem-stack/      # Kustomize-only approach
    └── components/ # Organized by component
```

All manifests have been moved to `rem-stack/components/` for a cleaner, Kustomize-native structure.
