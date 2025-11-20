# REM Kubernetes Manifests

Kubernetes deployment manifests for the REM platform, organized by layer.

## Directory Structure

```
manifests/
├── infra/              # Infrastructure layer (EKS, VPC, IAM)
│   ├── cdk-eks/       # AWS CDK for EKS deployment
│   └── eks-yaml/      # Pulumi YAML for EKS (alternative)
├── platform/           # Platform services (ArgoCD, OTEL, PostgreSQL)
│   ├── argocd/        # GitOps deployment
│   ├── otel/          # OpenTelemetry collector
│   ├── arize-phoenix/ # LLM observability
│   ├── cloudnative-pg/# PostgreSQL operator
│   ├── cert-manager/  # Certificate management
│   └── keda/          # Event-driven autoscaling
├── application/        # Application workloads
│   ├── rem-api/       # FastAPI server
│   ├── rem-mcp/       # FastMCP server
│   └── file-processor/# File processing workers
└── generate-configmap.sh  # ConfigMap generator (bridges infra + app)
```

## ConfigMap Generator

The `generate-configmap.sh` script bridges infrastructure (CDK/CloudFormation outputs) with application configuration (REM settings.py).

### Purpose

- **Pull from CloudFormation**: Infrastructure-created resources (bucket names, queue URLs, cluster metadata)
- **Pull from REM settings**: Application defaults, nested variable patterns (`S3__*`, `OTEL__*`)
- **Only override infrastructure-specific values**: Skip settings that have sensible local defaults

### Usage

```bash
# Generate ConfigMaps (outputs to stdout)
./generate-configmap.sh

# Apply directly to cluster
./generate-configmap.sh | kubectl apply -f -

# Save to file for version control
./generate-configmap.sh > application/rem-api/base/configmap.yaml

# Custom stack/namespace/profile
./generate-configmap.sh REMApplicationClusterA rem rem
```

### Generated ConfigMaps

1. **rem-config** (namespace: `rem`)
   - S3 bucket name (overrides `rem-storage` → `rem-io-dev`)
   - OTEL endpoint (enables OTEL, points to `observability` namespace)
   - Phoenix endpoint (enables Phoenix, points to `observability` namespace)
   - Postgres connection string (points to `postgres-cluster` namespace)

2. **rem-queues** (namespace: `rem`)
   - SQS queue URLs for file processing

3. **rem-postgres-backup** (namespace: `postgres-cluster`)
   - S3 backup bucket for CloudNativePG operator

### How It Works

The script:
1. Fetches CloudFormation stack outputs via AWS CLI
2. Knows REM's expected environment variable structure (from `rem/src/rem/settings.py`)
3. Knows cluster namespace architecture (`rem`, `observability`, `postgres-cluster`)
4. Generates Kubernetes ConfigMaps with comments referencing settings.py line numbers
5. Only includes values that differ from application defaults

### Example Output

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rem-config
  namespace: rem
data:
  # Default: rem-storage -> Override with CDK-created bucket
  S3__BUCKET_NAME: "rem-io-dev"

  # Default: OTEL__ENABLED=false -> Enable in cluster
  OTEL__ENABLED: "true"
  OTEL__COLLECTOR_ENDPOINT: "http://otel-collector.observability.svc.cluster.local:4318"

  # ... more settings ...
```

## Deployment Workflow

1. **Deploy Infrastructure** (see `infra/*/README.md`)
   ```bash
   cd infra/cdk-eks
   npx cdk deploy --profile rem
   ```

2. **Generate ConfigMaps**
   ```bash
   cd ../..
   ./generate-configmap.sh | kubectl apply -f -
   ```

3. **Deploy Platform Services** (see `platform/README.md`)
   ```bash
   kubectl apply -k platform/argocd/
   ```

4. **Deploy Applications** (see `application/README.md`)
   ```bash
   kubectl apply -f application/rem-api/argocd-application.yaml
   ```

## Configuration Philosophy

Following CLAUDE.md principles:

- **Infrastructure layer** creates resources (EKS, S3, SQS, VPC)
- **Platform layer** installs operators and shared services (ArgoCD, OTEL, PostgreSQL)
- **Application layer** deploys REM workloads
- **ConfigMap generator** bridges the gap, pulling from both infra outputs and app requirements

## References

- Infrastructure: `infra/*/README.md`
- Platform: `platform/README.md`
- Application: `application/README.md`
- REM Settings: `../rem/src/rem/settings.py`
