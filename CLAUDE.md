# CLAUDE.md

## Quick Reference

**REM** = Resources, Entities, Moments - a bio-inspired memory system for agentic AI.

**Key Files:**

- `rem/README.md` - Full documentation, CLI reference, API usage
- `rem/src/rem/settings.py` - All configuration options

**Local Development (Recommended):**

```bash
cd rem
tilt up                                     # Start postgres + API + worker with dashboard
# Open http://localhost:10350 for logs, restart buttons, task runners
```

**Common Commands:**

```bash
cd rem
pytest tests/integration/ -v -m "not llm"  # Run non-LLM tests
./scripts/run_mypy.sh                       # Type checking
rem ask "query"                             # Test queries
rem db diff                                 # Check schema drift
rem db schema generate                      # Regenerate schema SQL
```

---

## Critical Conventions

### 1. Use `date_utils` for All Datetimes

```python
# ALWAYS use UTC-naive datetimes
from rem.utils.date_utils import utc_now, to_iso, parse_iso, days_ago

now = utc_now()
cutoff = days_ago(30)

# NEVER use datetime directly
# from datetime import datetime  # Don't do this!
```

### 2. Use `settings` for Configuration

```python
# ALWAYS use settings
from rem.settings import settings
api_key = settings.llm.openai_api_key

# NEVER use os.getenv() for API keys
```

### 3. Use Factory Functions

```python
# Database
from rem.services.postgres import get_postgres_service
db = get_postgres_service()

# Agents
from rem.agentic import create_agent, create_agent_from_schema_file
agent = await create_agent(context=context)

# NEVER instantiate services directly
```

### 4. Serialize Pydantic Models at Boundaries

```python
from rem.agentic.serialization import serialize_agent_result

# ALWAYS serialize before returning from MCP tools/API endpoints
return {"response": result.output.model_dump()}  # Correct

# NEVER return Pydantic models directly
return {"response": result.output}  # Wrong - fields may be lost
```

### 5. Shared Utilities

| Module | Purpose |
|--------|---------|
| `rem.utils.date_utils` | UTC-naive datetime operations |
| `rem.utils.mime_types` | MIME type mappings |
| `rem.utils.constants` | Timeouts, magic numbers |
| `rem.utils.files` | Temp file handling |

See `rem/src/rem/utils/README.md` for full API.

---

## Architecture Overview

```text
remstack/
├── rem/                    # Python package (PyPI: remdb)
│   ├── src/rem/
│   │   ├── api/           # FastAPI + MCP server
│   │   ├── agentic/       # Agent framework (Pydantic AI)
│   │   ├── services/      # Database, content, dreaming
│   │   └── cli/           # Command-line interface
│   └── README.md          # Full documentation
├── manifests/             # Kubernetes deployment
│   ├── infra/            # AWS CDK for EKS
│   ├── platform/         # ArgoCD, CloudNativePG
│   ├── application/      # rem-api, file-processor
│   └── local/            # Tilt local development
└── CLAUDE.md             # This file
```

**Deployments:**

- **rem-api**: FastAPI + MCP at `/api/v1/mcp` (HPA: 2-10 replicas)
- **file-processor**: SQS worker for S3 files (KEDA: 0-20 replicas)

**Key Patterns:**

- MCP is NOT separate - mounted in FastAPI
- Data scoped by `user_id` (not `tenant_id`)
- Schema evolution via Pydantic models + Alembic diff
- OTEL disabled locally, enabled in prod via `OTEL__ENABLED=true`

**Schema Management (code is source of truth):**

Two migration files only:
- `001_install.sql` - Core infrastructure (extensions, functions, KV store)
- `002_install_models.sql` - Entity tables (auto-generated from models)

No incremental migrations (003, 004, etc.) - regenerate from code.

```bash
# Adding/modifying models:
# 1. Edit models in src/rem/models/entities/
# 2. Register new models in src/rem/registry.py
rem db schema generate   # Regenerate 002_install_models.sql
rem db diff              # See additive changes (default: --strategy additive)
rem db diff --generate   # Generate migration SQL file
rem db apply <file>      # Apply the migration

# Migration strategies:
rem db diff                        # additive only (safe, no drops)
rem db diff --strategy full        # all changes including drops
rem db diff --strategy safe        # additive + safe type widenings

# CI/CD - detect drift:
rem db diff --check      # Exit 1 if drift detected

# Remote database (production/staging):
kubectl port-forward -n <namespace> svc/rem-postgres-rw 5433:5432 &
POSTGRES__CONNECTION_STRING="postgresql://user:pass@localhost:5433/db" rem db diff
```

---

## REM Query Dialect

Four query types with performance guarantees:

| Query | Complexity | Use When |
|-------|------------|----------|
| `LOOKUP "entity-key"` | O(1) | Know exact entity name |
| `FUZZY "text" THRESHOLD 0.3` | O(n) | Typos, partial matches |
| `SEARCH "semantic query" LIMIT 10` | O(log n) | Conceptual similarity |
| `TRAVERSE FROM "entity" TYPE "rel" DEPTH 2` | O(edges) | Graph relationships |

**Graph edges use human-readable labels** (not UUIDs):

```json
{"dst": "sarah-chen", "rel_type": "authored_by", "weight": 1.0}
```

See `rem/README.md#rem-query-dialect` for full grammar.

---

## Design Principles

- **Lean implementation** - stubs first, no hacks
- **DRY** - use existing services, don't duplicate
- **No backwards compatibility hacks** - delete unused code
- **Provider-agnostic naming** - no "pydantic" or "openai" in public APIs
- **Pydantic 2.0** for all data structures

---

## Component Documentation

| Component | README Location |
|-----------|-----------------|
| **REM Package** | `rem/README.md` |
| **Local Dev (Tilt)** | `manifests/local/README.md` |
| **Agentic Framework** | `rem/src/rem/agentic/README.md` |
| **PostgreSQL Service** | `rem/src/rem/services/postgres/README.md` |
| **Dreaming Workers** | `rem/src/rem/services/dreaming/README.md` |
| **Phoenix Evaluation** | `rem/src/rem/services/phoenix/README.md` |
| **Content Processing** | `rem/src/rem/services/content/README.md` |
| **CLI Commands** | `rem/src/rem/cli/README.md` |
| **Utilities** | `rem/src/rem/utils/README.md` |
| **EKS Infrastructure** | `manifests/infra/cdk-eks/README.md` |
| **Platform (ArgoCD)** | `manifests/platform/README.md` |
| **Application Deployment** | `manifests/application/README.md` |

---

## Testing

```bash
cd rem

# Non-LLM tests (fast, no API costs) - ALWAYS run these first
pytest tests/integration/ -v -m "not llm"

# LLM tests (expensive, uses API credits)
pytest tests/integration/ -v -m "llm"

# Type checking
./scripts/run_mypy.sh
```

**Test markers:**

- `@pytest.mark.llm` - Makes LLM API calls (skip with `-m "not llm"`)
- `@pytest.mark.slow` - Long-running tests

---

## Publishing to PyPI

```bash
cd rem
# 1. Update version in pyproject.toml
# 2. Build
rm -rf dist/ && uv build
# 3. Publish
uv publish --token $PYPI_TOKEN
```

**Current Version:** Check `rem/pyproject.toml`

---

## Active Migrations

### tenant_id → user_id (Complete)

Data now scoped by `user_id`, not `tenant_id`. The `tenant_id` column remains for backwards compatibility but is set to `user_id` value.

Schema changes are now managed via the diff-based workflow - no incremental migration files.
