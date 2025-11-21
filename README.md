# REMStack

Cloud-native REM (Resources Entities Moments) system for agentic AI workloads on AWS EKS.

## Stack Components

### Infrastructure
- AWS EKS cluster via Pulumi
- Karpenter for intelligent node provisioning
- Spot instances for stateless workloads
- On-demand instances for stateful workloads

### Platform
- ArgoCD for GitOps continuous delivery
- OpenTelemetry for distributed tracing
- CloudNativePG with PostgreSQL 18 and pgvector
- Arize Phoenix for LLM observability

### Application
- FastAPI server with MCP mounted at `/api/v1/mcp` (not separate)
- Multi-provider OAuth (Google, Microsoft Entra ID, custom)
- Pydantic AI for agent orchestration

**Important**: The MCP (Model Context Protocol) server is not a separate deployment.
It is mounted as part of the rem-api FastAPI application.

## Quickstart with Docker

Get REM running in under 2 minutes with Docker. Two approaches supported:

### Option 1: Standalone Docker (No Installation Required)

Run REM entirely in Docker containers - no local Python installation needed.

```bash
# Clone the repository
git clone https://github.com/your-org/remstack.git
cd remstack/rem

# Set your LLM API keys
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"  # Optional

# Start all services (API, Worker, PostgreSQL)
docker compose up -d

# Wait for services to be healthy (~30 seconds)
docker compose ps

# Use the CLI via docker exec
docker exec rem-api rem db migrate  # Run migrations
docker exec rem-api rem schema list  # List agent schemas
docker exec rem-api rem ask "What is REM?"  # Ask a question

# Process files
docker exec rem-api rem process files --limit 10

# Run dreaming workers (knowledge extraction)
docker exec rem-api rem dreaming full --user-id demo-user --tenant-id demo-tenant
```

**Access the API:**
- REST API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- MCP Server: http://localhost:8000/api/v1/mcp
- Health: http://localhost:8000/health

**Database Access:**
```bash
# Connect to PostgreSQL directly
docker exec -it rem-postgres psql -U rem -d rem

# Run SQL queries
docker exec rem-postgres psql -U rem -d rem -c "SELECT COUNT(*) FROM resources;"
```

### Option 2: Hybrid Approach (Docker + Local pip install)

Use Docker for infrastructure (PostgreSQL) but install the `rem` package locally for faster development iteration.

```bash
# Clone and navigate to the rem package
git clone https://github.com/your-org/remstack.git
cd remstack/rem

# Start PostgreSQL only
docker compose up postgres -d

# Install remdb from PyPI
pip install remdb[all]

# Set environment variables
export ANTHROPIC_API_KEY="your-key-here"
export POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem"
export AUTH__ENABLED="false"
export OTEL__ENABLED="false"

# Run migrations
rem db migrate

# Use CLI directly (much faster than docker exec)
rem schema list
rem ask "What is REM?"
rem process files --limit 10
rem dreaming full --user-id demo-user --tenant-id demo-tenant

# Run API server locally
uvicorn rem.api.main:app --reload --port 8000
```

**Why Hybrid?**
- **Faster CLI**: No `docker exec` overhead
- **Hot Reload**: Code changes reflected immediately
- **Native Debugging**: Use your IDE's debugger directly
- **Isolated DB**: PostgreSQL still containerized with migrations auto-applied

**Connect from Python:**
```python
from rem.services.rem.service import RemService
from rem.agentic.context import AgentContext

# Initialize service (connects to Docker PostgreSQL)
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

### Pulling Pre-Built Images

Instead of building locally, pull from Docker Hub:

```bash
# Pull latest images
docker pull percolationlabs/rem:latest

# Update docker-compose.yml to use pre-built image
# Replace:
#   build:
#     context: .
#     dockerfile: Dockerfile
# With:
#   image: percolationlabs/rem:latest

docker compose up -d
```

### Environment Variables

Configure REM via environment variables in `docker-compose.yml` or `.env` file:

```bash
# LLM Configuration (Required)
LLM__ANTHROPIC_API_KEY=sk-ant-...
LLM__OPENAI_API_KEY=sk-...
LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
LLM__DEFAULT_TEMPERATURE=0.5

# Database (Auto-configured in docker-compose)
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@postgres:5432/rem

# Authentication (Disabled for local dev)
AUTH__ENABLED=false

# Observability (Disabled for local dev)
OTEL__ENABLED=false

# S3 Storage (Optional - for file processing)
S3__BUCKET_NAME=rem-storage
S3__ENDPOINT_URL=http://minio:9000
S3__ACCESS_KEY_ID=minioadmin
S3__SECRET_ACCESS_KEY=minioadmin
```

### Next Steps

After running the quickstart:

1. **Explore the API**: Visit http://localhost:8000/docs for interactive API documentation
2. **Upload Files**: Use the file processing endpoints to upload and process documents
3. **Create Agent Schemas**: Define custom extractors for your domain (CVs, contracts, etc.)
4. **Query with MCP**: Connect Claude Desktop or other MCP clients to http://localhost:8000/api/v1/mcp
5. **Run Evaluations**: Use Arize Phoenix for systematic agent testing (see `rem eval --help`)

## Killer Features

| Feature | Description |
|---------|-------------|
| **Custom Ontology Discovery** | Users/tenants can create custom extractors (JSON Schema agents) to extract domain-specific knowledge from files (CVs, contracts, medical records). Extractors run automatically in background jobs when matching files are uploaded. |

## Key Technologies

- Pydantic 2.0 models for all data structures
- OCI registries for all images and Helm charts
- External Secrets Operator for credential management
- IRSA for AWS permissions
- OpenTelemetry Protocol (OTLP) for observability

## Architecture Layers

```
application/     FastAPI with MCP, auth providers (rem-app namespace)
platform/        ArgoCD, OTel, CloudNativePG, Phoenix
infra/           Pulumi (EKS), Karpenter NodePools
```

## Namespace Structure

- **rem-app**: 2 deployments (rem-api, file-processor)
- **postgres**: PostgreSQL cluster (CloudNativePG)
- **observability**: OpenTelemetry collector (optional, future)

## Design Principles

- Stubs-first development
- Separation of concerns
- No backward compatibility hacks
- DRY code
- Immutable infrastructure
- Schema evolution via Pydantic models

## Deployment Strategy

- OCI Helm charts for platform components
- GitOps via ArgoCD
- Declarative Kubernetes manifests
- No mutable tags in production

## Database

- CloudNativePG operator
- PostgreSQL 18 with pgvector extension
- Vector embeddings for semantic search
- Streaming replication for HA
- No external RDS dependency

## Observability

- OpenTelemetry instrumentation
- Arize Phoenix for LLM tracing
- Structured JSON logging
- Correlation between metrics and traces

## Authentication

- JWT-based authentication
- Multiple OAuth providers
- Token refresh handling
- RBAC integration

## Development Workflow

1. Define Pydantic models
2. Create component stubs
3. Implement incrementally
4. Test with real workloads
5. Deploy via GitOps

## Security

- IRSA for AWS access
- External Secrets for credentials
- Pod Security Standards
- Network policies
- No hardcoded secrets

## Future

- Alembic migrations (when needed)
- Multi-cluster support
- Custom CRDs for REM agents
- Advanced RBAC policies
