# REM Dreaming Worker

Background worker for building the REM knowledge graph through memory indexing and insight extraction.

## Overview

The dreaming worker processes user content to construct the REM knowledge graph through three core operations:

1. **User Model Updates**: Extract and update user profiles from activity
2. **Moment Construction**: Identify temporal narratives from resources
3. **Resource Affinity**: Build semantic relationships between resources

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

**Lean Implementation**: Push complex utilities to services/repositories
- Worker focuses on orchestration and coordination
- Complex operations delegated to REM services
- Minimal business logic in worker code

**REM-First**: Use REM system for all reads and writes
- Query API for resource retrieval
- Repository API for entity persistence
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
rem-dreaming user-model --tenant-id=tenant-123
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
rem-dreaming moments --tenant-id=tenant-123

# Custom lookback
rem-dreaming moments --tenant-id=tenant-123 --lookback-hours=48

# Limit resources processed
rem-dreaming moments --tenant-id=tenant-123 --limit=100
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
rem-dreaming affinity --tenant-id=tenant-123

# LLM mode (intelligent, expensive)
rem-dreaming affinity --tenant-id=tenant-123 --use-llm --limit=100

# Custom lookback
rem-dreaming affinity --tenant-id=tenant-123 --lookback-hours=168
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
rem-dreaming full --tenant-id=tenant-123

# All active tenants (daily cron)
rem-dreaming full --all-tenants

# Use LLM affinity mode
rem-dreaming full --tenant-id=tenant-123 --use-llm-affinity
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
python -m rem.cli.dreaming user-model --tenant-id=tenant-test

# Run moment construction
python -m rem.cli.dreaming moments --tenant-id=tenant-test --lookback-hours=24

# Run affinity (semantic mode)
python -m rem.cli.dreaming affinity --tenant-id=tenant-test

# Run full workflow
python -m rem.cli.dreaming full --tenant-id=tenant-test
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
  python -m rem.cli.dreaming full --tenant-id=tenant-test
```

## Architecture Decisions

### Why Lean?
Complex operations belong in services/repositories, not workers. Workers orchestrate, services execute.

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
- [REM Repository](../../repositories/) - Entity persistence
- [CLAUDE.md](../../../../CLAUDE.md) - Overall architecture
