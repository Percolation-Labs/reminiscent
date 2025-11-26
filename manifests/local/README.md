# REM Local Development with Tilt

Get the REM stack running locally in 5 minutes with hot reload, unified logging, and task buttons.

## Quick Start

```bash
# 1. Check prerequisites
./setup.sh

# 2. Create .env (if not exists)
cp ../../rem/.env.example ../../rem/.env
# Edit ../../rem/.env - add ANTHROPIC_API_KEY or OPENAI_API_KEY

# 3. Start everything
tilt up

# 4. Open the dashboard
open http://localhost:10350
```

## Tiers

This setup supports three progressive tiers. Start with Tier 1 and enable more features as needed.

### Tier 1: Docker Compose (Default)

```bash
tilt up
```

The simplest mode - wraps the existing `docker-compose.yml`:
- PostgreSQL with pgvector on port 5050
- API with hot reload on port 8000
- Worker (file processor)

### Tier 2: + MinIO Storage

```bash
tilt up -- --enable_minio
```

Adds S3-compatible storage for testing file uploads:
- MinIO API on port 9000
- MinIO Console on port 9001
- Auto-created `rem-storage` bucket
- API and Worker pre-configured to use MinIO

**MinIO Credentials:** `minioadmin` / `minioadmin`

### Tier 3: Local Kubernetes

```bash
# First time: create a local cluster
kind create cluster --name rem-local

# Then start Tilt in K8s mode
tilt up -- --k8s_mode
```

Tests your Kustomize manifests locally using **production manifests as the base**:
- Uses `manifests/application/rem-stack/overlays/local` (patches production manifests)
- Removes CRD dependencies (ExternalSecrets, CloudNativePG, KEDA, HPA)
- Standalone PostgreSQL deployment
- Live sync for source code changes
- Catches K8s-specific issues before push

**Note:** The local overlay patches production manifests to remove cloud-specific
dependencies. This ensures local and production stay in sync - any changes to
production deployment specs are automatically reflected locally.

## Services

| Service    | Port | URL                                     |
|------------|------|-----------------------------------------|
| API        | 8000 | http://localhost:8000                   |
| Swagger UI | 8000 | http://localhost:8000/docs              |
| MCP        | 8000 | http://localhost:8000/api/v1/mcp        |
| PostgreSQL | 5050 | `postgresql://rem:rem@localhost:5050/rem` |
| MinIO API  | 9000 | http://localhost:9000 (Tier 2)          |
| MinIO UI   | 9001 | http://localhost:9001 (Tier 2)          |

## Task Buttons

Click these in the Tilt UI (http://localhost:10350) to run common tasks:

| Button           | Description                              |
|------------------|------------------------------------------|
| db-migrate       | Apply database migrations                |
| test-integration | Run non-LLM integration tests            |
| type-check       | Run mypy type checking                   |
| health-check     | Check if API is responding               |
| db-reset         | Reset database (deletes all data!)       |

## Configuration

### User Settings

Create `tilt_config.json` to set defaults:

```json
{
  "enable_minio": true,
  "k8s_mode": false
}
```

### Environment Variables

Copy and edit `../../rem/.env`:

```bash
# Required: at least one LLM API key
LLM__ANTHROPIC_API_KEY=sk-ant-...
LLM__OPENAI_API_KEY=sk-...

# Database (pre-configured for docker-compose)
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5050/rem
```

See `../../rem/.env.example` for all options.

## Hot Reload

**Docker Compose mode (Tier 1 & 2):**
- Source changes in `rem/src/` trigger automatic API reload
- Worker requires manual restart: click restart in Tilt UI

**Kubernetes mode (Tier 3):**
- Source synced to pods via Tilt live_update
- No image rebuild needed for Python changes

## Stopping

```bash
# Stop services (keeps data)
tilt down

# Stop and delete database volume
tilt down
docker compose -f ../../rem/docker-compose.yml down -v
```

## Troubleshooting

### Port already in use

```bash
# Check what's using the port
lsof -i :8000
lsof -i :5050

# Stop existing containers
docker compose -f ../../rem/docker-compose.yml down
```

### Database connection refused

Wait 5-10 seconds for PostgreSQL to start. Check the Tilt UI for postgres health status.

### API keeps restarting

Check the Tilt logs for Python errors. Common causes:
- Missing environment variables
- Syntax errors in code
- Import errors

### MinIO bucket not created

The `minio-init` container should create the bucket automatically. If it fails:

```bash
# Manual bucket creation
docker exec rem-minio mc mb local/rem-storage --ignore-existing
```

### K8s mode: image not loading

```bash
# Manually load image into kind
docker build -t rem-local:latest ../../rem
kind load docker-image rem-local:latest --name rem-local
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Tilt Dashboard                            │
│                     http://localhost:10350                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Tier 1: Docker Compose        Tier 2: + MinIO                  │
│  ┌─────────────────────┐       ┌─────────────────────┐          │
│  │  postgres :5050     │       │  postgres :5050     │          │
│  │  api :8000          │       │  api :8000          │          │
│  │  worker             │       │  worker             │          │
│  └─────────────────────┘       │  minio :9000/:9001  │          │
│                                └─────────────────────┘          │
│                                                                  │
│  Tier 3: Local Kubernetes (uses production manifests as base)   │
│  ┌─────────────────────────────────────────────────────┐        │
│  │  kind cluster (rem-local)                           │        │
│  │  ┌─────────────┐ ┌─────────────┐                   │        │
│  │  │ postgres-   │ │ rem-api     │                   │        │
│  │  │ local :5432 │ │ :8000       │                   │        │
│  │  └─────────────┘ └─────────────┘                   │        │
│  │                                                     │        │
│  │  Source: manifests/application/rem-stack/          │        │
│  │          overlays/local (patches production)       │        │
│  └─────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

## What Tilt Adds vs Docker Compose

| Feature               | docker-compose       | Tilt                    |
|-----------------------|---------------------|-------------------------|
| Start services        | `docker compose up` | `tilt up`               |
| View logs             | Multiple terminals  | Unified UI with filters |
| Restart service       | Manual command      | Click button            |
| Run migrations        | `docker exec ...`   | Click "db-migrate"      |
| Run tests             | `cd rem && pytest`  | Click "test-integration"|
| See file changes      | Manual check        | Real-time watcher       |
| Service status        | `docker compose ps` | Color-coded UI          |
| Links to endpoints    | Remember URLs       | Clickable links         |
| Progressive features  | Separate files      | `--enable_minio` flag   |
