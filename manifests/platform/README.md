# Platform Layer

Platform components deployed via ArgoCD using OCI Helm charts.

## Forking This Stack

This stack is designed to be forkable. ArgoCD Applications use `${GIT_REPO_URL}` as a placeholder.

**After forking**, replace `${GIT_REPO_URL}` with your repository URL:

```bash
# Replace in all ArgoCD application files
find manifests/platform/argocd -name "*.yaml" -exec \
  sed -i '' 's|\${GIT_REPO_URL}|https://github.com/YOUR_ORG/YOUR_REPO.git|g' {} \;
```

## Components

### CDK-Managed (Infrastructure Layer)

These are deployed by CDK as EKS addons - no manual installation needed:

- **aws-load-balancer-controller**: ALB/NLB provisioning (deployed by `EksAddonsStack`)
- **karpenter**: Node autoscaling (deployed by `EksAddonsStack`)

### ArgoCD Applications (`argocd/applications/`)

Platform components deployed as ArgoCD Applications using the OCI repository pattern:

1. **cert-manager**: Certificate management
2. **external-secrets-operator**: Secret management from AWS Parameter Store
3. **cluster-secret-stores**: ClusterSecretStores for AWS SSM and K8s secrets
4. **cloudnative-pg**: PostgreSQL operator for database clusters
5. **opentelemetry-operator**: OTEL instrumentation and collection
6. **keda**: Event-driven autoscaling for workers
7. **arize-phoenix**: LLM observability platform

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

### Deployment Order (Automatic)

ArgoCD manages dependencies and deploys in this order:

1. **cert-manager** (required by opentelemetry-operator)
2. **external-secrets-operator** (required by ClusterSecretStores)
3. **cluster-secret-stores** (required by applications using ExternalSecrets)
4. **cloudnative-pg** (required by applications with databases)
5. **keda** (required by event-driven autoscaling)
6. **opentelemetry-operator** (required by instrumented applications)
7. **arize-phoenix** (LLM observability)

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

Before deploying, populate required secrets in AWS Parameter Store:

```bash
# PostgreSQL credentials (required)
aws ssm put-parameter --name /rem/postgres/username --value "remuser" --type String
aws ssm put-parameter --name /rem/postgres/password --value "$(openssl rand -base64 24)" --type SecureString

# LLM API keys (required)
aws ssm put-parameter --name /rem/llm/anthropic-api-key --value "sk-ant-..." --type SecureString
aws ssm put-parameter --name /rem/llm/openai-api-key --value "sk-..." --type SecureString

# Phoenix secrets (required for observability)
aws ssm put-parameter --name /rem/phoenix/api-key --value "$(openssl rand -base64 32)" --type SecureString
aws ssm put-parameter --name /rem/phoenix/secret --value "$(openssl rand -base64 32)" --type SecureString
aws ssm put-parameter --name /rem/phoenix/admin-secret --value "$(openssl rand -base64 32)" --type SecureString

# Optional: OAuth credentials
aws ssm put-parameter --name /rem/auth/google-client-id --value "..." --type String
aws ssm put-parameter --name /rem/auth/google-client-secret --value "..." --type SecureString
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
