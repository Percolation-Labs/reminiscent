# REM - Resources Entities Moments

Cloud-native unified memory infrastructure for agentic AI systems built with Pydantic AI, FastAPI, and FastMCP.

## Quick Start

### Docker Compose (Recommended)

```bash
cd rem

# Set up API keys (required)
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# Or create a .env file (copy from .env.docker template)
cp .env.docker .env
# Edit .env and add your API keys

# Start API and PostgreSQL 18
docker compose up --build

# API will be available at http://localhost:8000
# PostgreSQL will be available at localhost:5050

# Test chat completions
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: acme-corp" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "What documents did Sarah Chen author?"}],
    "stream": false
  }'
```

### Local Development

```bash
cd rem

# Install dependencies
uv sync

# Set up environment variables
cp .env.example .env
# Edit .env and add your API keys:
# LLM__OPENAI_API_KEY=sk-...
# LLM__ANTHROPIC_API_KEY=sk-ant-...

# Run PostgreSQL separately or use docker compose for just postgres
docker compose up postgres -d

# Run API server with hot reload
uv run python -m rem.api.main

# Test chat completions
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: demo" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": false
  }'
```

## Architecture

### Core Components

1. **REM Models** (`models/`)
   - **Core Models**: `CoreModel`, `InlineEdge`, `RemQuery`
   - **Entities**: `Resource`, `Message`, `User`, `File`, `Moment`
   - All entities inherit from CoreModel: id, temporal tracking, multi-tenancy, graph connectivity, metadata

2. **Services** (`services/`)
   - **PostgresService**: CloudNativePG database operations
   - **RemService**: REM query execution with O(1) guarantees
   - **FS**: Unified file system (S3 + local) with format detection

3. **Agent System** (`agents/`, `providers/`)
   - **AgentContext**: Session context from HTTP headers
   - **AgentQuery**: Standardized query/knowledge/scratchpad structure
   - **Pydantic AI Factory**: JsonSchema � Pydantic model conversion

4. **MCP Server** (`mcp/`)
   - FastMCP server with REM query tools and resources
   - Mounted at `/api/v1/mcp` on FastAPI (not a separate deployment)
   - Stateless HTTP mode for Kubernetes compatibility

**Important**: The MCP (Model Context Protocol) server is not a separate deployment.
It is mounted as part of the rem-api FastAPI application.

5. **API** (`api/`)
   - OpenAI-compatible chat completions (streaming & non-streaming)
   - Header-based configuration (X-Tenant-Id, X-User-Id, X-Agent-Schema)
   - FastAPI with middleware stack

## Design Patterns

Key architectural patterns documented inline in code:

1. **Nested Pydantic Settings** - Environment variables with `__` delimiter
2. **Header to Context Mapping** - HTTP headers → AgentContext fields
3. **JsonSchema to Pydantic** - Dynamic agent creation from schemas
4. **Streaming with agent.iter()** - Full execution visibility with tool calls
5. **Stateless MCP Mounting** - Kubernetes-friendly stateless_http mode
6. **Schema Description Stripping** - Reduce token usage in LLM schemas
7. **Response Format Control** - Best-effort JSON extraction
8. **Discriminated Unions** - Type-safe tool inputs
9. **Middleware Ordering** - CORS last (runs first)
10. **Conditional OTEL** - Development-friendly observability

## Settings

All settings via environment variables with `__` delimiter:

```bash
# LLM
LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
LLM__DEFAULT_TEMPERATURE=0.5

# Auth (disabled by default)
AUTH__ENABLED=false
AUTH__OIDC_ISSUER_URL=https://accounts.google.com

# OTEL (disabled by default for local dev)
OTEL__ENABLED=false
OTEL__SERVICE_NAME=rem-api

# Postgres
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5432/rem

# S3
S3__BUCKET_NAME=rem-storage
S3__REGION=us-east-1
```

## API Endpoints

### Chat Completions (OpenAI-compatible)

```bash
POST /api/v1/chat/completions
```

**Headers**:
- `X-Tenant-Id`: Tenant identifier (required for REM)
- `X-User-Id`: User identifier
- `X-Session-Id`: Session/conversation identifier
- `X-Agent-Schema`: Agent schema URI to use

**Body**:
```json
{
  "model": "anthropic:claude-sonnet-4-5-20250929",
  "messages": [
    {"role": "user", "content": "Find all documents Sarah authored"}
  ],
  "stream": true,
  "response_format": {"type": "text"}
}
```

**Streaming Response** (SSE):
```
data: {"id": "chatcmpl-123", "choices": [{"delta": {"role": "assistant", "content": ""}}]}

data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "[Calling: rem_query]"}}]}

data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "Found 3 documents..."}}]}

data: {"id": "chatcmpl-123", "choices": [{"delta": {}, "finish_reason": "stop"}]}

data: [DONE]
```

### MCP Endpoint

```bash
# MCP HTTP transport
POST /api/v1/mcp
```

Tools and resources for REM query execution, resource management, file operations.

### Health Check

```bash
GET /health
# {"status": "healthy", "version": "0.1.0"}
```

## Development

### Docker Compose

```bash
# Start all services with hot reload
docker compose up

# Rebuild after dependency changes
docker compose up --build

# View logs
docker compose logs -f api
docker compose logs -f postgres

# Stop all services
docker compose down

# Stop and remove volumes (deletes database data)
docker compose down -v

# Connect to PostgreSQL
psql -h localhost -p 5050 -U rem -d rem
```

### Database Migrations

Migrations are automatically applied on container startup from `sql/migrations/*.sql`:
- `001_init_schema.sql` - Core schema with all entity tables and indexes

To add new migrations:
1. Create `sql/migrations/002_your_migration.sql`
2. Restart PostgreSQL container: `docker compose restart postgres`

### Test Data

Sample seed data is available in `tests/data/seed/001_sample_data.yaml` but **not** automatically loaded.

The YAML file contains structured test data for all entity types (users, resources, moments, messages, files, schemas).

To load test data, use Python:
```python
import yaml
from pathlib import Path
from rem.models.entities import User, Resource, Moment, Message, File, Schema

# Load YAML
data = yaml.safe_load(Path("tests/data/seed/001_sample_data.yaml").read_text())

# Create entities and insert into database
# See tests/data/seed/README.md for complete example
```

See `tests/data/seed/README.md` for complete loading instructions and pytest fixtures.

### Local Development

```bash
# Install dependencies
uv sync

# Run with auto-reload (requires PostgreSQL running)
uv run python -m rem.api.main

# Run tests (TODO)
uv run pytest

# Type check (TODO)
uv run mypy src/rem
```

## Deployment

See [`manifests/`](../../manifests/) for Pulumi infrastructure and Kubernetes manifests.

### Infrastructure (manifests/infra/)
- EKS cluster with Karpenter
- Separate NodePools for stateful (on-demand) and stateless (spot) workloads

### Platform (manifests/platform/)
- ArgoCD (GitOps)
- OpenTelemetry (observability)
- CloudNativePG (PostgreSQL 18 with pgvector)
- Arize Phoenix (LLM observability)

## Implementation Status

### ✅ Completed
- [x] **PostgresService** - Fully implemented with batch_upsert, connection pooling, tenant isolation
- [x] **RemService** - Query execution for LOOKUP, FUZZY, SQL, TRAVERSE implemented
- [x] **Models** - All entity models (Resource, Entity, Moment, Message, File, User) complete
- [x] **Settings** - Nested Pydantic settings with environment variable support
- [x] **MCP Server** - FastMCP integration with instructions and mounting patterns
- [x] **Chat Completions** - OpenAI-compatible API (streaming & non-streaming)
- [x] **Agent Factory** - JSON Schema to Pydantic AI conversion
- [x] **File System** - S3 and local providers with format detection

### 🚧 In Progress
- [ ] **MCP Tools** - Implement rem_query, ask_rem, create_resource, create_moment tools
- [ ] **MCP Resources** - Register schema docs and status resources
- [ ] **SEARCH Query** - Embedding generation integration (OpenAI/Anthropic API)
- [ ] **REM Query Router** - REST endpoint for direct REM query execution
- [ ] **CRUD Routers** - Resource and moment creation/update endpoints
- [ ] **Auth Implementation** - Complete OAuth providers and JWT validation
- [ ] **Tests** - Unit and integration tests for core services

### 📝 Design Complete (Stubs Present)
- [ ] **update_graph_edges** - PostgresService method (stub present)
- [ ] **vector_search** - PostgresService method (delegated to RemService)
- [ ] **OAuth routes** - Auth router stubs with redirect handling
- [ ] **OTEL setup** - Conditional instrumentation pattern defined

## License

MIT
