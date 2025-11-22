# REM - Resources Entities Moments

Cloud-native unified memory infrastructure for agentic AI systems built with Pydantic AI, FastAPI, and FastMCP.

## Killer Features

| Feature | Description | Benefits |
|---------|-------------|----------|
| **OpenAI-Compatible Chat API** | Drop-in replacement for OpenAI chat completions API with streaming support | Use with existing OpenAI clients, switch models across providers (OpenAI, Anthropic, etc.) |
| **Built-in MCP Server** | FastMCP server with 5 tools + 3 resources for memory operations | Export memory to Claude Desktop, Cursor, or any MCP-compatible host |
| **REM Query Engine** | Multi-index query system (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE) with custom dialect | O(1) lookups, semantic search, graph traversal - all tenant-isolated |
| **Dreaming Workers** | Background workers for entity extraction, moment generation, and affinity matching | Automatic knowledge graph construction from resources (0% → 100% query answerable) |
| **PostgreSQL + pgvector** | CloudNativePG with PostgreSQL 18, pgvector extension, streaming replication | Production-ready vector search, no external vector DB needed |
| **AWS EKS Recipe** | Complete infrastructure-as-code with Pulumi, Karpenter, ArgoCD | Deploy to production EKS in minutes with auto-scaling and GitOps |
| **JSON Schema Agents** | Dynamic agent creation from YAML schemas via Pydantic AI factory | Define agents declaratively, version control schemas, load dynamically |
| **Content Providers** | Audio transcription (Whisper), vision (GPT-4V, Claude), PDFs, DOCX, images | Multimodal ingestion out of the box with format detection |
| **Configurable Embeddings** | Provider-agnostic embedding system (OpenAI, Cohere, Jina) | Switch embedding providers via env vars, no code changes |
| **Multi-Tenancy** | Tenant isolation at database level with automatic scoping | SaaS-ready with complete data separation per tenant |
| **Streaming Everything** | SSE for chat, background workers for embeddings, async throughout | Real-time responses, non-blocking operations, scalable |
| **Zero Vendor Lock-in** | Raw HTTP clients (no OpenAI SDK), swappable providers, open standards | Not tied to any vendor, easy to migrate, full control |

## Installation

### 🚀 Published to PyPI

**Package:** `remdb` | **PyPI:** https://pypi.org/project/remdb/ | **CLI Command:** `rem`

```bash
# Install from PyPI (includes CLI + library)
pip install remdb[all]

# Verify installation
rem --help

# Configure REM (interactive wizard)
rem configure

# Configure and install database tables
rem configure --install

# Configure + install + register with Claude Desktop
rem configure --install --claude-desktop
```

### Three Deployment Options

**Option 1: Standalone Docker** (Zero Python installation)
```bash
git clone https://github.com/mr-saoirse/remstack.git
cd remstack/rem
export ANTHROPIC_API_KEY="your-key"
docker compose up -d

# Use CLI via docker exec
docker exec rem-api rem --help
```

**Option 2: Hybrid** (Recommended for development)
```bash
# Docker for PostgreSQL only
docker compose up postgres -d

# Install from PyPI
pip install remdb[all]
export POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem"

# Use CLI directly (no docker exec!)
rem --help
rem ask "What is REM?"
```

**Option 3: Library Usage** (Embed in your projects)
```python
from rem.services.rem.service import RemService
from rem.agentic.context import AgentContext

service = RemService()
context = AgentContext(user_id="user-123", tenant_id="acme-corp")
result = await service.ask_rem("What resources do we have?", context=context)
```

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

## Publishing to PyPI

**Prerequisites:**
```bash
pip install build twine
export PYPI_API_KEY="pypi-..."  # Create at https://pypi.org/manage/account/token/
```

**Quick Publish:**
```bash
# Update version in pyproject.toml
# version = "0.1.x"

# Build and publish using the archived script
./.claude/archive/publish.sh
```

The `publish.sh` script handles cleaning, building, and uploading to PyPI automatically. See `.claude/archive/PUBLISH.md` for detailed publishing documentation.

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

data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "[Calling: search_rem]"}}]}

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

## CLI Reference

REM provides a comprehensive command-line interface for all operations.

### Configuration & Server

#### `rem configure` - Interactive Setup Wizard

Set up REM with PostgreSQL, LLM providers, and S3 storage.

```bash
# Interactive wizard (creates ~/.rem/config.yaml)
rem configure

# Run wizard + install database tables
rem configure --install

# Show current configuration
rem configure --show

# Edit configuration in $EDITOR
rem configure --edit

# Register with Claude Desktop
rem configure --claude-desktop
```

#### `rem mcp` - Run MCP Server

Run the FastMCP server for Claude Desktop integration.

```bash
# Stdio mode (for Claude Desktop)
rem mcp

# HTTP mode (for testing)
rem mcp --http --port 8001
```

**Configuration File:** `~/.rem/config.yaml`

```yaml
postgres:
  connection_string: postgresql://rem:rem@localhost:5432/rem
  pool_min_size: 5
  pool_max_size: 20

llm:
  default_model: anthropic:claude-sonnet-4-5-20250929
  openai_api_key: sk-...
  anthropic_api_key: sk-ant-...

s3:
  bucket_name: rem-storage
  region: us-east-1
```

**Precedence:** Environment variables > Config file > Defaults

#### `rem serve` - Start API Server

Start the FastAPI server with uvicorn.

```bash
# Use settings from config
rem serve

# Development mode (auto-reload)
rem serve --reload

# Production mode (4 workers)
rem serve --workers 4

# Bind to all interfaces
rem serve --host 0.0.0.0 --port 8080

# Override log level
rem serve --log-level debug
```

### Database Management

#### `rem db migrate` - Run Migrations

Apply database migrations (install.sql and install_models.sql).

```bash
# Apply all migrations
rem db migrate

# Core infrastructure only (extensions, functions)
rem db migrate --install

# Entity tables only (Resource, Message, etc.)
rem db migrate --models

# Background indexes (HNSW for vectors)
rem db migrate --background-indexes

# Custom connection string
rem db migrate --connection "postgresql://user:pass@host:5432/db"

# Custom SQL directory
rem db migrate --sql-dir /path/to/sql
```

#### `rem db status` - Migration Status

Show applied migrations and execution times.

```bash
rem db status
```

#### `rem db rebuild-cache` - Rebuild KV Cache

Rebuild KV_STORE cache from entity tables (after database restart or bulk imports).

```bash
rem db rebuild-cache
```

### Schema Management

#### `rem db schema generate` - Generate SQL Schema

Generate database schema from Pydantic models.

```bash
# Generate install_models.sql from entity models
rem db schema generate \
  --models src/rem/models/entities \
  --output rem/src/rem/sql/install_models.sql

# Generate migration file
rem db schema generate \
  --models src/rem/models/entities \
  --output rem/src/rem/sql/migrations/003_add_fields.sql
```

#### `rem db schema indexes` - Generate Background Indexes

Generate SQL for background index creation (HNSW for vectors).

```bash
# Generate background_indexes.sql
rem db schema indexes \
  --models src/rem/models/entities \
  --output rem/src/rem/sql/background_indexes.sql
```

#### `rem db schema validate` - Validate Models

Validate Pydantic models for schema generation.

```bash
rem db schema validate --models src/rem/models/entities
```

### File Processing

#### `rem process files` - Process Files

Process files with optional custom extractor (ontology extraction).

```bash
# Process all completed files for tenant
rem process files \
  --tenant-id acme-corp \
  --status completed \
  --limit 10

# Process with custom extractor
rem process files \
  --tenant-id acme-corp \
  --extractor cv-parser-v1 \
  --limit 50

# Process files from the last 7 days
rem process files \
  --tenant-id acme-corp \
  --lookback-hours 168
```

#### `rem process uri` - Process Single URI

Process a single file URI and extract content.

```bash
# Process local file
rem process uri \
  --uri file:///path/to/document.pdf \
  --user-id user-123 \
  --tenant-id acme-corp

# Process S3 file
rem process uri \
  --uri s3://bucket/key.docx \
  --user-id user-123 \
  --tenant-id acme-corp
```

### Memory & Knowledge Extraction (Dreaming)

#### `rem dreaming full` - Complete Workflow

Run full dreaming workflow: extractors → moments → affinity → user model.

```bash
# Full workflow for user
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp

# Skip ontology extractors
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp \
  --skip-extractors

# Process last 24 hours only
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp \
  --lookback-hours 24

# Limit resources processed
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp \
  --limit 100
```

#### `rem dreaming custom` - Custom Extractor

Run specific ontology extractor on user's data.

```bash
# Run CV parser on user's files
rem dreaming custom \
  --user-id user-123 \
  --tenant-id acme-corp \
  --extractor cv-parser-v1

# Process last week's files
rem dreaming custom \
  --user-id user-123 \
  --tenant-id acme-corp \
  --extractor contract-analyzer-v1 \
  --lookback-hours 168 \
  --limit 50
```

#### `rem dreaming moments` - Extract Moments

Extract temporal narratives from resources.

```bash
# Generate moments for user
rem dreaming moments \
  --user-id user-123 \
  --tenant-id acme-corp \
  --limit 50

# Process last 7 days
rem dreaming moments \
  --user-id user-123 \
  --tenant-id acme-corp \
  --lookback-hours 168
```

#### `rem dreaming affinity` - Build Relationships

Build semantic relationships between resources using embeddings.

```bash
# Build affinity graph for user
rem dreaming affinity \
  --user-id user-123 \
  --tenant-id acme-corp \
  --limit 100

# Process recent resources only
rem dreaming affinity \
  --user-id user-123 \
  --tenant-id acme-corp \
  --lookback-hours 24
```

#### `rem dreaming user-model` - Update User Model

Update user model from recent activity (preferences, interests, patterns).

```bash
# Update user model
rem dreaming user-model \
  --user-id user-123 \
  --tenant-id acme-corp
```

### Evaluation & Experiments

#### `rem eval dataset` - Dataset Management

Manage Phoenix evaluation datasets (golden sets).

```bash
# Create dataset from CSV
rem eval dataset create rem-lookup-golden \
  --from-csv golden.csv \
  --input-keys query \
  --output-keys expected_label,expected_type

# Upload to Phoenix
rem eval dataset upload rem-lookup-golden \
  --file dataset.jsonl

# List datasets
rem eval dataset list
```

#### `rem eval experiment` - Run Experiments

Execute evaluation experiments with agents and evaluators.

```bash
# Run experiment on golden set
rem eval experiment run rem-lookup-golden \
  --experiment rem-v1 \
  --agent ask_rem \
  --evaluator rem-lookup-correctness

# Run with custom Phoenix endpoint
rem eval experiment run rem-search-golden \
  --experiment rem-v2 \
  --agent ask_rem \
  --evaluator rem-search-correctness \
  --phoenix-url http://localhost:6006
```

#### `rem eval trace` - Trace Retrieval

Retrieve traces from Phoenix for analysis.

```bash
# Get trace by ID
rem eval trace get trace-abc-123

# List recent traces
rem eval trace list --limit 10
```

#### `rem experiments` - Experiment Config

Manage experiment configurations (A/B testing, parameter sweeps).

```bash
# Create experiment config
rem experiments create \
  --name cv-parser-test \
  --description "Test CV parser with different models"

# List experiments
rem experiments list

# Show experiment details
rem experiments show cv-parser-test

# Run experiment
rem experiments run cv-parser-test
```

### Interactive Agent

#### `rem ask` - Test Agent

Test Pydantic AI agent with natural language queries.

```bash
# Ask a question
rem ask "What documents did Sarah Chen author?"

# With context headers
rem ask "Find all resources about API design" \
  --user-id user-123 \
  --tenant-id acme-corp

# Use specific agent schema
rem ask "Analyze this contract" \
  --agent-schema contract-analyzer-v1
```

### Global Options

All commands support:

```bash
# Verbose logging
rem --verbose <command>
rem -v <command>

# Version
rem --version

# Help
rem --help
rem <command> --help
rem <command> <subcommand> --help
```

### Environment Variables

Override any setting via environment variables:

```bash
# Database
export POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5432/rem
export POSTGRES__POOL_MIN_SIZE=5

# LLM
export LLM__DEFAULT_MODEL=openai:gpt-4o
export LLM__OPENAI_API_KEY=sk-...
export LLM__ANTHROPIC_API_KEY=sk-ant-...

# S3
export S3__BUCKET_NAME=rem-storage
export S3__REGION=us-east-1

# Server
export API__HOST=0.0.0.0
export API__PORT=8000
export API__RELOAD=true

# Run command with overrides
rem serve
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

Migrations are automatically applied on container startup from `src/rem/sql/migrations/*.sql`:
- `001_init_schema.sql` - Core schema with all entity tables and indexes

To add new migrations:
1. Create `src/rem/sql/migrations/002_your_migration.sql`
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
- [x] **RemService** - All query types implemented (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
- [x] **SEARCH Query** - Embedding generation via OpenAI API integrated
- [x] **MCP Tools** - search_rem, ask_rem_agent, ingest_into_rem, read_resource
- [x] **MCP Resources** - Schema docs and status resources registered
- [x] **Models** - All entity models (Resource, Entity, Moment, Message, File, User) complete
- [x] **Settings** - Nested Pydantic settings with environment variable support
- [x] **MCP Server** - FastMCP integration with instructions and mounting patterns
- [x] **Chat Completions** - OpenAI-compatible API (streaming & non-streaming)
- [x] **Agent Factory** - JSON Schema to Pydantic AI conversion
- [x] **File System** - S3 and local providers with format detection
- [x] **Embeddings** - OpenAI embedding generation (sync & async)

### 🚧 In Progress
- [ ] **REM Query Router** - REST endpoint for direct REM query execution
- [ ] **CRUD Routers** - Resource and moment creation/update endpoints
- [ ] **Auth Implementation** - Complete OAuth providers and JWT validation
- [ ] **Tests** - Unit and integration tests for core services
- [ ] **SQL Functions** - PostgreSQL functions (rem_lookup, rem_fuzzy, rem_search, rem_traverse)

### 📝 Design Complete (Stubs Present)
- [ ] **update_graph_edges** - PostgresService method (stub present)
- [ ] **vector_search** - PostgresService method (delegated to RemService)
- [ ] **OAuth routes** - Auth router stubs with redirect handling
- [ ] **OTEL setup** - Conditional instrumentation pattern defined

## License

MIT
