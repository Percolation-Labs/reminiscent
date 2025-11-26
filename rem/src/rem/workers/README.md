# REM Dreaming Worker

Background worker for building the REM knowledge graph through memory indexing and insight extraction.

## Overview

The dreaming worker processes user content to construct the REM knowledge graph through four core operations:

1. **Ontology Extraction**: Run custom extractors on files/resources for domain-specific knowledge
2. **User Model Updates**: Extract and update user profiles from activity
3. **Moment Construction**: Identify temporal narratives from resources
4. **Resource Affinity**: Build semantic relationships between resources

```
┌─────────────────────────────────────────────────────────────┐
│                    Dreaming Worker                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  │
│  │   User Model  │  │    Moment     │  │   Resource    │  │
│  │   Updater     │  │  Constructor  │  │   Affinity    │  │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘  │
│          │                  │                  │          │
│          └──────────────────┼──────────────────┘          │
│                            │                              │
│                    ┌───────▼───────┐                      │
│                    │  REM Services │                      │
│                    │  - Repository │                      │
│                    │  - Query      │                      │
│                    │  - Embedding  │                      │
│                    └───────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

## Design Philosophy

**Lean Implementation**: Push complex utilities to services
- Worker focuses on orchestration and coordination
- Complex operations delegated to REM services
- Minimal business logic in worker code

**REM-First**: Use REM system for all reads and writes
- Query API for resource retrieval
- PostgresService/Repository for entity persistence
- Embedding API for vector operations
- Chat completions for LLM operations

**Modular**: Each operation is independent and composable
- User model updates can run independently
- Moment construction doesn't depend on affinity
- Affinity can use different modes (semantic vs LLM)

**Observable**: Rich logging and metrics
- Structured JSON logs for parsing
- Metrics for resources processed, moments created, edges added
- OpenTelemetry traces for distributed tracing

**Cloud-Native**: Designed for Kubernetes CronJob execution
- Stateless workers (no shared state)
- Spot instance tolerant
- Resource limits enforced
- Completion tracking

## Operations

### Ontology Extraction

Runs custom extractors on user's files and resources to extract domain-specific structured knowledge.

**What is an Ontology?**

An ontology is domain-specific knowledge extracted from files using custom agent schemas. Unlike generic chunking and embedding:
- **Structured**: Extracts specific fields (e.g., candidate skills, contract terms, medical diagnoses)
- **Validated**: Uses JSON Schema for output structure
- **Searchable**: Semantic search on extracted fields
- **Queryable**: Direct queries on structured data

**Examples:**
- **Recruitment**: Extract candidate skills, experience, education from CVs
- **Legal**: Extract parties, obligations, financial terms from contracts
- **Medical**: Extract diagnoses, medications, treatments from health records
- **Financial**: Extract metrics, risks, forecasts from reports

**How It Works:**

```
┌──────────────────────────────────────────────────────────────────┐
│ 1. Load User's Files/Resources (lookback window)                 │
│    - Query files WHERE user_id=X AND updated > cutoff            │
│    - Filter by processing_status='completed'                     │
└──────────────────┬───────────────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────────────┐
│ 2. Load Matching Extractor Schemas                               │
│    - Find schemas with category='ontology-extractor'             │
│    - Check user's OntologyConfig rules (MIME type, tags, etc.)   │
└──────────────────┬───────────────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────────────┐
│ 3. Run Extraction (for each file + schema pair)                  │
│    - Load schema from database                                   │
│    - Create agent: create_pydantic_ai_agent(schema.spec)         │
│    - Run agent: result = await agent.run(file.content)           │
│    - Serialize: serialize_agent_result(result.output)            │
└──────────────────┬───────────────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────────────┐
│ 4. Generate Embeddings                                           │
│    - Extract fields: extract_fields_for_embedding()              │
│    - Generate embedding: generate_embeddings()                   │
└──────────────────┬───────────────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────────────┐
│ 5. Store Ontology Entity                                         │
│    - Ontology(extracted_data=..., embedding_text=...)            │
│    - Save via ontology_repo.upsert()                             │
└──────────────────────────────────────────────────────────────────┘
```

**Key Principle: No Separate Service**

Ontology extraction is NOT a separate service. It's just:
- Load schema (existing repository)
- Run agent (existing `create_pydantic_ai_agent()`)
- Serialize result (existing `serialize_agent_result()`)
- Extract embedding text (util: `extract_fields_for_embedding()`)
- Generate embedding (existing `generate_embeddings()`)
- Store ontology (existing repository)

All logic lives in the dreaming worker. Maximum DRY.

**Process:**
1. Query user's files/resources (lookback window)
2. For each file, find matching extractor schemas
3. Run agent extraction on file content
4. Extract embedding text from configured fields
5. Generate embeddings for semantic search
6. Store Ontology entity

**Output:**
- Ontology entities with:
  - `extracted_data`: Arbitrary structured JSON (the gold!)
  - `file_id`: Link to source file
  - `agent_schema_id`: Which agent extracted this
  - `provider_name`, `model_name`: LLM used
  - `confidence_score`: Optional quality metric (0.0-1.0)
  - `embedding_text`: Text for semantic search

**CLI:**
```bash
# Run custom extractor on user's data
rem dreaming custom --user-id user-123 --extractor cv-parser-v1

# With lookback and limit
rem dreaming custom --user-id user-123 --extractor contract-analyzer-v1 \\
  --lookback-hours 168 --limit 50

# Override provider
rem dreaming custom --user-id user-123 --extractor cv-parser-v1 \\
  --provider anthropic --model claude-sonnet-4-5
```

**Frequency:** On-demand or as part of full workflow

**Example Extractors:**

**CV Parser** (`cv-parser-v1.yaml`):
```yaml
Extracts: candidate_name, email, skills, experience, education, certifications
Use case: Recruitment consultants processing resumes
Embedding fields: candidate_name, professional_summary, skills, experience
```

**Contract Analyzer** (`contract-analyzer-v1.yaml`):
```yaml
Extracts: parties, financial_terms, key_obligations, risk_flags
Use case: Legal teams analyzing supplier/partnership agreements
Embedding fields: contract_title, contract_type, parties, key_obligations
```

**Creating Custom Extractors:**

1. Define JSON Schema with output structure
2. Add system prompt in `description` field
3. Specify `embedding_fields` in `json_schema_extra`
4. Optionally specify `provider_configs` for multi-provider testing
5. Save to database as Schema entity
6. Create OntologyConfig rules (MIME type, URI pattern, tags)

See `rem/schemas/ontology_extractors/` for examples.

### User Model Updates

Reads recent activity to generate comprehensive user profiles.

**Process:**
1. Query REM for recent sessions, moments, resources
2. Generate user summary using LLM
3. Update User entity with summary and metadata
4. Add graph edges to key resources and moments

**Output:**
- Updated User entity with summary field
- Graph edges to recent resources (rel_type="engaged_with")
- Activity level classification (active, moderate, inactive)
- Interest and topic extraction

**CLI:**
```bash
rem-dreaming user-model 
```

**Frequency:** Daily (runs as part of full workflow)

### Moment Construction

Extracts temporal narratives from resources.

**Process:**
1. Query REM for recent resources (lookback window)
2. Use LLM to extract temporal narratives
3. Create Moment entities with temporal boundaries
4. Link moments to source resources via graph edges
5. Generate embeddings for moment content

**Output:**
- Moment entities with:
  - Temporal boundaries (starts_timestamp, ends_timestamp)
  - Present persons
  - Emotion tags (focused, excited, concerned)
  - Topic tags (sprint-planning, api-design)
  - Natural language summaries
- Graph edges to source resources (rel_type="extracted_from")

**CLI:**
```bash
# Process last 24 hours
rem-dreaming moments 

# Custom lookback
rem-dreaming moments  --lookback-hours=48

# Limit resources processed
rem-dreaming moments  --limit=100
```

**Frequency:** Daily or on-demand

### Resource Affinity

Builds semantic relationships between resources.

**Modes:**

**Semantic Mode (Fast)**
- Vector similarity search
- Creates edges for similar resources (threshold: 0.7)
- No LLM calls, pure vector math
- Cheap and fast
- Good for frequent updates (every 6 hours)

**LLM Mode (Intelligent)**
- LLM assessment of relationship context
- Rich metadata in edge properties
- Expensive (many LLM calls)
- ALWAYS use --limit to control costs
- Good for deep weekly analysis

**Process:**
1. Query REM for recent resources
2. For each resource:
   - Semantic: Query similar resources by vector
   - LLM: Assess relationships using LLM
3. Create graph edges via REM repository
4. Update resource entities with affinity edges

**Output:**
- Graph edges between resources with:
  - rel_type: semantic_similar, references, builds_on, etc.
  - weight: Relationship strength (0.0-1.0)
  - properties: Rich metadata (confidence, context)

**CLI:**
```bash
# Semantic mode (fast, cheap)
rem-dreaming affinity 

# LLM mode (intelligent, expensive)
rem-dreaming affinity  --use-llm --limit=100

# Custom lookback
rem-dreaming affinity  --lookback-hours=168
```

**Frequency:**
- Semantic: Every 6 hours
- LLM: Weekly (Sundays)

### Full Workflow

Runs all operations in sequence.

**Process:**
1. Update user model
2. Construct moments
3. Build resource affinity

**CLI:**
```bash
# Single tenant
rem-dreaming full 

# All active tenants (daily cron)
rem-dreaming full --all-tenants

# Use LLM affinity mode
rem-dreaming full  --use-llm-affinity
```

**Frequency:** Daily at 3 AM UTC

## Environment Variables

```bash
# REM Configuration
REM_API_URL=http://rem-api:8000              # REM API endpoint
REM_EMBEDDING_PROVIDER=text-embedding-3-small  # Embedding provider
REM_DEFAULT_MODEL=gpt-4o                     # LLM model
REM_LOOKBACK_HOURS=24                        # Default lookback window

# API Keys
OPENAI_API_KEY=sk-...                        # OpenAI API key
ANTHROPIC_API_KEY=sk-ant-...                 # Anthropic API key (optional)
```

## Kubernetes Deployment

### CronJobs

**Daily Full Workflow** (3 AM UTC)
```yaml
schedule: "0 3 * * *"
command: rem-dreaming full --all-tenants
resources: 256Mi memory, 250m CPU
```

**Frequent Affinity Updates** (Every 6 hours)
```yaml
schedule: "0 */6 * * *"
command: rem-dreaming affinity --all-tenants --lookback-hours=6
resources: 256Mi memory, 250m CPU
```

**Weekly LLM Affinity** (Sundays 2 AM)
```yaml
schedule: "0 2 * * 0"
command: rem-dreaming affinity --all-tenants --use-llm --limit=500
resources: 512Mi memory, 500m CPU
```

### Deployment

```bash
# Apply via Kustomize
kubectl apply -k manifests/application/rem-stack/base

# Or via ArgoCD
kubectl apply -f manifests/application/rem-stack/argocd-staging.yaml
```

### Monitoring

```bash
# List CronJobs
kubectl get cronjobs -n rem-app

# List Jobs
kubectl get jobs -n rem-app

# Follow logs
kubectl logs -f -l app=rem-dreaming -n rem-app

# Manual trigger
kubectl create job dreaming-manual-$(date +%s) \
  --from=cronjob/rem-dreaming-worker \
  -n rem-app
```

## Cost Management

### Semantic Mode (Cheap)
- Only embedding costs (if generating new embeddings)
- Vector similarity is computational, not API calls
- Good for frequent updates

### LLM Mode (Expensive)
- Each resource pair = 1 LLM API call
- 100 resources = potentially 5,000 API calls
- ALWAYS use --limit to control costs
- Monitor costs in LLM provider dashboard

### Best Practices
1. Use semantic mode for frequent updates (6 hours)
2. Use LLM mode sparingly (weekly)
3. Always use --limit with LLM mode
4. Start with small lookback windows (24-48 hours)
5. Monitor embedding/LLM costs regularly

## Error Handling

**Graceful Degradation**
- Continue on partial failures
- Don't fail entire job if one tenant fails
- Log errors with context for debugging

**Retry Logic**
- Exponential backoff for transient errors
- Retry up to 3 times for API failures
- Don't retry on validation errors

**Job Status**
- Save success/failure status to database
- Include error messages and stack traces
- Enable post-mortem debugging

## Performance

**Batch Operations**
- Minimize round trips to REM API
- Batch entity creation (upsert multiple)
- Batch embedding generation

**Streaming**
- Process large result sets incrementally
- Don't load all resources into memory
- Use cursor-based pagination

**Parallelization**
- Use asyncio for concurrent operations
- Process multiple tenants in parallel
- Limit concurrency to avoid overwhelming API

**Caching**
- Cache embeddings (REM handles this)
- Cache LLM responses when possible
- Use etags for conditional requests

## Development

### Local Testing

```bash
# Set environment variables
export REM_API_URL=http://localhost:8000
export OPENAI_API_KEY=sk-...

# Run user model update
python -m rem.cli.dreaming user-model 

# Run moment construction
python -m rem.cli.dreaming moments  --lookback-hours=24

# Run affinity (semantic mode)
python -m rem.cli.dreaming affinity 

# Run full workflow
python -m rem.cli.dreaming full 
```

### Testing with Docker

```bash
# Build image
docker build -t rem-stack:latest -f Dockerfile .

# Run worker
docker run --rm \
  -e REM_API_URL=http://host.docker.internal:8000 \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  rem-stack:latest \
  python -m rem.cli.dreaming full 
```

## Architecture Decisions

### Why Lean?
Complex operations belong in services (postgres, embeddings, etc.), not workers. Workers orchestrate, services execute.

### Why REM-First?
Using REM APIs ensures consistency, observability, and reusability. No direct database access in workers.

### Why Separate Modes?
Semantic mode is cheap and fast (frequent updates). LLM mode is expensive and intelligent (deep analysis).

### Why CronJob?
Batch processing is more efficient than continuous streaming. Daily indexing provides fresh insights without constant load.

### Why Spot Instances?
Workers are fault-tolerant and can restart. Spot instances reduce costs by 70% with minimal impact.

## Related Documentation

- [Engram Specification](../../models/core/engram.py) - Core memory model
- [REM Query API](../../api/) - Query interface
- [PostgresService & Repository](../../services/postgres/) - Entity persistence
- [CLAUDE.md](../../../../CLAUDE.md) - Overall architecture
