# Platform Layer

Platform components deployed via ArgoCD using OCI Helm charts.

## Quick Start: Zero-Touch Bootstrap

For a fresh cluster, use the bootstrap script which handles all prerequisites:

```bash
# 1. Install rem CLI (required)
pip install remdb

# 2. Copy and configure environment variables
cp .env.example .env
# Edit .env with your values (API keys, GitHub credentials, repo URL)
source .env

# 3. Validate prerequisites
./scripts/validate-prereqs.sh

# 4. Run bootstrap (creates SSM params, secrets, and deploys ArgoCD apps)
./scripts/bootstrap-argocd.sh
```

**Required environment variables:**
| Variable | Description |
|----------|-------------|
| `GITHUB_REPO_URL` | Your fork's URL (e.g., `https://github.com/YOUR_ORG/YOUR_REPO.git`) |
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `OPENAI_API_KEY` | OpenAI API key |
| `GITHUB_PAT` | GitHub Personal Access Token (repo scope) |
| `GITHUB_USERNAME` | GitHub username |

**Optional environment variables:**
| Variable | Description |
|----------|-------------|
| `GOOGLE_CLIENT_ID` | Google OAuth client ID (placeholder if not set) |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret (placeholder if not set) |
| `AWS_PROFILE` | AWS profile to use (default: `rem`) |
| `REM_NAMESPACE` | Kubernetes namespace (default: `rem`) |

The bootstrap script will:
1. Create SSM parameters for all secrets (auto-generates PostgreSQL password, Phoenix keys, etc.)
2. Create ArgoCD repository secret for private repo access
3. Use `rem` CLI to generate PostgreSQL init ConfigMaps
4. Deploy platform-apps (app-of-apps) and rem-stack

## Forking This Stack

This stack is designed to be forkable. ArgoCD Applications currently point to `https://github.com/Percolation-Labs/reminiscent.git`.

**After forking**, update the repository URL in all ArgoCD application files:

```bash
# Replace in all ArgoCD application files
find manifests -name "*.yaml" -exec \
  sed -i '' 's|https://github.com/Percolation-Labs/reminiscent.git|https://github.com/YOUR_ORG/YOUR_REPO.git|g' {} \;
```

**For private repos**, create an ArgoCD repository secret:
```bash
kubectl create secret generic repo-your-repo \
  --namespace argocd \
  --from-literal=url=https://github.com/YOUR_ORG/YOUR_REPO.git \
  --from-literal=username=<github-user> \
  --from-literal=password=<github-pat> \
  --from-literal=type=git
kubectl label secret repo-your-repo -n argocd argocd.argoproj.io/secret-type=repository
```

## Components

### CDK-Managed (Infrastructure Layer)

These are deployed by CDK as EKS addons - no manual installation needed:

- **aws-load-balancer-controller**: ALB/NLB provisioning (deployed by `EksAddonsStack`)
- **karpenter**: Node autoscaling (deployed by `EksAddonsStack`)

### ArgoCD Applications (`argocd/applications/`)

Platform components deployed as ArgoCD Applications using the OCI repository pattern:

1. **cert-manager** (sync-wave: -1): Certificate management - deploys first
2. **cluster-issuers** (sync-wave: 0): ClusterIssuers for cert-manager
3. **external-secrets-operator** (sync-wave: 0): Secret management from AWS Parameter Store
4. **cluster-secret-stores** (sync-wave: 1): ClusterSecretStores for AWS SSM and K8s secrets
5. **cloudnative-pg** (sync-wave: 1): PostgreSQL operator for database clusters
6. **opentelemetry-operator** (sync-wave: 1): OTEL instrumentation and collection (uses cert-manager for webhook certs)
7. **keda** (sync-wave: 1): Event-driven autoscaling for workers

**Note:** Phoenix (LLM observability) is deployed via rem-stack, not as a platform app.

## Deployment

### Prerequisites

1. **Infrastructure deployed** - see [../infra/eks-yaml/README.md](../infra/eks-yaml/README.md)
2. **kubeconfig** configured: `export KUBECONFIG=~/.kube/rem-cluster-config`
3. **Secrets** in AWS Parameter Store (see Configuration section below)

### Install Platform Operators (Manual - without ArgoCD)

If not using ArgoCD, install operators manually:

```bash
# Add Helm repos
helm repo add external-secrets https://charts.external-secrets.io
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo update

# Install External Secrets Operator
# IMPORTANT: Use namespace external-secrets-system to match CDK Pod Identity association
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets-system --create-namespace --wait

# Install CloudNativePG operator
helm install cnpg cnpg/cloudnative-pg \
  -n cnpg-system --create-namespace --wait

# Apply ClusterSecretStores (connects to AWS Parameter Store and Kubernetes secrets)
kubectl apply -k manifests/platform/external-secrets/

# Verify ClusterSecretStores are Ready
kubectl get clustersecretstore
```

**Note:** If using ArgoCD (below), ClusterSecretStores are deployed automatically via the `cluster-secret-stores` Application.

### Install ArgoCD (Optional - for GitOps)

```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get admin password (optional - for UI access)
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### Deploy Platform Components (ArgoCD)

```bash
# Deploy all platform components via App-of-Apps
kubectl apply -f manifests/platform/argocd/app-of-apps.yaml

# Monitor deployment
watch kubectl get applications -n argocd

# All applications should show: HEALTH=Healthy, STATUS=Synced
```

### Deployment Order (Automatic via Sync-Waves)

ArgoCD manages dependencies using sync-wave annotations:

| Wave | Components | Notes |
|------|-----------|-------|
| -1 | cert-manager | Must be first (CRDs needed by others) |
| 0 | cluster-issuers, external-secrets-operator | Need cert-manager CRDs |
| 1 | cluster-secret-stores, cloudnative-pg, keda, opentelemetry-operator | Need ESO/cert-manager ready |

The OTEL operator uses cert-manager to generate webhook certificates (via `selfsigned-cluster-issuer`).

**Note:** ALB Controller and Karpenter are deployed by CDK, not ArgoCD.

## OCI Registry Pattern

All platform components use `oci://` URLs for Helm charts:

```yaml
source:
  repoURL: oci://ghcr.io/external-secrets/charts
  chart: external-secrets
  targetRevision: 0.11.1
```

Benefits:
- Version pinning
- Faster deployments
- No git polling
- Standard OCI ecosystem

## Prerequisites

Before deploying platform layer:

1. Infrastructure layer (Pulumi) must be complete
2. ArgoCD must be installed in the cluster
3. Environment variables from infra layer must be set
4. ECR access configured for pulling images

## Configuration

### AWS Parameter Store Secrets

**Recommended:** Use the bootstrap script which creates all SSM parameters automatically:
```bash
./scripts/bootstrap-argocd.sh
```

**Manual creation** (if not using bootstrap):

```bash
# PostgreSQL credentials (required)
# IMPORTANT: Username MUST be "remuser" to match CNPG cluster owner spec
aws ssm put-parameter --name /rem/postgres/username --value "remuser" --type String
aws ssm put-parameter --name /rem/postgres/password --value "$(openssl rand -base64 24)" --type SecureString

# LLM API keys (required)
aws ssm put-parameter --name /rem/llm/anthropic-api-key --value "sk-ant-..." --type SecureString
aws ssm put-parameter --name /rem/llm/openai-api-key --value "sk-..." --type SecureString

# Phoenix secrets (required for observability)
aws ssm put-parameter --name /rem/phoenix/api-key --value "$(openssl rand -base64 32)" --type SecureString
aws ssm put-parameter --name /rem/phoenix/secret --value "$(openssl rand -base64 32)" --type SecureString
aws ssm put-parameter --name /rem/phoenix/admin-secret --value "$(openssl rand -base64 32)" --type SecureString

# Auth secrets
aws ssm put-parameter --name /rem/auth/session-secret --value "$(openssl rand -base64 32)" --type SecureString

# Optional: OAuth credentials (use "placeholder" if not using Google OAuth)
aws ssm put-parameter --name /rem/auth/google-client-id --value "placeholder" --type String
aws ssm put-parameter --name /rem/auth/google-client-secret --value "placeholder" --type SecureString
```

### Pod Identity

Platform components use **EKS Pod Identity** (not IRSA) for AWS access. Pod Identity associations are created by CDK:

| Service Account | Namespace | Purpose |
|-----------------|-----------|---------|
| `external-secrets` | `external-secrets-system` | SSM Parameter Store access |
| `postgres-backup` | `postgres-cluster` | S3 backups for CNPG |
| `aws-load-balancer-controller` | `kube-system` | ALB/NLB management |
| `otel-collector` | `observability` | CloudWatch/X-Ray export |
| `rem-app` | `rem` | Application AWS access (S3, SQS) |

Pod Identity requires no service account annotations - IAM roles are associated via AWS API.

Verify associations:
```bash
aws eks list-pod-identity-associations --cluster-name <cluster-name> --region us-east-1
```

## Verification

```bash
# Check platform operators (manual install)
kubectl get pods -n external-secrets-system
kubectl get pods -n cnpg-system

# Check ClusterSecretStore is Ready
kubectl get clustersecretstore aws-parameter-store

# Check External Secrets syncing
kubectl get externalsecrets -A

# Check ArgoCD applications (if using ArgoCD)
kubectl get applications -n argocd
```

## Troubleshooting

### ArgoCD Application Stuck

```bash
# Check logs
kubectl logs -n argocd deployment/argocd-application-controller

# Force sync
kubectl patch application <name> -n argocd --type merge \
  -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

### External Secrets Not Syncing

```bash
# Check ClusterSecretStore status
kubectl describe clustersecretstore aws-parameter-store

# Check operator logs
kubectl logs -n external-secrets-system deployment/external-secrets

# Verify Pod Identity is working (operator should have AWS_* env vars)
kubectl exec -n external-secrets-system deploy/external-secrets -- env | grep AWS

# Check ExternalSecret status
kubectl describe externalsecret <name> -n <namespace>
```

### CloudNativePG Issues

```bash
# Check operator
kubectl logs -n cnpg-system deployment/cnpg-controller-manager

# Check cluster
kubectl describe cluster <name> -n <namespace>
```
