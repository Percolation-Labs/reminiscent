# CLAUDE.md

## Quick Reference

**REM** = Resources, Entities, Moments - a bio-inspired memory system for agentic AI.

**Key Files:**

- `rem/README.md` - Full documentation, CLI reference, API usage
- `rem/src/rem/settings.py` - All configuration options

**Common Commands:**

```bash
cd rem
pytest tests/integration/ -v -m "not llm"  # Run non-LLM tests
./scripts/run_mypy.sh                       # Type checking
rem ask "query"                             # Test queries
rem db migrate                              # Apply migrations
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
│   ├── infra/            # EKS, Pulumi
│   ├── platform/         # ArgoCD, CloudNativePG
│   └── application/      # rem-api, file-processor
└── CLAUDE.md             # This file
```

**Deployments:**

- **rem-api**: FastAPI + MCP at `/api/v1/mcp` (HPA: 2-10 replicas)
- **file-processor**: SQS worker for S3 files (KEDA: 0-20 replicas)

**Key Patterns:**

- MCP is NOT separate - mounted in FastAPI
- Data scoped by `user_id` (not `tenant_id`)
- Schema evolution via Pydantic models (no Alembic)
- OTEL disabled locally, enabled in prod via `OTEL__ENABLED=true`

**Schema Workflow (when adding/modifying entity models):**
```bash
# 1. Edit models in src/rem/models/entities/
# 2. Regenerate migration file
rem db schema generate -m src/rem/models/entities
# 3. Apply to database
rem db migrate
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
| **Agentic Framework** | `rem/src/rem/agentic/README.md` |
| **PostgreSQL Service** | `rem/src/rem/services/postgres/README.md` |
| **Dreaming Workers** | `rem/src/rem/services/dreaming/README.md` |
| **Phoenix Evaluation** | `rem/src/rem/services/phoenix/README.md` |
| **Content Processing** | `rem/src/rem/services/content/README.md` |
| **CLI Commands** | `rem/src/rem/cli/README.md` |
| **Utilities** | `rem/src/rem/utils/README.md` |
| **EKS Infrastructure** | `manifests/infra/pulumi/eks-yaml/README.md` |
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

### tenant_id → user_id (90% complete)

Data now scoped by `user_id`, not `tenant_id`. The `tenant_id` column remains for backwards compatibility but is set to `user_id` value.

**Migration file:** `src/rem/sql/migrations/006_tenant_to_user_migration.sql`

**Remaining:** Dreaming worker signatures, integration tests.

See `rem/REFACTORING_TODO.md` for tracking.
