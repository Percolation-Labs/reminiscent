# REM Stack Deployment Guide

This document provides a comprehensive deployment checklist and troubleshooting guide for deploying REM to Kubernetes.

## Quick Start

```bash
# 1. Install remdb and initialize (auto-downloads manifests)
pip install remdb
rem cluster init --project-name myproject -y

# Or specify a specific manifest version (manifests are versioned separately)
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

**Note:** The `--manifest-version` flag downloads manifests from GitHub releases. Use `latest` (default) or a specific version tag like `v0.5.0`. This is independent of the installed `remdb` package version.

---

## Deployment Checklist

### Phase 1: Infrastructure (CDK)

Before applying Kubernetes manifests, CDK must have created:

- [ ] **EKS Cluster** with Pod Identity enabled
- [ ] **S3 Buckets**
  - `{project}-io-{env}` - Application files
  - `{project}-io-pg-backups-{env}` - PostgreSQL backups
- [ ] **SQS Queues**
  - `{cluster}-file-processing-{env}` - File processing
  - `{cluster}-karpenter-interruption` - Spot interruptions
- [ ] **Pod Identity Associations** (critical for AWS access)
  - `rem-app` in `{namespace}` - S3, SQS, SSM access
  - `external-secrets` in `external-secrets-system` - SSM/Secrets Manager
  - `keda-operator` in `keda` - SQS (for autoscaling)
  - `{project}-postgres` in `{namespace}` - S3 backups
  - `otel-collector` in `observability` - X-Ray, CloudWatch

Verify Pod Identity associations:
```bash
aws eks list-pod-identity-associations --cluster-name your-cluster --region us-east-1
```

### Phase 2: SSM Parameters

Create these parameters BEFORE deploying (use `rem cluster setup-ssm`):

```bash
# Required
/rem/postgres/username        # String: "remuser"
/rem/postgres/password        # SecureString: random

# LLM API Keys
/rem/llm/anthropic-api-key    # SecureString: your key
/rem/llm/openai-api-key       # SecureString: your key

# Optional (Phoenix observability)
/rem/phoenix/api-key          # SecureString: random
/rem/phoenix/secret           # SecureString: random
```

### Phase 3: Platform Operators

Install operators via ArgoCD or manually:

```bash
# Option A: ArgoCD (recommended)
kubectl apply -f manifests/platform/argocd/applications/external-secrets-operator.yaml
kubectl apply -f manifests/platform/argocd/applications/cloudnative-pg.yaml
kubectl apply -f manifests/platform/argocd/applications/keda.yaml

# Option B: Manual Helm
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets-system --create-namespace

helm install cnpg cloudnative-pg/cloudnative-pg \
  -n cnpg-system --create-namespace

helm install keda kedacore/keda \
  -n keda --create-namespace
```

### Phase 4: ClusterSecretStores

Apply secret stores for External Secrets Operator:

```bash
kubectl apply -f manifests/platform/external-secrets/cluster-secret-store.yaml
kubectl apply -f manifests/platform/external-secrets/kubernetes-cluster-secret-store.yaml
```

Verify:
```bash
kubectl get clustersecretstore
# Should show: aws-parameter-store, kubernetes-secrets
```

### Phase 5: SQL ConfigMap

Generate and apply the PostgreSQL init ConfigMap:

```bash
rem cluster generate-sql-configmap --apply

# Or manually:
kubectl apply -f manifests/application/rem-stack/components/postgres/postgres-init-configmap.yaml
```

### Phase 6: Deploy Application

```bash
# Via ArgoCD
kubectl apply -f manifests/application/rem-stack/argocd-staging.yaml

# Or via kubectl directly
kubectl apply -k manifests/application/rem-stack/overlays/staging
```

---

## Common Issues & Fixes

### Issue 1: ExternalSecret AccessDeniedException

**Error**: `AccessDeniedException: User... is not authorized to perform: ssm:GetParameter`

**Cause**: Pod Identity not configured or namespace mismatch.

**Fix**:
1. Verify ESO is in `external-secrets-system` namespace (not `external-secrets`)
2. Check CDK Pod Identity association exists:
   ```bash
   aws eks list-pod-identity-associations --cluster-name your-cluster | grep external-secrets
   ```
3. Restart ESO pods after fixing:
   ```bash
   kubectl rollout restart deployment -n external-secrets-system
   ```

### Issue 2: CNPG Cluster Stuck Pending

**Error**: Pod stuck with "label does not have known values"

**Cause**: nodeSelector references labels that don't exist (e.g., `workload-type: stateful`).

**Fix**: Remove nodeSelector from base postgres-cluster.yaml or ensure Karpenter NodePool defines the labels.

### Issue 3: KEDA ScaledObject Not Scaling

**Error**: ScaledObject shows "error getting queue attributes"

**Causes**:
1. KEDA operator doesn't have SQS permissions (missing Pod Identity)
2. TriggerAuthentication misconfigured

**Fix**:
1. Verify KEDA Pod Identity:
   ```bash
   aws eks list-pod-identity-associations --cluster-name your-cluster | grep keda
   ```
2. If using `identityOwner: keda`, KEDA operator needs SQS access
3. If using `identityOwner: workload`, the workload SA needs SQS access

### Issue 4: Phoenix "users" Table Conflict

**Error**: `DuplicateTable: relation "users" already exists`

**Cause**: Phoenix and REM both have `users` tables. Sharing `remdb` causes conflicts.

**Fix**: Phoenix uses separate `phoenixdb`:
1. postgres-cluster.yaml creates `phoenixdb` via `postInitSQL`
2. Phoenix external-secret uses `phoenixdb` in connection string

For existing clusters:
```bash
kubectl exec rem-postgres-1 -n rem -- psql -U postgres -c "CREATE DATABASE phoenixdb OWNER remuser;"
kubectl rollout restart deployment/phoenix -n rem
```

### Issue 5: ArgoCD OutOfSync Loop

**Error**: Application constantly syncing, never healthy

**Cause**: Operators add default fields that don't match git manifests.

**Fix**: Add `ignoreDifferences` and `RespectIgnoreDifferences=true`:
```yaml
ignoreDifferences:
  - group: external-secrets.io
    kind: ExternalSecret
    jqPathExpressions:
      - .spec.data[].remoteRef.conversionStrategy
      - .spec.target.deletionPolicy
  - group: postgresql.cnpg.io
    kind: Cluster
    jsonPointers:
      - /spec
syncOptions:
  - RespectIgnoreDifferences=true  # CRITICAL
```

### Issue 6: ESO Chart 403 Forbidden

**Error**: `failed to pull chart: 403 Forbidden`

**Cause**: Using OCI registry that requires auth or doesn't exist.

**Fix**: Use HTTPS chart repository:
```yaml
source:
  repoURL: https://charts.external-secrets.io  # NOT oci://ghcr.io/...
  chart: external-secrets
  targetRevision: "0.20.4"
```

### Issue 7: CNPG PodMonitor Error

**Error**: `no matches for kind "PodMonitor"`

**Cause**: Prometheus Operator CRD not installed but `podMonitorEnabled: true`.

**Fix**: Disable PodMonitor in cloudnative-pg.yaml:
```yaml
monitoring:
  podMonitorEnabled: false
```

### Issue 8: External Secrets Webhook Service Name Mismatch

**Error**: `failed calling webhook "validate.externalsecret.external-secrets.io": service "external-secrets-webhook" not found`

**Cause**: The ValidatingWebhookConfiguration points to `external-secrets-webhook` but the actual service is named `external-secrets-operator-webhook`.

**Diagnosis**:
```bash
# Check what service the webhook expects
kubectl get validatingwebhookconfiguration externalsecret-validate \
  -o jsonpath='{.webhooks[0].clientConfig.service.name}'
# Returns: external-secrets-webhook

# Check actual service name
kubectl get svc -n external-secrets-system | grep webhook
# Returns: external-secrets-operator-webhook
```

**Fix**:
```bash
kubectl patch validatingwebhookconfiguration externalsecret-validate \
  --type='json' \
  -p='[{"op": "replace", "path": "/webhooks/0/clientConfig/service/name", "value": "external-secrets-operator-webhook"}]'
```

### Issue 9: AWS Load Balancer Controller Webhook TLS Certificate Mismatch

**Error**: `failed calling webhook "vingress.elbv2.k8s.aws": tls: failed to verify certificate: x509: certificate signed by unknown authority`

**Cause**: The webhook's `caBundle` doesn't match the TLS secret used by the controller. This can happen after certificate rotation or controller restarts.

**Diagnosis**:
```bash
# Compare certificate dates
# Webhook caBundle:
kubectl get validatingwebhookconfiguration aws-load-balancer-webhook \
  -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d | \
  openssl x509 -noout -dates

# TLS Secret:
kubectl get secret aws-load-balancer-tls -n kube-system \
  -o jsonpath='{.data.ca\.crt}' | base64 -d | \
  openssl x509 -noout -dates
```

**Fix**:
```bash
# Get new CA from secret
NEW_CA=$(kubectl get secret aws-load-balancer-tls -n kube-system -o jsonpath='{.data.ca\.crt}')

# Update validating webhook
kubectl patch validatingwebhookconfiguration aws-load-balancer-webhook \
  --type='json' \
  -p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\": \"$NEW_CA\"},
      {\"op\": \"replace\", \"path\": \"/webhooks/1/clientConfig/caBundle\", \"value\": \"$NEW_CA\"},
      {\"op\": \"replace\", \"path\": \"/webhooks/2/clientConfig/caBundle\", \"value\": \"$NEW_CA\"}]"

# Update mutating webhook
kubectl patch mutatingwebhookconfiguration aws-load-balancer-webhook \
  --type='json' \
  -p="[{\"op\": \"replace\", \"path\": \"/webhooks/0/clientConfig/caBundle\", \"value\": \"$NEW_CA\"},
      {\"op\": \"replace\", \"path\": \"/webhooks/1/clientConfig/caBundle\", \"value\": \"$NEW_CA\"},
      {\"op\": \"replace\", \"path\": \"/webhooks/2/clientConfig/caBundle\", \"value\": \"$NEW_CA\"}]"
```

**Prevention**: If the controller manages its own certs, ensure cert-manager or the controller's built-in cert rotation updates both the secret AND the webhook configurations.

### Issue 10: ArgoCD Repo Server Cache Not Refreshing

**Error**: ArgoCD shows `Synced` or `OutOfSync` but the revision doesn't match the latest commit on `main`.

**Cause**: ArgoCD repo-server caches git data and manifests. A stale cache can cause sync to use old manifests even when new commits exist.

**Diagnosis**:
```bash
# Check ArgoCD's synced revision
kubectl get app <app-name> -n argocd -o jsonpath='{.status.sync.revision}'

# Compare with actual remote HEAD
git ls-remote origin main

# Check repo-server logs for cache hits
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-repo-server | grep "cache hit"
```

**Fix**:
```bash
# Option 1: Hard refresh the application
kubectl annotate application <app-name> -n argocd \
  argocd.argoproj.io/refresh=hard --overwrite

# Option 2: Restart repo-server to clear all caches
kubectl rollout restart deployment argocd-repo-server -n argocd

# Wait for it to come back up, then refresh
sleep 30
kubectl annotate application <app-name> -n argocd \
  argocd.argoproj.io/refresh=hard --overwrite
```

**Prevention**: Configure GitHub webhook to notify ArgoCD of pushes for immediate refresh instead of relying on polling.

---

## Pod Identity Quick Reference

| Service Account | Namespace | Purpose |
|-----------------|-----------|---------|
| `external-secrets` | `external-secrets-system` | SSM/Secrets Manager access |
| `keda-operator` | `keda` | SQS GetQueueAttributes |
| `rem-app` | `rem` | S3, SQS, SSM for application |
| `rem-postgres` | `rem` | S3 for CNPG backups |
| `otel-collector` | `observability` | X-Ray, CloudWatch |
| `aws-load-balancer-controller` | `kube-system` | ALB provisioning |
| `karpenter` | `karpenter` | EC2/Spot instance management |

---

## Validation Commands

```bash
# Check Pod Identity associations
aws eks list-pod-identity-associations --cluster-name your-cluster --region us-east-1

# Check ExternalSecrets status
kubectl get externalsecrets -A
kubectl describe externalsecret <name> -n <ns>

# Check CNPG cluster health
kubectl get clusters.postgresql.cnpg.io -n rem
kubectl cnpg status rem-postgres -n rem

# Check KEDA ScaledObjects
kubectl get scaledobject -A
kubectl describe scaledobject file-processor-scaler -n rem

# Check ArgoCD sync status
argocd app list
argocd app get rem-stack-staging

# Verify secret was created
kubectl get secrets -n rem
kubectl get secret rem-api-secrets -n rem -o yaml
```

---

## Files Modified by Deployment

| File | Purpose |
|------|---------|
| `manifests/cluster-config.yaml` | Deployment configuration |
| `manifests/platform/external-secrets/*.yaml` | ClusterSecretStores |
| `manifests/platform/argocd/applications/*.yaml` | Platform operator apps |
| `manifests/application/rem-stack/argocd-staging.yaml` | Main ArgoCD application |
| `manifests/application/rem-stack/components/postgres/*.yaml` | PostgreSQL cluster config |
| `manifests/application/rem-stack/components/worker/*.yaml` | KEDA scaling config |

---

## Related Documentation

- [REM README](../rem/README.md) - Full package documentation
- [CDK Infrastructure](infra/cdk-eks/README.md) - AWS infrastructure
- [Platform README](platform/README.md) - Platform operators
- [Application README](application/README.md) - Application deployment

---

## Session Notes

### 2025-11-29: ArgoCD Setup for Private Repo

**Context**: Setting up ArgoCD to deploy rem-stack from private GitHub repo `Percolation-Labs/reminiscent`.

**Issues Encountered**:

1. **Manifest placeholder URLs not updated**
   - Multiple files had `${GIT_REPO_URL}`, `YOUR_ORG/remstack.git`, or `anthropics/remstack.git` as placeholders
   - Files updated:
     - `manifests/platform/argocd/app-of-apps.yaml`
     - `manifests/application/rem-stack/argocd-staging.yaml`
     - `manifests/application/rem-stack/argocd-prod.yaml`
     - `manifests/platform/argocd/applications/cluster-secret-stores.yaml`
     - `manifests/platform/argocd/applications/otel-collector.yaml`
     - `manifests/platform/argocd/applications/arize-phoenix.yaml`
     - `manifests/application/rem-stack/components/api/argocd-application.yaml`

2. **CI workflow missing working directory**
   - `pyproject.toml` is in `rem/` subdirectory
   - CI workflow ran commands from repo root, causing path errors
   - **Fix**: Added `defaults: run: working-directory: rem` to all jobs in `.github/workflows/ci.yaml`

3. **ArgoCD private repo access**
   - Repo is private, requires credentials
   - **Fix**: Created repository secret in ArgoCD namespace:
     ```bash
     kubectl create secret generic repo-reminiscent \
       --namespace argocd \
       --from-literal=url=https://github.com/Percolation-Labs/reminiscent.git \
       --from-literal=username=<github-user> \
       --from-literal=password=<github-pat> \
       --from-literal=type=git
     kubectl label secret repo-reminiscent -n argocd argocd.argoproj.io/secret-type=repository
     ```

4. **SSM Parameter username mismatch**
   - Created `/rem/postgres/username` with value `rem`
   - CNPG cluster spec defines `owner: remuser`
   - **Fix**: Update parameter to `remuser`:
     ```bash
     aws ssm put-parameter --name /rem/postgres/username --value "remuser" --type String --overwrite
     ```

5. **Missing SSM parameters**
   - External secrets failed with `SecretSyncedError`
   - Required parameters not in AWS Parameter Store
   - **Fix**: Create all required parameters:
     ```bash
     # Database
     aws ssm put-parameter --name /rem/postgres/username --value "remuser" --type String
     aws ssm put-parameter --name /rem/postgres/password --value "$(openssl rand -base64 24)" --type SecureString

     # LLM API Keys
     aws ssm put-parameter --name /rem/llm/anthropic-api-key --value "<key>" --type SecureString
     aws ssm put-parameter --name /rem/llm/openai-api-key --value "<key>" --type SecureString

     # Auth
     aws ssm put-parameter --name /rem/auth/session-secret --value "$(openssl rand -base64 32)" --type SecureString
     aws ssm put-parameter --name /rem/auth/google-client-id --value "placeholder" --type String
     aws ssm put-parameter --name /rem/auth/google-client-secret --value "placeholder" --type SecureString

     # Phoenix
     aws ssm put-parameter --name /rem/phoenix/api-key --value "$(openssl rand -base64 32)" --type SecureString
     aws ssm put-parameter --name /rem/phoenix/secret --value "$(openssl rand -base64 32)" --type SecureString
     aws ssm put-parameter --name /rem/phoenix/admin-secret --value "$(openssl rand -base64 32)" --type SecureString
     ```

6. **Force refresh external secrets after parameter changes**
   ```bash
   for es in $(kubectl get externalsecrets -n rem -o name); do
     kubectl annotate $es -n rem force-sync=$(date +%s) --overwrite
   done
   ```

**Result**: ArgoCD successfully syncing from private repo. rem-api running. Phoenix has separate database migration issue (not ArgoCD-related).
