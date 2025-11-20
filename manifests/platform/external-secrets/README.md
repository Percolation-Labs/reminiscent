# Secrets Management - REM Stack

This document explains the complete secrets management strategy for the REM stack, including CloudNativePG auto-generated secrets, External Secrets Operator, and AWS Parameter Store.

## Table of Contents

1. [Secrets Flow Overview](#secrets-flow-overview)
2. [CloudNativePG Auto-Generated Secrets](#cloudnativepg-auto-generated-secrets)
3. [External Secrets Operator](#external-secrets-operator)
4. [AWS Parameter Store](#aws-parameter-store)
5. [Usage Patterns](#usage-patterns)

---

## Secrets Flow Overview

The REM stack uses three complementary secrets management approaches:

```
┌─────────────────────────────────────────────────────────┐
│ 1. CloudNativePG (Database Credentials)                │
│    PostgreSQL Cluster → Auto-creates K8s Secret         │
│    rem-postgres → rem-postgres-app (username/password)  │
└─────────────────────────────────────────────────────────┘
                        ↓
              Two consumption patterns:
                        ↓
        ┌───────────────┴───────────────┐
        ↓                               ↓
┌───────────────────┐         ┌─────────────────────────┐
│ Direct Reference  │         │ ESO Kubernetes Provider │
│ (Applications)    │         │ (Dynamic sync)          │
│                   │         │ rem-postgres-app →      │
│ Pod env vars      │         │ phoenix-postgres-url    │
└───────────────────┘         └─────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ 2. External Secrets Operator (External Credentials)    │
│    AWS Parameter Store → K8s Secret                     │
│    /rem/llm/anthropic-api-key → rem-llm-api-keys       │
└─────────────────────────────────────────────────────────┘
```

---

## CloudNativePG Auto-Generated Secrets

### How It Works

When you create a CloudNativePG Cluster, it automatically creates Kubernetes secrets with database credentials:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: rem-postgres
  namespace: rem-api
spec:
  instances: 1
  bootstrap:
    initdb:
      database: remdb
      owner: remuser
```

**CloudNativePG automatically creates:**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rem-postgres-app
  namespace: rem-api
type: kubernetes.io/basic-auth
data:
  username: cmVtdXNlcg==        # base64: remuser
  password: <random-generated>  # base64: 32-char random password
  database: cmVtZGI=            # base64: remdb
  host: cmVtLXBvc3RncmVzLXJ3  # base64: rem-postgres-rw
  port: NTQzMg==                # base64: 5432
```

### Additional Secrets Created

CloudNativePG creates multiple secrets for different purposes:

- `rem-postgres-app` - Application user credentials (read-write) - **Use this for applications**
- `rem-postgres-superuser` - PostgreSQL superuser credentials (only created if `enableSuperuserAccess: true`)
- `rem-postgres-replication` - Replication user credentials (for streaming replication)
- `rem-postgres-ca` - Certificate Authority for TLS connections
- `rem-postgres-server` - Server TLS certificate

**Important Notes:**
- CloudNativePG creates these secrets automatically when the Cluster resource is applied
- No manual secret creation is needed - just reference `rem-postgres-app` in your deployments
- The secrets are created in the same namespace as the Cluster resource
- If the operator is deployed via ArgoCD, the secrets are managed by the CloudNativePG operator, not ArgoCD

**Service Endpoints Created:**

- `rem-postgres-rw` - Read-write service (primary)
- `rem-postgres-r` - Read-only service (replicas)
- `rem-postgres-ro` - Read-only service (all instances)

### Using CloudNativePG Secrets in Applications

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rem-api
spec:
  template:
    spec:
      containers:
      - name: api
        env:
          # Database host
          - name: POSTGRES__HOST
            value: rem-postgres-rw.rem-api.svc.cluster.local

          # Database port
          - name: POSTGRES__PORT
            value: "5432"

          # Database name
          - name: POSTGRES__DATABASE
            valueFrom:
              secretKeyRef:
                name: rem-postgres-app
                key: database

          # Database user
          - name: POSTGRES__USER
            valueFrom:
              secretKeyRef:
                name: rem-postgres-app
                key: username

          # Database password
          - name: POSTGRES__PASSWORD
            valueFrom:
              secretKeyRef:
                name: rem-postgres-app
                key: password
```

**Python application reads via nested Pydantic settings:**

```python
from pydantic_settings import BaseSettings

class PostgresSettings(BaseSettings):
    host: str = "localhost"
    port: int = 5432
    database: str = "rem"
    user: str = "rem"
    password: str

    class Config:
        env_prefix = "POSTGRES__"  # Reads POSTGRES__HOST, POSTGRES__PORT, etc.
```

---

## External Secrets Operator

### Purpose

External Secrets Operator syncs secrets FROM external sources INTO Kubernetes secrets.

**Supported providers:**
- **AWS Parameter Store** - For external API keys (LLM providers, OAuth, etc.)
- **Kubernetes Secrets** - For syncing between namespaces or transforming existing secrets
- AWS Secrets Manager, HashiCorp Vault, Google Secret Manager, Azure Key Vault, etc.

**Use cases:**
- LLM API keys (Anthropic, OpenAI, Cerebras)
- Phoenix database URL construction (from CloudNativePG secret)
- OAuth client secrets
- Third-party service credentials

### Setup

#### 1. ClusterSecretStore (Infrastructure Setup)

We have two ClusterSecretStores configured:

##### a) AWS Parameter Store (for external API keys)

```yaml
# manifests/platform/external-secrets/cluster-secret-store.yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: aws-parameter-store
spec:
  provider:
    aws:
      service: ParameterStore
      region: us-east-1
      # Uses Pod Identity (EKS modern auth) - no explicit auth config needed
```

This uses **EKS Pod Identity** to authenticate to AWS without credentials.

##### b) Kubernetes Secrets (for cross-namespace sync and transformations)

```yaml
# manifests/platform/external-secrets/kubernetes-cluster-secret-store.yaml
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: kubernetes-secrets
spec:
  provider:
    kubernetes:
      remoteNamespace: rem-api  # Default namespace, can be overridden per ExternalSecret
      server:
        url: "https://kubernetes.default"
        caProvider:
          type: ConfigMap
          name: kube-root-ca.crt
          key: ca.crt
          namespace: kube-system
      auth:
        serviceAccount:
          name: external-secrets
          namespace: external-secrets-system
```

This allows ESO to read Kubernetes secrets and transform them (e.g., combining username/password into a connection URL).

**Required IAM permissions:**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:GetParametersByPath"
    ],
    "Resource": "arn:aws:ssm:us-east-1:*:parameter/rem/*"
  }]
}
```

#### 2. ExternalSecret (Per-Application)

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: rem-llm-api-keys
  namespace: rem-api
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-parameter-store
    kind: ClusterSecretStore
  target:
    name: rem-llm-api-keys  # K8s secret name to create
    creationPolicy: Owner
  data:
  - secretKey: anthropic-api-key  # Key in K8s secret
    remoteRef:
      key: /rem/llm/anthropic-api-key  # Parameter Store path
  - secretKey: openai-api-key
    remoteRef:
      key: /rem/llm/openai-api-key
```

**What happens:**
1. External Secrets Operator reads `/rem/llm/anthropic-api-key` from AWS Parameter Store
2. Creates/updates Kubernetes Secret `rem-llm-api-keys` in `rem-api` namespace
3. Refreshes every 1 hour to pick up changes

#### 3. Application Uses the Synced Secret

```yaml
env:
  - name: LLM__ANTHROPIC_API_KEY
    valueFrom:
      secretKeyRef:
        name: rem-llm-api-keys  # Secret created by ExternalSecret
        key: anthropic-api-key
```

---

## AWS Parameter Store

### Parameter Naming Convention

All REM parameters follow the pattern: `/rem/<component>/<key-name>`

### Current Parameters

#### Phoenix API Key

**Path:** `/rem/phoenix/api-key`
**Type:** SecureString
**Description:** Arize Phoenix API key for OTEL collector integration
**Status:** ⚠️ Requires generation from Phoenix UI or API
**Usage:** OTEL Collector forwards traces to Phoenix with this key in Authorization header

**Phoenix Deployment Secrets:**
- `PHOENIX_SECRET`: Strong authentication secret (auto-generated: `Xs6HMMCCqiSmi6SNxMA08LBzu4/0saKgedDeDIO1CVA=`)
- `PHOENIX_ADMIN_SECRET`: For programmatic API key generation (Phoenix 8.26+)

**Option 1: Generate API Key via Phoenix UI (Recommended for first setup)**

1. Port-forward to Phoenix:
   ```bash
   kubectl port-forward -n rem-api svc/phoenix 6006:6006
   ```

2. Open Phoenix UI: http://localhost:6006

3. Navigate to Settings → API Keys

4. Create a System API Key

5. Copy the key and add to Parameter Store:
   ```bash
   aws ssm put-parameter \
     --name /rem/phoenix/api-key \
     --value "phx_YOUR_GENERATED_API_KEY_HERE" \
     --type SecureString \
     --description "Arize Phoenix API key for OTEL collector" \
     --region us-east-1 \
     --overwrite
   ```

**Option 2: Generate API Key Programmatically (Phoenix 8.26+)**

Using the `PHOENIX_ADMIN_SECRET`, you can create API keys via API:

```bash
# Get Phoenix service endpoint
PHOENIX_URL="http://phoenix.rem-api.svc.cluster.local:6006"

# Create system API key (run from inside cluster or via port-forward)
curl -X POST "${PHOENIX_URL}/api/v1/api-keys" \
  -H "Authorization: Bearer ${PHOENIX_ADMIN_SECRET}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "otel-collector",
    "description": "System API key for OTEL collector",
    "expires_at": null
  }'

# The response will contain the API key - save it to Parameter Store
# Then REMOVE PHOENIX_ADMIN_SECRET from the deployment for security
```

**How it works:**
1. Parameter Store stores the API key at `/rem/phoenix/api-key`
2. ExternalSecret `rem-phoenix-api-key` syncs it to Kubernetes Secret with key `PHOENIX_API_KEY`
3. OTEL Collector pod loads the secret as environment variable
4. OTEL exports traces to Phoenix with header: `Authorization: Bearer ${PHOENIX_API_KEY}`

**ExternalSecret configuration:**
```yaml
# manifests/application/phoenix/external-secret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: rem-phoenix-api-key
spec:
  target:
    template:
      data:
        PHOENIX_API_KEY: "{{ .apikey }}"  # Maps to env var
  data:
    - secretKey: apikey
      remoteRef:
        key: /rem/phoenix/api-key
```

**OTEL Collector configuration:**
```yaml
# manifests/platform/otel-collector/otel-collector.yaml
spec:
  envFrom:
    - secretRef:
        name: rem-phoenix-api-key
  config:
    exporters:
      otlphttp/phoenix:
        endpoint: http://phoenix.rem-api.svc.cluster.local:6006/v1/traces
        headers:
          authorization: "Bearer ${PHOENIX_API_KEY}"
```

#### Phoenix PostgreSQL Connection

**Problem:** Phoenix requires a complete PostgreSQL URL (`postgresql://user:pass@host:port/db`), but CloudNativePG stores credentials as separate fields in a Kubernetes secret.

**Solution:** Use External Secrets Operator with Kubernetes provider and template transformation.

**How it works:**
1. CloudNativePG creates `rem-postgres-app` secret with fields: `username`, `password`, `dbname`
2. ExternalSecret reads from CloudNativePG secret via `kubernetes-secrets` ClusterSecretStore
3. ESO template engine constructs the full PostgreSQL URL
4. Creates `phoenix-postgres-url` secret with single field `PHOENIX_SQL_DATABASE_URL`
5. Phoenix deployment references the constructed URL
6. **Auto-rotation ready**: If CloudNativePG rotates the password, ESO syncs within 5 minutes

**ExternalSecret configuration:**
```yaml
# manifests/application/phoenix/postgres-external-secret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: phoenix-postgres-url
  namespace: rem-api
spec:
  refreshInterval: 5m  # Sync every 5 minutes to catch password rotations

  secretStoreRef:
    name: kubernetes-secrets  # Uses Kubernetes provider ClusterSecretStore
    kind: ClusterSecretStore

  target:
    name: phoenix-postgres-url
    creationPolicy: Owner
    template:
      engineVersion: v2
      data:
        # Template combines individual fields into connection URL
        PHOENIX_SQL_DATABASE_URL: "postgresql://{{ .username }}:{{ .password }}@rem-postgres-rw.rem-api.svc.cluster.local:5432/{{ .dbname }}"

  data:
    - secretKey: username
      remoteRef:
        key: rem-postgres-app  # CloudNativePG secret name
        property: username
    - secretKey: password
      remoteRef:
        key: rem-postgres-app
        property: password
    - secretKey: dbname
      remoteRef:
        key: rem-postgres-app
        property: dbname
```

**Phoenix deployment usage:**
```yaml
# manifests/application/phoenix/deployment.yaml
spec:
  template:
    spec:
      containers:
        - name: phoenix
          env:
            - name: PHOENIX_SQL_DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: phoenix-postgres-url  # ESO-created secret
                  key: PHOENIX_SQL_DATABASE_URL
```

**Benefits:**
- ✅ No hardcoded credentials in manifests or Parameter Store
- ✅ Automatic sync when CloudNativePG rotates passwords
- ✅ Phoenix gets properly formatted connection URL
- ✅ Single source of truth (CloudNativePG secret)
- ✅ 5-minute refresh interval catches changes quickly

**Password Rotation Handling:**

If CloudNativePG updates the `rem-postgres-app` secret (manual or automatic rotation):

1. External Secrets Operator detects change within 5 minutes (configurable via `refreshInterval`)
2. ESO updates `phoenix-postgres-url` secret with new password
3. Phoenix pod needs restart to pick up new credentials:
   ```bash
   kubectl rollout restart deployment phoenix -n rem-api
   ```

For zero-downtime rotation, consider:
- Using a sidecar container that watches for secret changes and reloads the app
- Implementing graceful connection handling with automatic reconnection in Phoenix
- Using Kubernetes Reloader operator to auto-restart pods on secret changes

#### LLM API Keys

**Anthropic Claude:**
```bash
aws ssm put-parameter \
  --name /rem/llm/anthropic-api-key \
  --value "sk-ant-..." \
  --type SecureString \
  --description "Anthropic Claude API key for REM agents" \
  --region us-east-1 \
  --overwrite
```

**OpenAI:**
```bash
aws ssm put-parameter \
  --name /rem/llm/openai-api-key \
  --value "sk-..." \
  --type SecureString \
  --description "OpenAI API key for REM agents" \
  --region us-east-1 \
  --overwrite
```

**Cerebras:**
```bash
aws ssm put-parameter \
  --name /rem/llm/cerebras-api-key \
  --value "csk-..." \
  --type SecureString \
  --description "Cerebras API key for REM agents" \
  --region us-east-1 \
  --overwrite
```

#### How to Update API Keys

To replace placeholder values with real API keys:

1. **Get your API keys:**
   - **Anthropic**: https://console.anthropic.com/ → API Keys
   - **OpenAI**: https://platform.openai.com/api-keys
   - **Cerebras**: https://cloud.cerebras.ai/ → API Keys

2. **Update Parameter Store** (use `--overwrite` to replace placeholders):
   ```bash
   # Anthropic Claude
   aws ssm put-parameter \
     --name /rem/llm/anthropic-api-key \
     --value "sk-ant-YOUR_ACTUAL_KEY_HERE" \
     --type SecureString \
     --region us-east-1 \
     --overwrite

   # OpenAI
   aws ssm put-parameter \
     --name /rem/llm/openai-api-key \
     --value "sk-YOUR_ACTUAL_KEY_HERE" \
     --type SecureString \
     --region us-east-1 \
     --overwrite

   # Cerebras
   aws ssm put-parameter \
     --name /rem/llm/cerebras-api-key \
     --value "csk-YOUR_ACTUAL_KEY_HERE" \
     --type SecureString \
     --region us-east-1 \
     --overwrite
   ```

3. **External Secrets will auto-sync** within the refresh interval (default 1 hour), or force immediate sync:
   ```bash
   # Delete and recreate the ExternalSecret to force immediate sync
   kubectl delete externalsecret rem-llm-api-keys -n rem-api
   kubectl apply -f manifests/application/rem-stack/components/api/external-secret.yaml

   # Verify the secret was updated
   kubectl get externalsecret rem-llm-api-keys -n rem-api
   kubectl describe secret rem-llm-api-keys -n rem-api
   ```

4. **Restart pods** to pick up the new secret values:
   ```bash
   kubectl rollout restart deployment rem-api -n rem-api
   ```

### Viewing Parameters

```bash
# List all REM parameters
aws ssm describe-parameters \
  --parameter-filters "Key=Name,Option=BeginsWith,Values=/rem/" \
  --region us-east-1

# Get a specific parameter value (decrypted)
aws ssm get-parameter \
  --name /rem/phoenix/api-key \
  --with-decryption \
  --region us-east-1 \
  --query 'Parameter.Value' \
  --output text
```

---

## Usage Patterns

### Pattern 1: Database Credentials (CloudNativePG)

**Best for:** Auto-managed PostgreSQL credentials

```yaml
# No manual secret creation needed!
# Just reference the CloudNativePG-created secret:
env:
  - name: DATABASE_URL
    value: "postgresql://$(POSTGRES__USER):$(POSTGRES__PASSWORD)@$(POSTGRES__HOST):$(POSTGRES__PORT)/$(POSTGRES__DATABASE)"
  - name: POSTGRES__USER
    valueFrom:
      secretKeyRef:
        name: rem-postgres-app
        key: username
  - name: POSTGRES__PASSWORD
    valueFrom:
      secretKeyRef:
        name: rem-postgres-app
        key: password
```

### Pattern 2: External API Keys (Parameter Store + External Secrets)

**Best for:** Third-party API credentials that change rarely

```yaml
# Step 1: Store in Parameter Store
$ aws ssm put-parameter --name /rem/llm/anthropic-api-key --value "sk-ant-..." --type SecureString

# Step 2: Create ExternalSecret to sync
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: rem-llm-api-keys
  namespace: rem-api
spec:
  secretStoreRef:
    name: aws-parameter-store
    kind: ClusterSecretStore
  data:
  - secretKey: anthropic-api-key
    remoteRef:
      key: /rem/llm/anthropic-api-key

# Step 3: Reference in deployment
env:
  - name: LLM__ANTHROPIC_API_KEY
    valueFrom:
      secretKeyRef:
        name: rem-llm-api-keys
        key: anthropic-api-key
```

### Pattern 3: Manual Kubernetes Secrets

**Best for:** Secrets that don't need external storage

```bash
kubectl create secret generic rem-jwt-secret \
  --from-literal=jwt-secret=$(openssl rand -base64 32) \
  -n rem-api
```

```yaml
env:
  - name: AUTH__JWT_SECRET
    valueFrom:
      secretKeyRef:
        name: rem-jwt-secret
        key: jwt-secret
```

### Pattern 4: Secret Transformation (ESO Kubernetes Provider + Templates)

**Best for:** Applications requiring specific secret formats that differ from source

**Problem:** Phoenix needs `postgresql://user:pass@host:port/db` but CloudNativePG stores separate fields.

**Solution:**
```yaml
# Step 1: CloudNativePG auto-creates rem-postgres-app with fields
# username, password, dbname

# Step 2: ExternalSecret reads from Kubernetes and transforms
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: phoenix-postgres-url
  namespace: rem-api
spec:
  refreshInterval: 5m
  secretStoreRef:
    name: kubernetes-secrets  # Kubernetes provider
    kind: ClusterSecretStore
  target:
    template:
      engineVersion: v2
      data:
        # Template transformation!
        PHOENIX_SQL_DATABASE_URL: "postgresql://{{ .username }}:{{ .password }}@rem-postgres-rw.rem-api.svc.cluster.local:5432/{{ .dbname }}"
  data:
    - secretKey: username
      remoteRef:
        key: rem-postgres-app
        property: username
    - secretKey: password
      remoteRef:
        key: rem-postgres-app
        property: password
    - secretKey: dbname
      remoteRef:
        key: rem-postgres-app
        property: dbname

# Step 3: Phoenix uses the transformed secret
env:
  - name: PHOENIX_SQL_DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: phoenix-postgres-url  # ESO-created transformed secret
        key: PHOENIX_SQL_DATABASE_URL
```

**Benefits:**
- Auto-syncs when source secret changes (password rotation support)
- No hardcoded credentials
- Format transformation handled declaratively
- Single source of truth maintained

---

## Security Best Practices

1. **Never commit secrets to Git** - Use `.gitignore` for local secret files
2. **Use SecureString for sensitive data** - KMS encryption at rest in Parameter Store
3. **Rotate credentials regularly** - External Secrets auto-syncs changes
4. **Principle of least privilege** - IRSA roles only access needed parameters
5. **Audit access** - CloudTrail logs all Parameter Store access
6. **Namespace isolation** - Secrets are namespace-scoped in Kubernetes

---

## Troubleshooting

### External Secret Not Syncing

```bash
# Check ExternalSecret status
kubectl describe externalsecret rem-llm-api-keys -n rem-api

# Check External Secrets Operator logs
kubectl logs -n external-secrets-system deployment/external-secrets

# Verify IRSA is configured
kubectl describe sa external-secrets -n external-secrets-system
# Should have annotation: eks.amazonaws.com/role-arn

# Test Parameter Store access from pod
kubectl run aws-cli --rm -it --image amazon/aws-cli --serviceaccount=external-secrets \
  -- ssm get-parameter --name /rem/phoenix/api-key --region us-east-1
```

### CloudNativePG Secret Not Found

```bash
# List all secrets created by CloudNativePG
kubectl get secrets -n rem-api | grep rem-postgres

# Check cluster status
kubectl describe cluster rem-postgres -n rem-api

# View cluster logs
kubectl logs -n rem-api rem-postgres-1
```

---

## Summary

| Secret Type | Source | K8s Secret | Use Case | Rotation Support |
|------------|--------|------------|----------|------------------|
| Database credentials | CloudNativePG auto-generated | `rem-postgres-app` | PostgreSQL connection (direct) | Manual/CloudNativePG managed |
| Phoenix DB URL | CloudNativePG → ESO (K8s provider) | `phoenix-postgres-url` | Phoenix PostgreSQL connection | ✅ Auto-syncs (5m refresh) |
| LLM API keys | Parameter Store → ESO | `rem-llm-api-keys` | Anthropic/OpenAI API | ✅ Auto-syncs (1h refresh) |
| Phoenix API key | Parameter Store → ESO | `rem-phoenix-api-key` | Arize Phoenix OTEL auth | ✅ Auto-syncs (1h refresh) |
| OAuth credentials | Parameter Store → ESO | `rem-oauth-creds` | Google/Microsoft auth | ✅ Auto-syncs (1h refresh) |
| Phoenix auth secrets | Manual K8s secret | `phoenix-secrets` | Phoenix authentication | Manual update |
| JWT secret | Manual K8s secret | `rem-jwt-secret` | Session signing | Manual rotation |

**Key Principles:**
- CloudNativePG manages database secrets automatically
- External Secrets Operator has **two modes**:
  1. **AWS Parameter Store provider** - Syncs external API keys into Kubernetes
  2. **Kubernetes provider** - Syncs/transforms between Kubernetes secrets (e.g., Phoenix DB URL)
- Applications only reference Kubernetes secrets (never external stores directly)
- ESO automatically refreshes secrets on schedule (enables rotation without manual intervention)
- Template transformation in ESO allows format conversion (e.g., fields → connection URL)
