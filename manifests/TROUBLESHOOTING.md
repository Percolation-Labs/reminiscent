# Deployment Troubleshooting Log

This document captures issues found during deployment and their fixes to ensure the stack is reproducible.

## Session: 2025-11-27 - siggy EKS Cluster Deployment

### Summary of Issues Found

The following issues were discovered when deploying to a fresh `siggy-application-cluster-a` EKS cluster. Each issue represents a gap in the manifests that should be fixed for reproducible deployments.

---

## Issue 1: Platform Operators Not Pre-Installed

**Error**: CRD not found when applying manifests
**Root Cause**: ESO and CNPG operators were not installed on the cluster

**Fix Applied**:
```bash
# Install External Secrets Operator
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets-system --create-namespace

# Install CloudNativePG
helm install cnpg cloudnative-pg/cloudnative-pg \
  -n cnpg-system --create-namespace
```

**Documentation Gap**: Platform README needed manual installation instructions since ArgoCD wasn't deploying them.

---

## Issue 2: ESO Installed in Wrong Namespace

**Error**: ExternalSecrets failing with "AccessDeniedException" from SSM
**Root Cause**: ESO was installed in `external-secrets` namespace but CDK Pod Identity expects `external-secrets-system`

**Fix Applied**:
- Reinstalled ESO in correct namespace `external-secrets-system`
- Updated platform README with correct namespace

---

## Issue 3: Missing ClusterSecretStore for Kubernetes Secrets

**Error**: `ClusterSecretStore "kubernetes-secrets" not found`
**Root Cause**: Phoenix external secret references a ClusterSecretStore for reading Kubernetes secrets (CNPG-generated), but it wasn't being applied.

**Fix Applied**:
- Created `manifests/platform/external-secrets/kubernetes-cluster-secret-store.yaml`
- Applied manually: `kubectl apply -f manifests/platform/external-secrets/kubernetes-cluster-secret-store.yaml`

**Gap**: This ClusterSecretStore should be part of the platform layer and applied automatically.

---

## Issue 4: PostgreSQL NodeSelector Preventing Scheduling

**Error**: Pod stuck in Pending with `label "workload-type" does not have known values`
**Root Cause**: Base postgres-cluster.yaml had `nodeSelector: workload-type=stateful` but Karpenter nodepool doesn't define this label.

**Fix Applied**:
- Removed nodeSelector and tolerations from base `postgres-cluster.yaml`
- These should be added in production overlay only when dedicated stateful nodes exist

**Files Changed**:
- `manifests/application/rem-stack/components/postgres/postgres-cluster.yaml` - removed nodeSelector/tolerations
- `manifests/application/rem-stack/overlays/staging/postgres-patch.yaml` - simplified affinity

---

## Issue 5: PostgreSQL Memory Request Below shared_buffers

**Error**: `Memory request is lower than PostgreSQL 'shared_buffers' value`
**Root Cause**: Staging patch had `memory: 1Gi` but base config has `shared_buffers: 2GB`

**Fix Applied**:
- Updated staging patch to `memory: 4Gi` (must be >= shared_buffers)

**Files Changed**:
- `manifests/application/rem-stack/overlays/staging/postgres-patch.yaml`

---

## Issue 6: Missing PostgreSQL Bootstrap Credentials Secret

**Error**: `secret "rem-database-credentials" not found`
**Root Cause**: CNPG cluster references `rem-database-credentials` for bootstrap, but no ExternalSecret was creating it.

**Fix Applied**:
1. Created SSM parameters:
   ```bash
   aws ssm put-parameter --name "/siggy/postgres/username" --value "remuser" --type String
   aws ssm put-parameter --name "/siggy/postgres/password" --value "$(openssl rand -base64 24)" --type SecureString
   ```

2. Created ExternalSecret:
   - `manifests/application/rem-stack/components/postgres/postgres-credentials-external-secret.yaml`

3. Added to kustomization.yaml

**Gap**: PostgreSQL bootstrap credentials should be documented as a required SSM parameter.

---

## Issue 7: Missing SSM Parameters

**Error**: ExternalSecrets failing with "ParameterNotFound"
**Root Cause**: Required SSM parameters weren't created before deployment

**Required SSM Parameters** (must exist before deployment):
```
/siggy/llm/anthropic-api-key    (SecureString)
/siggy/llm/openai-api-key       (SecureString)
/siggy/phoenix/api-key          (SecureString)
/siggy/postgres/username        (String)
/siggy/postgres/password        (SecureString)
```

---

## Issue 8: Phoenix Database Conflict with REM

**Error**: `DuplicateTable) relation "users" already exists`
**Root Cause**: Phoenix and REM both have a `users` table. When sharing `remdb`, whichever app runs migrations first creates the table, and the second fails.

**Fix Applied**:
1. Phoenix needs its own isolated database `phoenixdb`
2. Updated `phoenix/postgres-external-secret.yaml` to use `phoenixdb` instead of `remdb`
3. Added inline `postInitSQL` to postgres-cluster.yaml to create phoenixdb during CNPG bootstrap

**Files Changed**:
- `manifests/application/rem-stack/components/postgres/postgres-cluster.yaml` - Added postInitSQL for phoenixdb
- `manifests/application/phoenix/postgres-external-secret.yaml` - Changed to use phoenixdb

**Manual Fix** (for existing clusters without phoenixdb):
```bash
# Connect to postgres and create phoenixdb
kubectl exec rem-postgres-1 -n siggy -- psql -U postgres -c "CREATE DATABASE phoenixdb OWNER remuser;"
# Restart Phoenix to pick up new config
kubectl rollout restart deployment/phoenix -n siggy
```

**Why This Happens**: Phoenix is an observability platform (OTEL collector) that has its own user management for access control. Its `users` table conflicts with REM's `users` table for application users.

---

## Checklist for Clean Deployment

Before running `kubectl apply -k manifests/application/rem-stack/overlays/staging`:

### 1. Infrastructure (CDK)
- [ ] EKS cluster deployed with Pod Identity enabled
- [ ] S3 bucket created
- [ ] SQS queue created
- [ ] Pod Identity associations created for: `external-secrets`, `rem-app`

### 2. Platform Layer
- [ ] External Secrets Operator installed in `external-secrets-system` namespace
- [ ] CloudNativePG operator installed in `cnpg-system` namespace
- [ ] ClusterSecretStore `aws-parameter-store` applied
- [ ] ClusterSecretStore `kubernetes-secrets` applied

### 3. SSM Parameters
- [ ] `/siggy/llm/anthropic-api-key` created (SecureString)
- [ ] `/siggy/llm/openai-api-key` created (SecureString)
- [ ] `/siggy/phoenix/api-key` created (SecureString)
- [ ] `/siggy/phoenix/secret` created (SecureString) - for session signing
- [ ] `/siggy/phoenix/admin-secret` created (SecureString) - for admin API access
- [ ] `/siggy/postgres/username` created (String, value: `remuser`)
- [ ] `/siggy/postgres/password` created (SecureString, random value)

### 4. Application Manifests
```bash
kubectl apply -k manifests/application/rem-stack/overlays/staging
```

---

## Files Modified in This Session

| File | Change |
|------|--------|
| `manifests/platform/README.md` | Updated with manual install instructions, Pod Identity docs |
| `manifests/application/rem-stack/components/postgres/postgres-cluster.yaml` | Removed nodeSelector/tolerations |
| `manifests/application/rem-stack/components/postgres/kustomization.yaml` | Added postgres-credentials-external-secret.yaml |
| `manifests/application/rem-stack/components/postgres/postgres-credentials-external-secret.yaml` | **NEW** - PostgreSQL bootstrap credentials |
| `manifests/application/rem-stack/overlays/staging/postgres-patch.yaml` | Fixed memory to 4Gi, simplified affinity |
| `manifests/application/rem-stack/components/worker/deployment.yaml` | Changed to use rem-app service account |
| `manifests/application/rem-stack/components/worker/kustomization.yaml` | Re-enabled KEDA resources |
| `manifests/application/rem-stack/components/worker/triggerauthentication.yaml` | Changed identityOwner to workload |
| `manifests/application/rem-stack/components/worker/keda-scaledobject.yaml` | Updated SQS queue URL |
| `manifests/application/phoenix/postgres-external-secret.yaml` | Changed to use phoenixdb |
| `manifests/application/phoenix/phoenix-secrets-external.yaml` | **NEW** - Phoenix auth secrets from SSM |
| `manifests/application/phoenix/kustomization.yaml` | Added phoenix-secrets-external.yaml |
| `manifests/application/rem-stack/components/api/kustomization.yaml` | Removed obsolete secretstore.yaml |
