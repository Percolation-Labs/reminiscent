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

### 11. Agentic Chunking Pattern (utils/agentic_chunking.py)
**Purpose**: Handle large inputs that exceed model context windows by splitting, processing chunks independently, and merging results.

**When to use**:
- Input data exceeds model context limit (e.g., 128K tokens for GPT-4o, 200K for Claude)
- Processing large documents, datasets, or session histories
- Need to respect rate limits while processing multiple chunks

**Key Components**:
- `get_model_limits(model)` - Returns ModelLimits for any model (OpenAI, Anthropic, Google)
- `estimate_tokens(text, model)` - Uses tiktoken for OpenAI (exact), heuristic for others
- `chunk_text(text, max_tokens, model)` - Smart chunking with line/word boundary preservation
- `merge_results(results, strategy)` - Merge chunk results using configurable strategies

**Merge Strategies**:
1. `CONCATENATE_LIST` (default) - Merge lists, update dicts, keep first scalar
2. `MERGE_JSON` - Deep recursive merge of JSON objects
3. `LLM_MERGE` - Use LLM to intelligently merge results (TODO)

**Usage**:
```python
from rem.utils.agentic_chunking import chunk_text, merge_results, MergeStrategy, get_model_limits

# Get model limits
limits = get_model_limits("gpt-4o")
max_input_tokens = limits.max_input  # 111616 tokens

# Chunk large input (with buffer for system prompt overhead)
chunks = chunk_text(large_text, max_tokens=100000, model="gpt-4o")

# Process each chunk with agent
results = []
for chunk in chunks:
    result = await agent.run(chunk)
    results.append(result.output.model_dump())  # Serialize Pydantic models!

# Merge results
merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)
```

**Design Principles**:
- Tiktoken for exact token counting on OpenAI models
- Character-based heuristic (4 chars/token) fallback for other providers
- Line boundary preservation to avoid splitting mid-sentence
- Word boundary fallback for character chunking
- Conservative buffer ratios (75-80%) for safety
- Composable: works with any agent execution pattern

### 12. Pydantic Serialization Pattern (agentic/serialization.py)
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
- Entity-specific fields defined in each model (Resource, Message, User, File, Moment, Ontology)
- No duplicate tenant_id or system fields in child models

### Ontology Extraction Pattern (models/entities/ontology.py, services/ontology_extractor.py)

**Purpose**: Extract domain-specific structured knowledge from files using custom agent schemas.

**Architecture**:
1. **Ontology Entity**: Stores extracted structured data
   - Links to source File via `file_id`
   - Tracks agent schema used via `agent_schema_id`
   - Contains arbitrary structured data in `extracted_data` (dict)
   - Supports semantic search via `embedding_text` field
   - Records LLM provider and model used
   - Includes optional `confidence_score` (0.0-1.0)

2. **OntologyConfig Entity**: User-defined extraction rules
   - File matching via MIME type patterns, URI patterns, or tags
   - Multiple configs can match a single file (all will be applied)
   - Priority field controls execution order
   - Optional provider/model overrides per config
   - Enabled/disabled toggle for temporary deactivation

3. **Agent Schema Enhancements**:
   - `provider_configs`: Multi-provider testing (Anthropic, OpenAI, etc.)
   - `embedding_fields`: JSON paths to embed for semantic search
   - `category`: "ontology-extractor" tag for discovery

4. **Extraction Logic (in dreaming worker)**:
   - No separate service - uses existing agent factory
   - Loads schemas from database dynamically
   - Runs agent using `create_pydantic_ai_agent()`
   - Extracts embedding text using `utils/dict_utils.py`
   - Generates embeddings using `utils/embeddings.py`
   - Stores Ontology via repository

5. **Dreaming Worker Integration**:
   - New `extract_ontologies()` operation
   - Runs FIRST in `process_full()` workflow (before moments)
   - Finds files with `processing_status='completed'`
   - Applies matching OntologyConfig rules
   - Executes agents and stores results

**Example Use Cases**:
- **Recruitment**: Parse CVs to extract candidate skills, experience, education
  - Schema: `cv-parser-v1.yaml`
  - Extracted fields: candidate_name, skills, experience, education, seniority_level
  - Embedding fields: candidate_name, professional_summary, skills, experience

- **Legal**: Analyze contracts to extract parties, obligations, financial terms
  - Schema: `contract-analyzer-v1.yaml`
  - Extracted fields: contract_type, parties, financial_terms, key_obligations, risk_flags
  - Embedding fields: contract_title, contract_type, parties, key_obligations, risk_flags

- **Medical**: Extract diagnoses, medications, treatments from health records
- **Financial**: Parse reports to extract metrics, risks, forecasts

**Schema Structure**:
```yaml
---
type: object
description: |
  System prompt with LLM instructions for extraction.

properties:
  # JSON Schema defining structured output
  field_name:
    type: string
    description: Field description

required:
  - required_fields

json_schema_extra:
  fully_qualified_name: rem.agents.MyExtractorAgent
  version: "1.0.0"
  tags: [domain, ontology-extractor]

  # Ontology-specific configuration
  provider_configs:
    - provider_name: anthropic
      model_name: claude-sonnet-4-5-20250929
    - provider_name: openai
      model_name: gpt-4o

  embedding_fields:
    - field1
    - field2
    - nested.field3
```

**Workflow**:
1. User creates agent schema (stored in `schemas` table)
2. User creates OntologyConfig with file matching rules
3. Files uploaded to S3, File entities created
4. File processor extracts content, updates status to `completed`
5. Dreaming worker finds completed files
6. For each file, loads matching OntologyConfigs (sorted by priority)
7. For each config:
   - Loads agent schema from database
   - Creates agent using `create_pydantic_ai_agent()`
   - Runs agent on file content
   - Serializes extracted data (critical for Pydantic models!)
   - Generates embedding text from configured fields
   - Stores Ontology entity
8. Ontologies queryable via LOOKUP, SEARCH, or direct queries

**CLI Commands**:
```bash
# Run custom extractor on user's data (resources, files, sessions)
rem dreaming custom \
  --user-id user-123 \
  --tenant-id acme-corp \
  --extractor cv-parser-v1

# Run extractor with lookback window
rem dreaming custom \
  --user-id user-123 \
  --tenant-id acme-corp \
  --extractor contract-analyzer-v1 \
  --lookback-hours 168 \
  --limit 50

# Process files through extractor
rem process files \
  --tenant-id acme-corp \
  --extractor cv-parser-v1 \
  --status completed \
  --limit 10

# Full dreaming workflow (includes extractors if configs exist)
rem dreaming full --user-id user-123 --tenant-id acme-corp

# Skip extractors in full workflow
rem dreaming full --user-id user-123 --tenant-id acme-corp --skip-extractors
```

**Key Design Principles**:
- **Schema-driven**: Agent schemas in database, not hardcoded
- **Provider-agnostic**: Test across multiple LLM providers
- **Embedding-aware**: Automatically embeds configured fields
- **Tenant-isolated**: All operations scoped to tenant_id
- **Serialization-safe**: Always serialize Pydantic models (critical!)
- **Cost-conscious**: Optional provider configs for A/B testing

**Files**:
- `models/entities/ontology.py` - Ontology entity model
- `models/entities/ontology_config.py` - OntologyConfig entity model
- `models/entities/schema.py` - Enhanced with provider_configs, embedding_fields
- `services/repositories/ontology_repository.py` - Ontology CRUD operations
- `services/repositories/ontology_config_repository.py` - Config CRUD and file matching
- `workers/dreaming.py` - Contains extraction logic in `extract_ontologies()`
- `utils/dict_utils.py` - Nested dict access and field extraction for embeddings
- `utils/embeddings.py` - Embedding generation (reused)
- `agentic/serialization.py` - Pydantic serialization (reused)
- `cli/commands/dreaming.py` - Dreaming commands including `custom` for extractors
- `cli/commands/process.py` - Process commands with `--extractor` option
- `schemas/ontology_extractors/` - Example agent schemas (CV parser, contract analyzer)

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

## Evaluation Framework

REM includes a **two-phase evaluation system** using Arize Phoenix for systematic agent testing.

### Architecture

**Phase 1: SME Golden Set Creation**
- Subject Matter Experts create datasets with (input, reference) pairs
- No agent execution required
- Stored in Phoenix for reuse

**Phase 2: Automated Evaluation**
- Run agents on golden sets → produces outputs
- Run evaluators (LLM-as-a-Judge) → produces scores
- Track results in Phoenix for analysis over time

### Components

**Services** (`rem/src/rem/services/phoenix/`)
- `PhoenixClient`: Dataset management, experiment execution, trace retrieval
- `PhoenixConfig`: Connection configuration

**Providers** (`rem/src/rem/agentic/providers/phoenix.py`)
- Evaluator factory (mirrors Pydantic AI pattern)
- Schema-based LLM-as-a-Judge evaluators
- Support for Anthropic and OpenAI models

**Evaluator Schemas** (`rem/schemas/evaluators/`)
- `rem-lookup-correctness.yaml`: LOOKUP query evaluation
- `rem-search-correctness.yaml`: SEARCH query evaluation
- Multi-dimensional scoring (correctness, completeness, performance)

**CLI Commands**
```bash
# Create golden set from CSV
rem eval dataset create rem-lookup-golden \
  --from-csv golden.csv \
  --input-keys query \
  --output-keys expected_label,expected_type

# Run evaluation
rem eval experiment run rem-lookup-golden \
  --experiment rem-v1 \
  --agent ask_rem \
  --evaluator rem-lookup-correctness

# View results
open http://localhost:6006
```

### Future: RAGAS and RRF

**RAGAS Integration (Q1 2025)**
- Evaluate RAG retrieval quality independently from agents
- Metrics: Context Precision, Context Recall, Faithfulness, Answer Relevance
- Focus on REM query layer as retrieval gateway

**RRF Experiments (Q2 2025)**
- Reciprocal Rank Fusion for hybrid retrieval
- Combine SEARCH (semantic) + LOOKUP (exact) results
- Improve coverage and ranking quality

**Why This Matters:**
REM is fundamentally a RAG system. The query layer (LOOKUP, SEARCH, TRAVERSE, SQL) is the retrieval gateway. RAGAS and RRF allow us to evaluate and optimize retrieval in isolation from agent behavior - critical because if retrieval fails, agents fail.

See [rem/src/rem/services/phoenix/README.md](rem/src/rem/services/phoenix/README.md) for complete documentation.

---

## Future Considerations

- Alembic migrations (only when schema complexity requires it)
- Multi-cluster federation
- Advanced RBAC policies
- Custom CRDs for REM agents
