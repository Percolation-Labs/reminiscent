# REMStack

Cloud-native REM (Resources Entities Moments) system for agentic AI workloads on AWS EKS.

## What is REM?

REM is a **unified memory infrastructure** for AI agents that combines:
- **Multi-index database**: PostgreSQL with KV store + vector search + graph traversal + temporal queries
- **Custom query dialect**: O(1) lookups, semantic search, graph exploration with formal grammar
- **Progressive enrichment**: Background "dreaming" workers that build knowledge graphs from raw data (0% → 100% answerable)
- **No-code agents**: JSON Schema-based agent definitions with Pydantic AI runtime
- **Production-ready APIs**: OpenAI-compatible chat completions + MCP server for Claude Desktop/Cursor
- **Built-in observability**: OpenTelemetry tracing + Arize Phoenix + LLM-as-a-Judge evaluation framework

See [rem/README.md](rem/README.md) for complete Python package documentation.

## Quick Start (2 minutes)

### Option 1: Docker Compose (Recommended for Testing)

```bash
# Clone and start
git clone https://github.com/your-org/remstack.git
cd remstack/rem
export ANTHROPIC_API_KEY="sk-ant-..."
docker compose up -d

# Verify it's running
curl http://localhost:8000/health
```

**Access:**
- REST API: http://localhost:8000/docs
- MCP Server: http://localhost:8000/api/v1/mcp
- PostgreSQL: `localhost:5050` (rem/rem)

### Option 2: PyPI Install 

```bash
# Install
pip install remdb[all]

# Configure (interactive wizard)
rem configure --install --claude-desktop

# Start services
rem serve
```

See [rem/README.md](rem/README.md) for detailed installation and usage.

## Architecture

```mermaid
graph TD
    API[FastAPI<br/>Chat + MCP] --> AGENTS[JSON Schema<br/>Agents]
    AGENTS --> TOOLS[MCP Tools<br/>5 Tools]

    TOOLS --> QUERY[REM Query<br/>Dialect]
    QUERY --> DB[(PostgreSQL<br/>+pgvector)]

    FILES[File Processor] --> DREAM[Dreaming<br/>Workers]
    DREAM --> DB

    AGENTS --> OTEL[OpenTelemetry]
    OTEL --> PHOENIX[Arize<br/>Phoenix]

    EVAL[Evaluation<br/>Framework] --> PHOENIX

    classDef api fill:#4A90E2,stroke:#2E5C8A,color:#fff
    classDef agent fill:#7B68EE,stroke:#483D8B,color:#fff
    classDef db fill:#50C878,stroke:#2E7D4E,color:#fff
    classDef obs fill:#9B59B6,stroke:#6C3483,color:#fff

    class API,TOOLS api
    class AGENTS agent
    class DB,QUERY db
    class OTEL,PHOENIX,EVAL obs
```

**Key Components:**

- **API Layer**: OpenAI-compatible chat completions + MCP server (mounted, not separate)
- **Agentic Framework**: JSON Schema-based agents with no-code configuration
- **Database Layer**: PostgreSQL 18 with pgvector for multi-index memory (KV + Vector + Graph)
- **REM Query Dialect**: Custom query language with O(1) lookups, semantic search, graph traversal
- **Ingestion & Dreaming**: Background workers for content extraction and progressive index enrichment (0% → 100% answerable)
- **Observability & Evals**: OpenTelemetry tracing + Arize Phoenix + LLM-as-a-Judge evaluation framework

## Repository Structure

```
remstack/
├── rem/                    # Python package (PyPI: remdb)
│   ├── src/rem/           # Source code
│   ├── tests/             # Integration tests
│   ├── docker-compose.yml # Local development
│   └── README.md          # Package documentation
├── manifests/             # Kubernetes deployment
│   ├── infra/            # Pulumi EKS infrastructure
│   ├── platform/         # ArgoCD, CloudNativePG, Phoenix
│   └── application/      # REM application manifests
└── README.md             # This file
```

## Documentation

- **Python Package**: [rem/README.md](rem/README.md) - Installation, CLI, API, development
- **Infrastructure**: [manifests/infra/pulumi/eks-yaml/README.md](manifests/infra/pulumi/eks-yaml/README.md) - EKS cluster with Karpenter
- **Platform**: [manifests/platform/README.md](manifests/platform/README.md) - ArgoCD, CloudNativePG, Phoenix
- **Application**: [manifests/application/README.md](manifests/application/README.md) - Kubernetes deployment
- **Database**: [rem/src/rem/services/postgres/README.md](rem/src/rem/services/postgres/README.md) - Schema, migrations, queries
- **Evaluation**: [rem/src/rem/services/phoenix/README.md](rem/src/rem/services/phoenix/README.md) - Testing and evaluation

## Development

### Local Development (Hybrid)

```bash
# Start PostgreSQL
cd rem
docker compose up postgres -d

# Install package
pip install -e ".[dev]"

# Run migrations
rem db migrate

# Start API server (hot reload)
uvicorn rem.api.main:app --reload

# Run tests
pytest tests/integration/
```

### Docker Development

```bash
# Build and run everything
cd rem
docker compose up --build

# View logs
docker compose logs -f api

# Run CLI commands
docker exec rem-api rem db migrate
docker exec rem-api rem ask "What is REM?"
```

## Deployment

### Prerequisites

- AWS Account with credentials configured
- kubectl installed
- Pulumi CLI installed

### Deploy to AWS EKS

```bash
# 1. Deploy infrastructure (~25-30 min)
cd manifests/infra/pulumi/eks-yaml
pulumi up
kubectl apply -f karpenter-nodepools.yaml

# 2. Deploy platform (~10-15 min)
kubectl apply -k manifests/platform/argocd/
kubectl apply -f manifests/platform/argocd/app-of-apps.yaml

# 3. Deploy application (~5-10 min)
kubectl apply -f manifests/application/rem-api/argocd-application.yaml
```

See infrastructure README for detailed deployment guide.

## Core Design Patterns

REM implements battle-tested patterns for building production AI systems. See [CLAUDE.md](CLAUDE.md) for complete pattern documentation.

### Configuration & Settings

**Nested Pydantic Settings** (`rem/src/rem/settings.py`)
- Environment variables with double underscore delimiter (`LLM__DEFAULT_MODEL`)
- Nested settings groups by domain (LLM, MCP, OTEL, Auth, Postgres, S3)
- Automatic fallback from `LLM__*_API_KEY` to unprefixed env vars for provider compatibility
- Global singleton with sensible defaults
```python
from rem.settings import settings
api_key = settings.llm.anthropic_api_key  # Reads LLM__ANTHROPIC_API_KEY or ANTHROPIC_API_KEY
```

### Agent & API Patterns

**Header to Context Mapping** (`rem/src/rem/agentic/context.py`)
- HTTP headers automatically map to AgentContext: `X-User-Id` → `context.user_id`
- Case-insensitive header lookup with backward compatibility
- Supports both HTTP (headers) and programmatic (direct instantiation) usage

**JsonSchema to Pydantic** (`rem/src/rem/agentic/providers/pydantic_ai.py`)
- Agent schemas as JSON Schema with embedded metadata
- `description` → system prompt, `properties` → Pydantic model
- Dynamic model creation enables external schema definition (versioned, shareable)

**Streaming with agent.iter()** (`rem/src/rem/api/routers/chat/streaming.py`)
- Use `agent.iter()` for complete execution (captures tool calls)
- OpenAI SSE format: `data: {json}\n\n` with `[DONE]` terminator
- Stream tool call events with `[Calling: tool_name]` markers

**Pydantic Serialization** (`rem/src/rem/agentic/serialization.py`)
- **CRITICAL**: Always serialize Pydantic models before returning from MCP tools or API endpoints
- Use `.model_dump()` or `.model_dump_json()` to prevent field loss
```python
# ✅ CORRECT
return {"response": result.output.model_dump()}

# ❌ WRONG - fields may be silently dropped
return {"response": result.output}
```

### Infrastructure Patterns

**Stateless MCP Mounting** (`rem/src/rem/api/main.py`)
- FastMCP with `stateless_http=True` for Kubernetes (prevents stale sessions across pod restarts)
- Mount at `/api/v1/mcp`, combined lifespan management

**Middleware Ordering** (`rem/src/rem/api/main.py`)
- Middleware runs in reverse order of addition
- CORS added LAST (runs FIRST) - critical for auth headers on 401/403 responses

**Conditional OTEL Instrumentation** (`rem/src/rem/settings.py`)
- OTEL disabled by default for local development
- Enable in production: `OTEL__ENABLED=true`
- Applied at agent creation: `Agent(..., instrument=settings.otel.enabled)`

### Data Patterns

**Agentic Chunking** (`rem/src/rem/utils/agentic_chunking.py`)
- Handle inputs exceeding model context windows (128K for GPT-4o, 200K for Claude)
- Smart chunking with line/word boundary preservation
- Configurable merge strategies: CONCATENATE_LIST, MERGE_JSON, LLM_MERGE
```python
from rem.utils.agentic_chunking import chunk_text, merge_results, MergeStrategy

chunks = chunk_text(large_text, max_tokens=100000, model="gpt-4o")
results = [await agent.run(chunk) for chunk in chunks]
merged = merge_results([r.output.model_dump() for r in results], strategy=MergeStrategy.CONCATENATE_LIST)
```

**Graph Edge Pattern** (`rem/src/rem/models/core/inline_edge.py`)
- Human-readable destination labels (not UUIDs): `"sarah-chen"`, `"api-design-v2"`
- Edge weights: 1.0 = primary, 0.8-0.9 = important, 0.5-0.7 = secondary
- Rich metadata in properties dict enables conversational queries

**Entity Model Pattern** (`rem/src/rem/models/entities/`)
- All entities inherit from CoreModel with system fields: `id`, `created_at`, `user_id`, `graph_edges`, `metadata`, `tags`
- Data scoping by `user_id` for complete isolation
- No duplicate system fields in child models

### Database Patterns

**Repository Pattern** (`rem/src/rem/services/postgres/repository.py`)
- Generic repository with type-safe CRUD operations
- Automatic `user_id` filtering for data isolation
```python
from rem.services.postgres.repository import Repository
from rem.models.entities import Resource

repo = Repository(Resource, "resources", db)
resources = await repo.get_by_user_id("user-123", limit=10)
```

**Service Factory Pattern** (`rem/src/rem/services/postgres/__init__.py`)
- **ALWAYS** use `get_postgres_service()` factory function
- **NEVER** instantiate `PostgresService()` directly
- Factory handles connection pooling, lifecycle management, configuration

## Design Principles

- **Lean implementation**: Stubs-first, no premature optimization
- **Strict separation**: Infrastructure / Platform / Application
- **DRY code**: Single source of truth for all configurations
- **No vendor lock-in**: Raw HTTP clients, swappable providers, open standards
- **Provider-agnostic**: Switch LLM providers, embeddings, observability backends via env vars

## Technology Stack

### Core
- **Python 3.12+**: Pydantic 2.0, FastAPI, Pydantic AI
- **Database**: PostgreSQL 18 with pgvector extension
- **MCP**: FastMCP for Model Context Protocol integration

### Infrastructure
- **Cloud**: AWS EKS (Elastic Kubernetes Service)
- **IaC**: Pulumi YAML (no Python virtualenv required)
- **Autoscaling**: Karpenter for intelligent node provisioning

### Platform
- **GitOps**: ArgoCD for continuous delivery
- **Database Operator**: CloudNativePG for PostgreSQL management
- **Observability**: OpenTelemetry + Arize Phoenix for LLM tracing

## Developers

### Running Tests
Run the integration test suite to verify changes:
```bash
cd rem
pytest tests/integration/
```

### Type Checking
Run the type checker to catch schema and type-related issues:
```bash
./scripts/check_types.sh
```
Alternatively, run mypy directly:
```bash
cd rem
mypy src/rem
```
