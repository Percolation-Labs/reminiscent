# REM Quickstart Guide

## 🚀 Published to PyPI!

**Package:** `remdb` version 0.1.9
**PyPI:** https://pypi.org/project/remdb/
**CLI Command:** `rem`

## Installation Options

### Option 1: Standalone Docker (Zero Installation)

Run everything in containers - no Python installation needed.

```bash
# Clone repository
git clone https://github.com/mr-saoirse/remstack.git
cd remstack/rem

# Set API keys
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="your-key"  # Optional

# Start all services
docker compose up -d

# Use CLI via docker exec
docker exec rem-api rem --help
docker exec rem-api rem schema generate
docker exec rem-api rem db migrate --sql-dir sql/migrations
```

**Access Points:**
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- MCP: http://localhost:8000/api/v1/mcp
- PostgreSQL: localhost:5050

### Option 2: Hybrid (Recommended for Development)

Docker for infrastructure, pip install for CLI/library.

```bash
# Clone repository
git clone https://github.com/mr-saoirse/remstack.git
cd remstack/rem

# Start PostgreSQL only
docker compose up postgres -d

# Install from PyPI
pip install remdb[all]

# Set environment variables
export ANTHROPIC_API_KEY="your-key"
export POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem"
export AUTH__ENABLED="false"
export OTEL__ENABLED="false"

# Use CLI directly (no docker exec!)
rem --help
rem schema validate
rem db migrate --sql-dir sql/migrations
rem ask "What is REM?"

# Run API locally with hot reload
uvicorn rem.api.main:app --reload --port 8000
```

**Why Hybrid?**
- ⚡ Faster CLI (no container overhead)
- 🔥 Hot reload for development
- 🐛 Native debugging
- 🐘 Isolated PostgreSQL

### Option 3: Library Usage

Use REM as a Python library in your projects.

```bash
# Install in your project
pip install remdb[all]
```

```python
from rem.services.rem.service import RemService
from rem.agentic.context import AgentContext

# Connect to Docker PostgreSQL
service = RemService()
context = AgentContext(
    user_id="demo-user",
    tenant_id="demo-tenant"
)

# Ask questions
result = await service.ask_rem(
    query="What resources do we have?",
    context=context
)
print(result)
```

## Testing the Installation

### Verify CLI Installation
```bash
rem --help
rem schema --help
rem db --help
```

### Verify PostgreSQL Connection
```bash
docker exec rem-postgres psql -U rem -d rem -c "SELECT version();"
```

### Verify API Health
```bash
curl http://localhost:8000/health
```

## Environment Configuration

All configuration via environment variables:

```bash
# LLM Configuration (Required)
export LLM__ANTHROPIC_API_KEY="sk-ant-..."
export LLM__OPENAI_API_KEY="sk-..."
export LLM__DEFAULT_MODEL="anthropic:claude-sonnet-4-5-20250929"

# Database (Auto-configured in docker-compose)
export POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem"

# Auth & Observability (Disabled for local dev)
export AUTH__ENABLED="false"
export OTEL__ENABLED="false"

# S3 Storage (Optional)
export S3__BUCKET_NAME="rem-storage"
export S3__ENDPOINT_URL="http://minio:9000"
```

## Next Steps

1. **Explore API Docs:** http://localhost:8000/docs
2. **Upload Files:** Use file processing endpoints
3. **Create Agent Schemas:** Define custom extractors
4. **Connect MCP Clients:** http://localhost:8000/api/v1/mcp
5. **Run Evaluations:** `rem experiments --help`

## Troubleshooting

### CLI Not Found
```bash
# Make sure package is installed
pip list | grep remdb

# Check if CLI is in PATH
which rem

# If using venv, make sure it's activated
source venv/bin/activate
```

### PostgreSQL Connection Failed
```bash
# Check if container is running
docker compose ps

# Check logs
docker logs rem-postgres

# Verify connection string
echo $POSTGRES__CONNECTION_STRING
```

### API Not Starting
```bash
# Check API logs
docker logs rem-api

# Verify environment variables
docker exec rem-api env | grep LLM
```

## Uninstall

```bash
# Stop Docker services
docker compose down -v

# Remove Python package
pip uninstall remdb

# Remove test data
rm -rf /tmp/test-remdb
```

## Support

- **Issues:** https://github.com/mr-saoirse/remstack/issues
- **Docs:** https://github.com/mr-saoirse/remstack/blob/main/README.md
- **PyPI:** https://pypi.org/project/remdb/
