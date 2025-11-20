# Platform Layer

Platform components deployed via ArgoCD using OCI Helm charts.

## Components

### ArgoCD Applications (`argocd/applications/`)

All platform components are deployed as ArgoCD Applications using the OCI repository pattern:

1. **cert-manager**: Certificate management
2. **external-secrets-operator**: Secret management from AWS Parameter Store
3. **cloudnative-pg**: PostgreSQL operator for database clusters
4. **opentelemetry-operator**: OTEL instrumentation and collection
5. **aws-load-balancer-controller**: ALB/NLB provisioning
6. **arize-phoenix**: LLM observability platform

## Deployment

### Prerequisites

1. **Infrastructure deployed** - see [../infra/eks-yaml/README.md](../infra/eks-yaml/README.md)
2. **kubeconfig** configured: `export KUBECONFIG=~/.kube/rem-cluster-config`
3. **Secrets** in AWS Parameter Store (see Configuration section below)

### Install ArgoCD

```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ready
kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd

# Get admin password (optional - for UI access)
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d
```

### Deploy Platform Components

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
2. **external-secrets-operator** (required by applications)
3. **cloudnative-pg** (required by applications with databases)
4. **opentelemetry-operator** (required by instrumented applications)
5. **aws-load-balancer-controller** (required for ingress)
6. **arize-phoenix** (required by OTEL collectors)

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

Before deploying, populate required secrets:

```bash
# LLM API keys
aws ssm put-parameter --name /rem/llm/anthropic-api-key --value "sk-ant-..." --type SecureString
aws ssm put-parameter --name /rem/llm/openai-api-key --value "sk-..." --type SecureString

# Optional: OAuth credentials
aws ssm put-parameter --name /rem/auth/google-client-id --value "..." --type String
aws ssm put-parameter --name /rem/auth/google-client-secret --value "..." --type SecureString
```

### IRSA Roles

Platform components use IRSA roles created by Pulumi:
- **external-secrets**: Access to Parameter Store
- **cloudnative-pg**: S3 backups
- **aws-load-balancer-controller**: ALB/NLB management
- **otel-collector**: CloudWatch/X-Ray export

Get role ARNs: `cd manifests/infra/eks-yaml && pulumi stack output`

## Verification

```bash
# Check all applications
kubectl get applications -n argocd

# Check platform pods
kubectl get pods -n cert-manager
kubectl get pods -n external-secrets
kubectl get pods -n cnpg-system
kubectl get pods -n opentelemetry-operator-system

# Check External Secrets syncing
kubectl get externalsecrets -A
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
# Check SecretStore
kubectl describe secretstore -n <namespace>

# Check operator logs
kubectl logs -n external-secrets deployment/external-secrets

# Verify IRSA
kubectl describe sa external-secrets -n external-secrets
# Should have: eks.amazonaws.com/role-arn annotation
```

### CloudNativePG Issues

```bash
# Check operator
kubectl logs -n cnpg-system deployment/cnpg-controller-manager

# Check cluster
kubectl describe cluster <name> -n <namespace>
```
