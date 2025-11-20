# CLAUDE.md

## Architecture Overview

This is a cloud-native REM (Resources Entities Moments) system for agentic AI workloads built on AWS EKS with modern best practices.

### Application Architecture (3 Namespaces, 2 Deployments)

**Namespaces:**
- `rem-app`: Application components (2 deployments)
- `postgres`: PostgreSQL cluster (deployed separately)
- `observability`: OpenTelemetry collector (optional, future)

**Deployments in rem-app:**
1. **rem-api** (HPA: 2-10 replicas)
   - FastAPI REST and streaming endpoints
   - **MCP server mounted** at `/api/v1/mcp` (not separate)
   - External Secrets for LLM API keys

2. **file-processor** (KEDA: 0-20 replicas)
   - SQS-based autoscaling worker
   - Processes files from S3
   - Spot instances preferred

**Important**: MCP is NOT a separate deployment - it's part of the rem-api FastAPI application.

## Design Principles

- Lean, stubs-first implementation
- Strict separation of concerns: infra/platform/application
- DRY (Don't Repeat Yourself)
- No hacks, no fallbacks
- Pydantic 2.0 models for all data structures
- OCI-based deployments for reproducibility

## Infrastructure Layer (manifests/infra/pulumi/eks-yaml)

### Pulumi YAML Stack
- **Runtime**: Pulumi YAML (no Python virtualenv required)
- **Location**: `manifests/infra/pulumi/eks-yaml/Pulumi.yaml`
- **Single consolidated file**: All infrastructure in one declarative YAML
- Follows AWS EKS best practices guide (2025)

**Note**: This section describes the production-ready architecture with custom VPC and Karpenter.
For a simplified getting-started approach using default VPC and batteries-included `eks:Cluster`,
see `manifests/infra/pulumi/eks-yaml/README.md`.

### EKS Cluster
- **Component**: `eks:Cluster` (proven to work in Pulumi YAML)
- **Version**: 1.32 (configurable)
- **VPC**: Custom VPC with public/private subnets across 3 AZs
- **NAT Gateways**: One per AZ for high availability
- **OIDC Provider**: Automatic creation for IRSA
- **Endpoints**: Both private and public access enabled
- **Logging**: All control plane logs enabled

### Karpenter (Installed via Pulumi)
- **Helm chart**: Installed directly in Pulumi stack using Kubernetes provider
- **IRSA**: IAM role with OIDC web identity federation
- **Interruption handling**: SQS queue + EventBridge rules for Spot/rebalance/health events
- **Node role**: Shared IAM role for all Karpenter-provisioned nodes
- **Namespace**: `karpenter`
- **NodePools**: Applied post-deployment via `kubectl apply -f karpenter-nodepools.yaml`
  - `stateful`: On-demand instances for CloudNativePG
  - `stateless`: Spot instances for API/MCP workloads
  - `gpu`: GPU instances for future ML inference
- **EC2NodeClass**: AL2023 EKS-optimized AMI, GP3 volumes, IMDSv2 required
- **Consolidation**: WhenEmptyOrUnderutilized for cost optimization

## Platform Layer (manifests/platform)

### ArgoCD
- GitOps continuous delivery
- OCI Helm chart repository pattern
- enableOCI: true for all registries
- External Secrets Operator for credential management
- Umbrella chart pattern for complex deployments
- Latest stable image from OCI registry

### OpenTelemetry (OTel)
- Distributed tracing and observability backbone
- OpenTelemetry Collector deployment
- OTLP protocol for trace ingestion
- Integration with Arize Phoenix

### CloudNativePG
- PostgreSQL 18 with pgvector extension
- Immutable extension pattern using ImageVolumes (K8s 1.33+)
- extension_control_path for extension management
- Vector embeddings for AI workloads
- Backup/restore strategy
- High availability with streaming replication

### Arize Phoenix
- LLM observability and evaluation platform
- OpenTelemetry-based tracing (OpenInference conventions)
- Framework-agnostic instrumentation
- OTLP endpoint for trace collection
- Latest Phoenix image from OCI

## Application Layer (manifests/application/rem-stack)

### rem-api (Deployment)
- **FastAPI server** with REST and streaming endpoints
- **FastMCP server mounted** at `/api/v1/mcp` (not a separate deployment)
- Pydantic AI integration
- Pydantic 2.0 request/response models
- JWT-based authentication (OAuth providers)
- OpenTelemetry instrumentation (conditional)
- No Alembic migrations (schema evolution via models only)
- HPA: 2-10 replicas (CPU-based)
- External Secrets for LLM API keys

### file-processor (Deployment)
- **KEDA-scaled worker** (0-20 replicas based on SQS queue depth)
- Background file processing (S3 → process → S3)
- Pod Identity/IRSA for AWS access
- Spot instances preferred (cost optimization)
- Pod anti-affinity for distribution

## REM System Architecture

### Resources Entities Moments

REM is a bio-inspired memory architecture mirroring human memory systems:

**Resources**: Chunked, embedded content from documents, files, conversations
- Semantic searchable via vector embeddings (pgvector)
- Stored with metadata: source URI, timestamp, tenant, hash
- Contains `related_entities` (extracted entity references)
- Contains `graph_paths` (InlineEdge objects for knowledge graph)

**Entities**: Domain knowledge nodes with properties and relationships
- Natural language labels as identifiers (e.g., "sarah-chen", "tidb-migration-spec")
- NOT UUIDs - enables conversational queries without internal ID knowledge
- Entity types: person, project, technology, concept, document
- Graph edges stored inline using InlineEdge pattern
- Flexible properties stored as JSONB

**Moments**: Temporal narratives and time-bound events
- Time-indexed classifications of resources and entities
- Enable chronological memory retrieval
- Store temporal boundaries (start/end timestamps)
- Present persons, speakers, emotion tags, topic tags
- Reference resources and entities (does not duplicate)

**Core Design Principles**:
- Multi-index organization for different retrieval patterns
- Iterated retrieval: LLMs conduct multi-turn database conversations
- Hybrid storage: vectors + graph + time indexes + key-value
- Human-readable entity labels (not UUIDs) for natural language queries
- Tenant-scoped: complete data isolation per tenant

**REM Query Language**: Custom dialect for flexible retrieval
- `LOOKUP`: O(1) lookup by entity label
- `SEARCH`: Semantic search across entity types (vector-based)
- `TRAVERSE`: Graph traversal with depth control (follows InlineEdge relationships)
- `SQL`: Direct SQL queries for temporal/structured queries
- Supports predicate-based filtering and complex queries

**Memory Evolution Through Dreaming**:
- Stage 0: Raw resources only (0% answerable)
- Stage 1: Entity extraction complete (20% answerable, LOOKUP works)
- Stage 2: Moments generated (50% answerable, temporal queries work)
- Stage 3: Affinity matching complete (80% answerable, semantic/graph queries work)
- Stage 4: Multiple dreaming cycles (100% answerable, full query capabilities)

## Core Design Patterns (rem/src/rem/)

### 1. Nested Pydantic Settings Pattern (settings.py)
- Environment variables with double underscore delimiter (`LLM__DEFAULT_MODEL`)
- Nested settings groups by domain (LLM, MCP, OTEL, Auth, Postgres, S3)
- Sensible defaults (auth disabled, OTEL disabled for local dev)
- Global singleton for easy import
- Documentation of all environment variables in docstrings

### 2. Header to Context Mapping Pattern (agentic/context.py)
- HTTP headers automatically map to AgentContext fields
- `X-User-Id` → `context.user_id`
- `X-Tenant-Id` → `context.tenant_id` (REM multi-tenancy)
- `X-Session-Id` → `context.session_id`
- `X-Agent-Schema` → `context.agent_schema_uri`
- Case-insensitive header lookup
- Support for both HTTP (via headers) and programmatic (direct instantiation) usage
- AgentContext passed to agent factory, NOT stored in agent

### 3. Agent Query Structure Pattern (agentic/query.py)
- Standardized query/knowledge/scratchpad structure
- `query`: User's question or task
- `knowledge`: Retrieved context from REM queries
- `scratchpad`: Working memory for multi-turn reasoning
- Supports markdown + fenced JSON for structured data
- Converts to single prompt string for agent consumption

### 4. JsonSchema to Pydantic Pattern (agentic/providers/pydantic_ai.py)
- Agent schemas are JSON Schema with embedded metadata
- `description` field becomes system prompt
- `properties` field becomes Pydantic output model
- `json_schema_extra.tools` specifies MCP tools to load
- `json_schema_extra.resources` specifies MCP resources
- Dynamic model creation using `json-schema-to-pydantic` library
- Enables external schema definition (versioned, shareable)

### 5. Schema Description Stripping Pattern (agentic/providers/pydantic_ai.py)
- Remove model-level description from LLM schema
- Agent schema description already in system prompt
- Prevents duplication and reduces token usage
- Keep docstrings in Python code for documentation
- Only strip model-level description, keep field descriptions

### 6. Streaming with agent.iter() Pattern (api/routers/chat/streaming.py)
- Use `agent.iter()` for complete execution (not `run_stream()`)
- `agent.iter()` captures tool calls, `run_stream()` stops after first output
- Stream tool call events with `[Calling: tool_name]` markers
- Stream text content deltas as they arrive
- OpenAI SSE format: `data: {json}\n\n` with `[DONE]` terminator
- Error handling with graceful degradation

### 7. OpenAI-Compatible Chat Completions (api/routers/chat/)
- Full OpenAI `/v1/chat/completions` compatibility
- Streaming and non-streaming modes
- Response format control (text vs json_object)
- Best-effort JSON extraction with multiple fallback strategies
- Model specified in `body.model` (standard OpenAI field)
- Headers provide session context, body provides request data

### 8. Stateless MCP Mounting Pattern (api/main.py)
- FastMCP with `stateless_http=True` for Kubernetes
- Prevents stale session errors across pod restarts
- Mount at `/api/v1/mcp` for consistency
- Path rewrite middleware for trailing slash handling
- Combined lifespan management (app + MCP)
- `redirect_slashes=False` prevents auth header stripping

### 9. Middleware Ordering Pattern (api/main.py)
- Middleware runs in reverse order of addition
- CORS added LAST (runs FIRST) - adds headers to all responses
- Auth middleware before logging
- Logging middleware before sessions
- Sessions middleware added first (runs last)
- Critical: CORS must run before auth to add headers to 401/403 responses

### 10. Conditional OTEL Instrumentation (settings.py, providers/pydantic_ai.py)
- OTEL disabled by default for local development
- Enabled in production via `OTEL__ENABLED=true` environment variable
- Applied at agent creation time: `Agent(..., instrument=settings.otel.enabled)`
- Prevents trace spam during local testing
- Clean integration with Pydantic AI's built-in OTEL support

### 11. Pydantic Serialization Pattern (agentic/serialization.py)
**CRITICAL: Always serialize Pydantic models before returning from MCP tools or API endpoints**

When agent results contain Pydantic model instances (e.g., `result.output` or `result.data`), they MUST be explicitly serialized using `.model_dump()` or `.model_dump_json()` before returning. Frameworks like FastMCP and FastAPI may use their own serialization logic that silently drops fields from unserialized Pydantic models.

**Anti-Pattern (causes field loss):**
```python
# ❌ BAD: Returns Pydantic model directly
return {
    "status": "success",
    "response": result.output,  # Pydantic model instance - fields may be lost!
}
```

**Correct Pattern:**
```python
# ✅ GOOD: Explicitly serialize first
return {
    "status": "success",
    "response": result.output.model_dump(),  # Serialized dict - all fields preserved
}
```

**Helper utilities:**
- `serialize_agent_result(result)` - Returns dict or primitive, handles Pydantic models
- `serialize_agent_result_json(result)` - Returns JSON string (for SSE, API responses)
- `is_pydantic_model(obj)` - Check if object is Pydantic model
- `safe_serialize_dict(data)` - Recursively serialize nested Pydantic models

**Where to apply:**
- MCP tool return values (tools.py)
- Service layer methods called by MCP tools (services/rem/service.py)
- API endpoint responses (api/routers/*)
- SSE streaming events (api/routers/chat/streaming.py)
- Any context where data crosses serialization boundary

**Examples:**
```python
# Service layer (already correct)
async def ask_rem(query: str) -> dict[str, Any]:
    result = await agent.run(query)
    return {
        "query_output": result.data.model_dump(),  # ✅ Serialized
        "natural_query": query,
    }

# MCP tool
async def ask_rem_tool(query: str) -> dict[str, Any]:
    result = await service.ask_rem(query)
    return result  # ✅ Already serialized by service layer

# API endpoint with Pydantic check
if hasattr(result.output, "model_dump_json"):
    content = result.output.model_dump_json()  # ✅ Serialized
else:
    content = str(result.output)

# SSE streaming
chunk = ChatCompletionStreamResponse(...)
yield f"data: {chunk.model_dump_json()}\n\n"  # ✅ Serialized
```

## REM-Specific Patterns

### REM Query System (models/core/rem_query.py)
- Schema-agnostic queries (LOOKUP, FUZZY, TRAVERSE)
- Natural language labels instead of UUIDs
- Performance contracts (O(1) for LOOKUP, indexed for SEARCH)
- Multi-turn iterated retrieval pattern
- Plan memos for agent scratchpad across turns

### Graph Edge Pattern (models/core/inline_edge.py)
- Human-readable destination labels (not UUIDs)
- `dst` field contains entity labels (e.g., "sarah-chen", "api-design-v2")
- Edge weights (1.0 = primary, 0.8-0.9 = important, 0.5-0.7 = secondary)
- Rich metadata in properties dict
- Enables conversational queries without internal ID knowledge

### Entity Model Pattern (models/entities/)
- All entities inherit from CoreModel
- System fields (inherited from CoreModel):
  - Identity: `id` (UUID or string, generated per model type)
  - Temporal tracking: `created_at`, `updated_at`, `deleted_at`
  - Multi-tenancy: `tenant_id` (optional, system-level field)
  - Ownership: `user_id` (optional, tenant-scoped)
  - Graph connectivity: `graph_edges` (list of InlineEdge dicts)
  - Flexible metadata: `metadata` (dict), `tags` (list)
  - Database schema: `column` (dict for schema metadata)
- Entity-specific fields defined in each model (Resource, Message, User, File, Moment)
- No duplicate tenant_id or system fields in child models

## Technology Decisions

### OCI Registry Strategy
- All platform components use OCI Helm charts
- Application containers from OCI registries
- Version pinning via image tags
- No mutable 'latest' tags in production

### No ALB Controller
- Alternative ingress approach (to be defined)
- Cost optimization
- Simplified architecture

### Database Strategy
- CloudNativePG as operator
- No external RDS dependency
- pgvector for semantic search
- PostgreSQL 18 for latest features

### Observability
- OpenTelemetry as instrumentation standard
- Arize Phoenix for LLM-specific observability
- Structured logging (JSON)
- Metrics and traces correlation

## Development Workflow

1. Define Pydantic models first
2. Create stubs for all components
3. Implement incrementally
4. No backward compatibility hacks
5. Delete unused code completely

## Security

- IRSA (IAM Roles for Service Accounts) for AWS access
- External Secrets Operator for secret management
- No hardcoded credentials
- Pod Security Standards enforcement
- Network policies for isolation

## Deployment

Quick deployment guide for the complete stack:

### Prerequisites
```bash
export AWS_PROFILE=rem
export PULUMI_CONFIG_PASSPHRASE="your-passphrase"
```

### 1. Infrastructure (~25-30 min)
See [manifests/infra/eks-yaml/README.md](manifests/infra/eks-yaml/README.md)
```bash
cd manifests/infra/eks-yaml
pulumi up
kubectl apply -f karpenter-nodepools.yaml
```

### 2. Platform (~10-15 min)
See [manifests/platform/README.md](manifests/platform/README.md)
```bash
kubectl apply -k manifests/platform/argocd/
kubectl apply -f manifests/platform/argocd/app-of-apps.yaml
```

### 3. Applications (~5-10 min)
See [manifests/application/README.md](manifests/application/README.md)
```bash
kubectl apply -f manifests/application/rem-api/argocd-application.yaml
kubectl apply -f manifests/application/rem-mcp/argocd-application.yaml
```

## Future Considerations

- Alembic migrations (only when schema complexity requires it)
- Multi-cluster federation
- Advanced RBAC policies
- Custom CRDs for REM agents
