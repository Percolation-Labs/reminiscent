# UNLOGGED Table Restorer

Automatically rebuilds PostgreSQL UNLOGGED tables (`kv_store`, `rate_limits`) after pod restarts or failovers.

## Problem

PostgreSQL UNLOGGED tables provide high-performance caching but:
- Are **NOT** written to WAL (Write-Ahead Log)
- Are **NOT** replicated to standby servers
- Are **truncated** on crash/restart

In a CloudNativePG (CNPG) multi-replica setup:
- Primary has data in UNLOGGED tables
- Replicas have **empty** UNLOGGED tables (by design)
- On failover, new primary has **empty** UNLOGGED tables

This breaks REM's `LOOKUP`, `FUZZY`, and `TRAVERSE` queries which rely on `kv_store`.

## Solution

Two-layer detection and recovery:

### 1. Event-Driven (Argo Events)
Watches CNPG Cluster custom resource for status changes:
- `status.currentPrimary` changes → failover occurred
- `status.phase` transitions → cluster recovering

Triggers a Job that runs `--check-and-restore`.

### 2. Periodic (CronJob)
Every 5 minutes, checks if rebuild is needed:
- If `kv_store` is empty but entity tables have data → rebuild
- Uses advisory locks to prevent concurrent rebuilds
- Idempotent - safe to run frequently

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Event-Driven Layer                        │
│                                                              │
│  ┌──────────────────┐    ┌──────────────────┐               │
│  │  EventSource     │───▶│  Sensor          │               │
│  │  (watch CNPG CR) │    │  (filter+trigger)│               │
│  └──────────────────┘    └────────┬─────────┘               │
│                                   │                          │
│                                   ▼                          │
│                          ┌──────────────────┐               │
│                          │  Job             │               │
│                          │  --check-restore │               │
│                          └──────────────────┘               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    Periodic Layer (Backup)                   │
│                                                              │
│  ┌──────────────────┐                                       │
│  │  CronJob         │  Every 5 minutes                      │
│  │  --check-restore │  (belt & suspenders)                  │
│  └──────────────────┘                                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    Detection Logic                           │
│                                                              │
│  1. Check if connected to primary (replicas can't access)   │
│  2. Check kv_store count                                    │
│  3. If kv_store=0 AND any entity table has data:           │
│     → REBUILD NEEDED                                        │
│  4. Acquire advisory lock (prevent concurrent rebuilds)     │
│  5. Call rebuild_kv_store() PostgreSQL function            │
│  6. Push watermark to S3 (observability)                   │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

### Argo Events (Optional but Recommended)
```bash
# Install Argo Events
kubectl create namespace argo-events
kubectl apply -n argo-events -f https://raw.githubusercontent.com/argoproj/argo-events/stable/manifests/install.yaml

# Install EventBus (required for event routing)
kubectl apply -n argo-events -f https://raw.githubusercontent.com/argoproj/argo-events/stable/examples/eventbus/native.yaml
```

If Argo Events is not installed, comment out the argo-* resources in `kustomization.yaml`.
The CronJob will still provide periodic checks.

### Database Credentials
The `rem-database-credentials` secret must exist with a `uri` key containing the PostgreSQL connection string.

## Deployment

```bash
# Deploy with Kustomize
kubectl apply -k manifests/application/rem-stack/components/unlogged-restorer/

# Or add to your overlay's kustomization.yaml:
# components:
#   - ../components/unlogged-restorer
```

## Manual Operations

```bash
# Check if rebuild is needed
kubectl exec -it deployment/rem-api -- python -m rem.workers.unlogged_maintainer --check-and-restore

# Force rebuild
kubectl exec -it deployment/rem-api -- python -m rem.workers.unlogged_maintainer --restore

# Push watermark to S3
kubectl exec -it deployment/rem-api -- python -m rem.workers.unlogged_maintainer --snapshot
```

## Monitoring

### S3 Watermark
After each rebuild, a watermark is pushed to S3:
```
s3://{bucket}/state/unlogged-watermark.json
```

Contents:
```json
{
  "snapshot_ts": "2025-01-29T10:30:00Z",
  "primary_instance": "10.0.1.5:5432",
  "kv_store_count": 15420,
  "tables": {
    "resources": {"count": 5000, "max_updated_at": "2025-01-29T10:25:00Z"},
    "moments": {"count": 10000, "max_updated_at": "2025-01-29T10:28:00Z"}
  }
}
```

### Logs
```bash
# CronJob logs
kubectl logs -l app=unlogged-restorer --tail=100

# Argo Events sensor logs
kubectl logs -l sensor-name=unlogged-restore-trigger
```

### Alerts
Consider adding alerts for:
- `kv_store` count drops to 0
- Watermark not updated in >10 minutes
- Restore job failures

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `POSTGRES__CONNECTION_STRING` | Database connection | (required) |
| `S3__BUCKET_NAME` | Bucket for watermark | `rem-io-{env}` |
| `S3__REGION` | AWS region | `us-east-1` |

## Testing

```bash
cd rem
pytest tests/integration/test_unlogged_maintainer.py -v
```

Simulate a failover scenario:
```sql
-- On primary, truncate kv_store
TRUNCATE kv_store;

-- Run maintainer
-- python -m rem.workers.unlogged_maintainer --check-and-restore

-- Verify rebuild
SELECT count(*) FROM kv_store;
```

## Files

```
unlogged-restorer/
├── README.md                 # This file
├── kustomization.yaml        # Kustomize configuration
├── cronjob.yaml             # Periodic check (every 5 min)
├── argo-eventsource.yaml    # Watch CNPG Cluster CR
└── argo-sensor.yaml         # Trigger restore on changes
```

## Related

- [PostgreSQL UNLOGGED Tables](https://www.crunchydata.com/blog/postgresl-unlogged-tables)
- [CloudNativePG Failover](https://cloudnative-pg.io/documentation/current/failover/)
- [Argo Events Resource EventSource](https://argoproj.github.io/argo-events/eventsources/setup/resource/)
