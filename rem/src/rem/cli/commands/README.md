# REM CLI Commands

## Database Management (`rem db`)

REM uses a **code-as-source-of-truth** approach to database schema management. Pydantic models define the schema, and the database is kept in sync via diff-based migrations.

### Quick Reference

```bash
rem db schema generate   # Regenerate schema SQL from registered models
rem db diff              # Compare models vs database (detect drift)
rem db diff --check      # CI mode: exit 1 if drift detected
rem db apply <file>      # Apply SQL file to database
```

### Schema Management Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    Source of Truth                          │
│                                                             │
│   Pydantic Models (CoreModel subclasses)                   │
│   └── src/rem/models/entities/*.py                         │
│                                                             │
│   Model Registry                                            │
│   └── Core models auto-registered                          │
│   └── Custom models via @rem.register_model                │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                 rem db schema generate                      │
│                                                             │
│   Generates SQL from registry → 002_install_models.sql     │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      rem db diff                            │
│                                                             │
│   Compares models ↔ database using Alembic autogenerate    │
│   Shows: + additions, - removals, ~ modifications          │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    rem db apply                             │
│                                                             │
│   Executes SQL directly against database                    │
│   Optionally logs to rem_migrations (audit only)           │
└─────────────────────────────────────────────────────────────┘
```

### File Structure

```
src/rem/sql/
├── migrations/
│   ├── 001_install.sql          # Core infrastructure (manual)
│   └── 002_install_models.sql   # Entity tables (auto-generated)
└── background_indexes.sql       # HNSW vector indexes (optional)
```

**Key principle**: Only two migration files. No incremental `003_`, `004_` files. The models file is always regenerated to match code.

### Commands

#### `rem db schema generate`

Regenerate `002_install_models.sql` from the model registry:

```bash
rem db schema generate
```

This reads all registered models (core + custom) and generates:
- CREATE TABLE statements for each entity
- Embeddings tables (`embeddings_<table>`)
- KV_STORE triggers for cache maintenance
- Foreground indexes (GIN for JSONB, B-tree for lookups)

#### `rem db diff`

Compare Pydantic models against the live database:

```bash
# Show differences
rem db diff

# CI mode: exit 1 if drift detected
rem db diff --check
```

Output shows:
- `+ ADD COLUMN` - Column exists in model but not in DB
- `- DROP COLUMN` - Column exists in DB but not in model
- `~ ALTER COLUMN` - Column type or constraints differ
- `+ CREATE TABLE` - Table exists in model but not in DB
- `- DROP TABLE` - Table exists in DB but not in model

#### `rem db apply`

Apply a SQL file directly to the database:

```bash
# Apply with audit logging (default)
rem db apply src/rem/sql/migrations/002_install_models.sql

# Preview without executing
rem db apply --dry-run src/rem/sql/migrations/002_install_models.sql

# Apply without logging to rem_migrations
rem db apply --no-log src/rem/sql/migrations/002_install_models.sql
```

### Typical Workflows

#### Initial Setup

```bash
# 1. Generate schema from models
rem db schema generate

# 2. Apply infrastructure (extensions, kv_store)
rem db apply src/rem/sql/migrations/001_install.sql

# 3. Apply entity tables
rem db apply src/rem/sql/migrations/002_install_models.sql

# 4. Verify no drift
rem db diff
```

#### Adding a New Entity

```bash
# 1. Create model in src/rem/models/entities/
# 2. Register in src/rem/registry.py (add to core_models list)
# 3. Regenerate schema
rem db schema generate

# 4. Check what changed
rem db diff

# 5. Apply changes
rem db apply src/rem/sql/migrations/002_install_models.sql
```

#### Modifying an Existing Entity

```bash
# 1. Modify model in src/rem/models/entities/
# 2. Regenerate schema
rem db schema generate

# 3. Check what changed
rem db diff

# 4. Apply changes (idempotent - uses IF NOT EXISTS)
rem db apply src/rem/sql/migrations/002_install_models.sql
```

#### CI/CD Pipeline

```bash
# Fail build if schema drift detected
rem db diff --check
```

### Registering Custom Models

```python
import rem
from rem.models.core import CoreModel

@rem.register_model
class MyEntity(CoreModel):
    name: str
    description: str  # Auto-embeds (content field)

# Or with options:
@rem.register_model(table_name="custom_table")
class AnotherEntity(CoreModel):
    title: str
```

---

## Configuration (`rem configure`)

Interactive configuration wizard for REM setup.

### Quick Start

```bash
# Basic configuration (creates ~/.rem/config.yaml)
rem configure

# Configure + install database tables
rem configure --install

# View current configuration
rem configure --show

# Edit configuration file
rem configure --edit
```

### Configuration File

`~/.rem/config.yaml`:

```yaml
postgres:
  connection_string: postgresql://user:pass@localhost:5432/rem

llm:
  default_model: anthropic:claude-sonnet-4-5-20250929
  openai_api_key: sk-...
  anthropic_api_key: sk-ant-...

s3:
  bucket_name: rem-storage
  region: us-east-1
```

### Environment Variables

All configuration can be overridden via environment variables:

```bash
export POSTGRES__CONNECTION_STRING=postgresql://user:pass@host:5432/db
export LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
export LLM__OPENAI_API_KEY=sk-...
```

**Precedence**: Environment variables > Config file > Defaults

---

## Cluster Management (`rem cluster`)

Commands for deploying REM to Kubernetes.

### Quick Reference

```bash
rem cluster init           # Initialize cluster config
rem cluster generate       # Generate all manifests (ArgoCD, ConfigMaps, etc.)
rem cluster setup-ssm      # Create required SSM parameters in AWS
rem cluster validate       # Validate deployment prerequisites
rem cluster env check      # Validate .env for cluster deployment
```

### `rem cluster generate`

Generates all Kubernetes manifests from cluster config:

```bash
rem cluster generate
```

This generates/updates:
- ArgoCD Application manifests
- ClusterSecretStore configurations
- SQL init ConfigMap (from `rem/sql/migrations/*.sql`)

The SQL ConfigMap is used by CloudNativePG for database initialization on first cluster bootstrap.

### `rem cluster env`

Environment configuration management:

```bash
rem cluster env check              # Validate .env for staging
rem cluster env check --env prod   # Validate for production
rem cluster env generate           # Generate ConfigMap from .env
rem cluster env diff               # Compare .env with cluster ConfigMap
```

---

## Other Commands

| Command | Description |
|---------|-------------|
| `rem ask` | Interactive chat with REM agents |
| `rem serve` | Start FastAPI server |
| `rem mcp` | MCP server commands |
| `rem dreaming` | Background knowledge processing |
| `rem process` | File processing utilities |

Run `rem COMMAND --help` for detailed usage.

## See Also

- [rem/README.md](../../../../../README.md) - Main documentation
- [CLAUDE.md](../../../../../CLAUDE.md) - Architecture overview
- [postgres/README.md](../../services/postgres/README.md) - Database service details
