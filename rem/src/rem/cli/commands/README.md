# REM CLI Commands

## Configuration (`rem configure`)

Interactive configuration wizard for REM setup.

### Quick Start

```bash
# Basic configuration (creates ~/.rem/config.yaml)
rem configure

# Configure + install database tables
rem configure --install

# Configure + install + register with Claude Desktop
rem configure --install --claude-desktop
```

### Managing Configuration

```bash
# View current configuration
rem configure --show

# Edit configuration file
rem configure --edit  # Opens in $EDITOR (defaults to vim)

# Or edit manually
vim ~/.rem/config.yaml
```

### Configuration File Structure

`~/.rem/config.yaml`:

```yaml
postgres:
  connection_string: postgresql://user:pass@localhost:5432/rem
  pool_min_size: 5
  pool_max_size: 20

llm:
  default_model: anthropic:claude-sonnet-4-5-20250929
  default_temperature: 0.5
  openai_api_key: sk-...
  anthropic_api_key: sk-ant-...

s3:
  bucket_name: rem-storage
  region: us-east-1
  # Optional: for MinIO/LocalStack
  endpoint_url: http://localhost:9000
  access_key_id: minioadmin
  secret_access_key: minioadmin
```

### Environment Variables

All configuration can be overridden via environment variables using double underscore delimiter:

```bash
# Postgres
export POSTGRES__CONNECTION_STRING=postgresql://user:pass@host:5432/db
export POSTGRES__POOL_MIN_SIZE=5
export POSTGRES__POOL_MAX_SIZE=20

# LLM
export LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
export LLM__OPENAI_API_KEY=sk-...
export LLM__ANTHROPIC_API_KEY=sk-ant-...

# S3
export S3__BUCKET_NAME=rem-storage
export S3__REGION=us-east-1
```

### Configuration Precedence

1. **Environment variables** (highest priority)
2. **Configuration file** (`~/.rem/config.yaml`)
3. **Default values** (from `rem/settings.py`)

### Docker/Kubernetes

In containerized environments, use environment variables exclusively:

```yaml
# docker-compose.yml
services:
  rem-api:
    image: rem:latest
    environment:
      POSTGRES__CONNECTION_STRING: postgresql://rem:rem@postgres:5432/rem
      LLM__OPENAI_API_KEY: ${OPENAI_API_KEY}
```

```yaml
# Kubernetes ConfigMap/Secret
apiVersion: v1
kind: Secret
metadata:
  name: rem-secrets
stringData:
  POSTGRES__CONNECTION_STRING: postgresql://rem:rem@postgres:5432/rem
  LLM__OPENAI_API_KEY: sk-...
```

## Other Commands

- **`rem ask`** - Interactive chat with REM memory
- **`rem serve`** - Start FastAPI server
- **`rem db`** - Database management (migrate, seed, etc.)
- **`rem schema`** - Schema generation and validation
- **`rem mcp`** - MCP server commands
- **`rem dreaming`** - Background knowledge processing
- **`rem process`** - File processing utilities
- **`rem phoenix`** - Arize Phoenix integration (evaluation)
- **`rem experiments`** - Experiment tracking and management

Run `rem COMMAND --help` for detailed usage of each command.

## See Also

- [README.md](../../../../../README.md) - Main documentation
- [CLAUDE.md](../../../../../CLAUDE.md) - Architecture overview
- [settings.py](../../settings.py) - All available settings
