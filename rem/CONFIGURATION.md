# REM Configuration Guide

REM provides a flexible configuration system that supports both file-based configuration and environment variables.

## Quick Start

### 1. Install REM

```bash
pip install rem
```

### 2. Configure REM

Run the interactive configuration wizard:

```bash
rem configure
```

This will:
- Prompt for PostgreSQL connection details
- Ask for LLM provider API keys (optional)
- Configure S3 storage settings (optional)
- Save configuration to `~/.rem/config.yaml`

### 3. Install Database Tables (Optional)

```bash
rem configure --install
```

Or separately:

```bash
rem db migrate
```

### 4. Start the API Server

```bash
rem serve
```

## Configuration File

Configuration is stored in `~/.rem/config.yaml` with the following structure:

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

# Additional custom environment variables
env:
  MY_CUSTOM_VAR: value
```

## Configuration Precedence

Configuration values are loaded in the following order (highest priority first):

1. **Environment variables** (e.g., `POSTGRES__CONNECTION_STRING`)
2. **Configuration file** (`~/.rem/config.yaml`)
3. **Default values** (from `rem/settings.py`)

This allows you to:
- Use the config file for permanent settings
- Override specific values with environment variables
- Have sensible defaults for all settings

## Managing Configuration

### View Current Configuration

```bash
rem configure --show
```

### Edit Configuration

```bash
rem configure --edit
```

This opens the configuration file in your `$EDITOR` (defaults to vim).

You can also manually edit:

```bash
vim ~/.rem/config.yaml
```

### Reconfigure

Run the wizard again to update your configuration:

```bash
rem configure
```

## Environment Variable Format

All configuration can be set via environment variables using the double underscore delimiter:

```bash
# Postgres settings
export POSTGRES__CONNECTION_STRING=postgresql://user:pass@host:5432/db
export POSTGRES__POOL_MIN_SIZE=5
export POSTGRES__POOL_MAX_SIZE=20

# LLM settings
export LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
export LLM__DEFAULT_TEMPERATURE=0.5
export LLM__OPENAI_API_KEY=sk-...
export LLM__ANTHROPIC_API_KEY=sk-ant-...

# S3 settings
export S3__BUCKET_NAME=rem-storage
export S3__REGION=us-east-1
export S3__ENDPOINT_URL=http://localhost:9000
```

## Starting the Server

### Development Mode (auto-reload)

```bash
rem serve --reload
```

### Production Mode (multiple workers)

```bash
rem serve --workers 4
```

### Custom Host/Port

```bash
rem serve --host 0.0.0.0 --port 8080
```

### Override Config via Environment

```bash
POSTGRES__CONNECTION_STRING=postgresql://prod:pass@prod-db:5432/rem rem serve --workers 4
```

## Complete Workflow Example

```bash
# 1. Install REM
pip install rem

# 2. Run configuration wizard with database installation
rem configure --install

# 3. Verify configuration
rem configure --show

# 4. Start the server
rem serve --reload

# 5. Test the installation
rem ask "Hello, REM!"
```

## Advanced Configuration

### Multiple Environments

You can maintain different configurations for different environments:

```bash
# Development
cp ~/.rem/config.yaml ~/.rem/config.dev.yaml

# Production
cp ~/.rem/config.yaml ~/.rem/config.prod.yaml

# Switch between them
cp ~/.rem/config.prod.yaml ~/.rem/config.yaml
```

Or use environment variables:

```bash
# Development
export POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5432/rem

# Production
export POSTGRES__CONNECTION_STRING=postgresql://user:pass@prod-db:5432/rem
```

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
      S3__BUCKET_NAME: rem-prod
```

```yaml
# Kubernetes deployment
apiVersion: v1
kind: Secret
metadata:
  name: rem-secrets
stringData:
  POSTGRES__CONNECTION_STRING: postgresql://rem:rem@postgres:5432/rem
  LLM__OPENAI_API_KEY: sk-...

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rem-api
spec:
  template:
    spec:
      containers:
      - name: rem-api
        image: rem:latest
        envFrom:
        - secretRef:
            name: rem-secrets
```

## Troubleshooting

### Configuration not loading

Check that the file exists and is valid YAML:

```bash
cat ~/.rem/config.yaml
python -c "import yaml; yaml.safe_load(open('/Users/$USER/.rem/config.yaml'))"
```

### Environment variables not working

Ensure you're using the correct double underscore delimiter:

```bash
# ✅ Correct
export POSTGRES__CONNECTION_STRING=postgresql://...

# ❌ Incorrect (single underscore)
export POSTGRES_CONNECTION_STRING=postgresql://...
```

### Database connection failing

Verify the connection string:

```bash
psql "postgresql://user:pass@host:5432/db" -c "SELECT version();"
```

### Settings not updating

Remember that environment variables take precedence over the config file. If a setting isn't changing, check if it's set in your environment:

```bash
env | grep POSTGRES
env | grep LLM
env | grep S3
```

## See Also

- [CLAUDE.md](CLAUDE.md) - Architecture overview
- [rem/sql/README.md](rem/sql/README.md) - Database schema documentation
- [rem/src/rem/settings.py](rem/src/rem/settings.py) - All available settings
