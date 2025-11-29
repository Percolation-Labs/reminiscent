# REM Kubernetes Manifests

Kubernetes deployment manifests for the REM platform, organized by layer.

## Quick Start Deployment

```bash
# 1. Install remdb and initialize (auto-downloads manifests if not present)
pip install remdb
rem cluster init --project-name myproject -y

# Or specify a specific manifest version
rem cluster init --project-name myproject --manifest-version v0.5.0 -y

# 2. Deploy CDK infrastructure
cd manifests/infra/cdk-eks
cdk deploy REMApplicationClusterA

# 3. Setup SSM parameters
rem cluster setup-ssm

# 4. Generate all manifests (includes SQL ConfigMap)
rem cluster generate

# 5. Validate prerequisites
rem cluster validate

# 6. Deploy via ArgoCD
kubectl apply -f manifests/application/rem-stack/argocd-staging.yaml
```

**Note:** Manifests are versioned separately from the `remdb` package. Use `--manifest-version` to pin to a specific release.

For detailed troubleshooting and deployment checklist, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Directory Structure

```
manifests/
├── cluster-config.yaml  # Deployment configuration (edit for your environment)
├── infra/               # Infrastructure layer (EKS, VPC, IAM)
│   └── cdk-eks/        # AWS CDK for EKS deployment
├── platform/            # Platform services (ArgoCD, OTEL, PostgreSQL)
│   ├── argocd/         # GitOps deployment
│   │   └── applications/  # ArgoCD Application manifests
│   ├── external-secrets/  # ClusterSecretStores
│   ├── otel/           # OpenTelemetry collector
│   ├── arize-phoenix/  # LLM observability
│   ├── cloudnative-pg/ # PostgreSQL operator
│   ├── cert-manager/   # Certificate management
│   └── keda/           # Event-driven autoscaling
├── application/         # Application workloads
│   └── rem-stack/      # Full REM stack (API, workers, postgres)
│       ├── components/ # Base components
│       └── overlays/   # Environment-specific configs
└── TROUBLESHOOTING.md  # Deployment guide and common issues
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

### Using CLI (Recommended)

```bash
# 1. Initialize config for your project
rem cluster init --project-name myproject --git-repo https://github.com/myorg/myrepo.git

# 2. Deploy CDK infrastructure
cd manifests/infra/cdk-eks
cdk deploy REMApplicationClusterA

# 3. Setup AWS SSM parameters (secrets)
rem cluster setup-ssm

# 4. Generate all manifests (includes SQL ConfigMap)
rem cluster generate

# 5. Validate all prerequisites are met
rem cluster validate

# 6. Deploy application via ArgoCD
kubectl apply -f manifests/application/rem-stack/argocd-staging.yaml
```

### Manual Deployment

1. **Deploy Infrastructure** (see `infra/cdk-eks/README.md`)
   ```bash
   cd infra/cdk-eks
   npx cdk deploy --profile rem
   ```

2. **Create SSM Parameters**
   ```bash
   aws ssm put-parameter --name "/rem/postgres/username" --value "remuser" --type String
   aws ssm put-parameter --name "/rem/postgres/password" --value "$(openssl rand -base64 24)" --type SecureString
   aws ssm put-parameter --name "/rem/llm/anthropic-api-key" --value "sk-ant-..." --type SecureString
   aws ssm put-parameter --name "/rem/llm/openai-api-key" --value "sk-..." --type SecureString
   ```

3. **Deploy Platform Services** (see `platform/README.md`)
   ```bash
   kubectl apply -f platform/argocd/applications/external-secrets-operator.yaml
   kubectl apply -f platform/argocd/applications/cloudnative-pg.yaml
   kubectl apply -f platform/argocd/applications/keda.yaml
   kubectl apply -f platform/external-secrets/cluster-secret-store.yaml
   kubectl apply -f platform/external-secrets/kubernetes-cluster-secret-store.yaml
   ```

4. **Generate All Manifests** (includes SQL ConfigMap)
   ```bash
   rem cluster generate
   ```

5. **Deploy Application**
   ```bash
   kubectl apply -f application/rem-stack/argocd-staging.yaml
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
