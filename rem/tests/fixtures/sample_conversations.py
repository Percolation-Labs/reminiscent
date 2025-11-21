"""Sample conversation data for testing session management.

This module provides realistic conversation fixtures for testing:
- Multi-turn conversations
- Long responses requiring compression
- Technical Q&A about REM
- Code examples and explanations
"""

# Sample conversation: REM introduction
REM_INTRO_CONVERSATION = [
    {
        "role": "user",
        "content": "What is REM?",
        "timestamp": "2025-01-20T10:00:00Z",
    },
    {
        "role": "assistant",
        "content": """REM (Resources Entities Moments) is a bio-inspired memory architecture for agentic AI workloads. It mirrors human memory systems by organizing information into three main components:

**Resources**: Chunked, embedded content from documents, files, and conversations. These are semantically searchable via vector embeddings stored in pgvector.

**Entities**: Domain knowledge nodes with properties and relationships. They use human-readable labels (like "sarah-chen" or "api-design-v2") instead of UUIDs, enabling natural language queries.

**Moments**: Temporal narratives and time-bound events that enable chronological memory retrieval.

REM provides multi-index organization with vector embeddings, knowledge graphs, and temporal indexing for flexible information retrieval.""",
        "timestamp": "2025-01-20T10:00:05Z",
    },
    {
        "role": "user",
        "content": "How do I perform a LOOKUP query?",
        "timestamp": "2025-01-20T10:01:00Z",
    },
    {
        "role": "assistant",
        "content": """LOOKUP queries provide O(1) retrieval by entity label. Here's how to use them:

```python
from rem.models.core import REMQuery, QueryType

# Create a LOOKUP query
query = REMQuery(
    type=QueryType.LOOKUP,
    entity_label="sarah-chen",  # Human-readable label
    entity_type="person"  # Optional type filter
)

# Execute via REM service
result = await rem_service.execute_query(query)
```

LOOKUP queries are ideal when you know the exact entity label. They're the fastest retrieval method in REM and don't require semantic search or graph traversal.""",
        "timestamp": "2025-01-20T10:01:10Z",
    },
]

# Sample conversation: Technical deep dive
TECHNICAL_DEEP_DIVE = [
    {
        "role": "user",
        "content": "Explain the InlineEdge pattern in REM",
        "timestamp": "2025-01-20T11:00:00Z",
    },
    {
        "role": "assistant",
        "content": """The InlineEdge pattern is a key design choice in REM's knowledge graph implementation. Here's how it works:

**What is InlineEdge?**
Instead of storing graph edges in a separate table, REM stores them inline within entity records using JSONB. Each entity has a `graph_edges` field containing an array of edge objects.

**Edge Structure:**
```python
{
    "dst": "entity-label",  # Destination entity (human-readable)
    "type": "relationship-type",  # e.g., "authored", "references"
    "weight": 0.8,  # Importance (0.0-1.0)
    "properties": {  # Optional metadata
        "since": "2024-01-01",
        "context": "collaboration"
    }
}
```

**Benefits:**
1. **Natural language queries**: Use entity labels instead of UUIDs
2. **Locality**: Edges stored with source entity (fewer joins)
3. **Flexibility**: JSONB allows arbitrary properties
4. **Performance**: Index on dst for reverse traversal

**Example:**
```python
from rem.models.entities import Resource
from rem.models.core import InlineEdge

resource = Resource(
    uri="s3://docs/api-design.md",
    content="API design document...",
    graph_edges=[
        InlineEdge(
            dst="api-design-v2",
            type="implements",
            weight=1.0
        ),
        InlineEdge(
            dst="sarah-chen",
            type="authored-by",
            weight=0.9,
            properties={"role": "lead-architect"}
        )
    ]
)
```

This pattern enables conversational queries without requiring users to know internal IDs.""",
        "timestamp": "2025-01-20T11:00:15Z",
    },
    {
        "role": "user",
        "content": "How does TRAVERSE work with these edges?",
        "timestamp": "2025-01-20T11:02:00Z",
    },
    {
        "role": "assistant",
        "content": """TRAVERSE queries use InlineEdge relationships to navigate the knowledge graph. Here's the complete workflow:

**Query Structure:**
```python
from rem.models.core import REMQuery, QueryType

traverse_query = REMQuery(
    type=QueryType.TRAVERSE,
    entity_label="sarah-chen",  # Starting point
    edge_types=["authored-by", "references"],  # Relationship types
    max_depth=2,  # How far to traverse
    filters={"entity_type": "document"}  # Optional filtering
)
```

**Traversal Algorithm:**
1. Start at source entity (sarah-chen)
2. Load graph_edges from JSONB field
3. For each edge matching edge_types:
   - Follow dst label to next entity
   - Apply filters
   - Recursively traverse if depth < max_depth
4. Return all discovered entities with path metadata

**Performance:**
- O(k^d) where k = avg edges per node, d = depth
- JSONB GIN index on graph_edges for fast filtering
- Limit max_depth to prevent expensive queries
- Weight-based pruning for focused results

**Example Use Case:**
Find all documents authored by Sarah and entities they reference:
```python
results = await rem_service.execute_query(
    REMQuery(
        type=QueryType.TRAVERSE,
        entity_label="sarah-chen",
        edge_types=["authored-by", "references"],
        max_depth=2
    )
)

# Results include path information
for entity, path in results:
    print(f"Found: {entity.name}")
    print(f"Path: {' -> '.join(path)}")
```

**Graph Path Storage:**
Entities can also store computed `graph_paths` for common traversals, enabling faster repeated queries.""",
        "timestamp": "2025-01-20T11:02:20Z",
    },
]

# Sample conversation: Practical implementation
PRACTICAL_IMPLEMENTATION = [
    {
        "role": "user",
        "content": "How do I set up session logging in my chat application?",
        "timestamp": "2025-01-20T12:00:00Z",
    },
    {
        "role": "assistant",
        "content": """Setting up session logging in REM involves using the SessionMessageStore and reload_session utilities. Here's a complete example:

**1. Import Required Components:**
```python
from rem.services.session import SessionMessageStore, reload_session
from rem.services.postgres import get_postgres_service
```

**2. In Your Chat Endpoint:**
```python
@router.post("/chat/completions")
async def chat_completions(body: ChatRequest, request: Request):
    # Extract session context from headers
    context = AgentContext.from_headers(dict(request.headers))
    db = get_postgres_service()

    # Reload conversation history
    history = []
    if context.session_id and db:
        history = await reload_session(
            db=db,
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            decompress_messages=False  # Use compressed for efficiency
        )

    # Run agent with history
    agent = await create_agent(context)
    result = await agent.run(user_prompt)

    # Save new messages
    if context.session_id and db:
        store = SessionMessageStore(db=db, tenant_id=context.tenant_id)
        await store.store_session_messages(
            session_id=context.session_id,
            messages=[
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": result.output}
            ],
            user_id=context.user_id,
            compress=True
        )

    return result
```

**3. Client Request with Session:**
```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \\
  -H "X-Tenant-Id: acme-corp" \\
  -H "X-Session-Id: session-123" \\
  -H "X-User-Id: alice" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "openai:gpt-4o-mini",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Key Features:**
- Automatic compression of long messages (>400 chars)
- REM LOOKUP keys for retrieving full messages
- Graceful degradation when Postgres disabled
- Tenant isolation for multi-tenancy""",
        "timestamp": "2025-01-20T12:00:15Z",
    },
]

# Very long response for compression testing
COMPRESSION_TEST_CONVERSATION = [
    {
        "role": "user",
        "content": "Give me a comprehensive guide to REM architecture",
        "timestamp": "2025-01-20T13:00:00Z",
    },
    {
        "role": "assistant",
        "content": """# Comprehensive Guide to REM Architecture

## Overview
REM (Resources Entities Moments) is a sophisticated memory architecture designed for agentic AI workloads. It provides a bio-inspired approach to knowledge organization and retrieval.

## Core Components

### 1. Resources
Resources represent chunked, embedded content from various sources:
- Documents and files
- Chat conversations
- API responses
- Web scrapes

**Storage:**
- Content stored in `resources` table
- Vector embeddings in pgvector for semantic search
- Metadata includes source URI, timestamps, tenant isolation
- Related entities referenced via `related_entities` field
- Graph paths stored as InlineEdge objects

**Usage:**
Resources are the foundation of REM's knowledge base. They're automatically chunked, embedded, and indexed for semantic search.

### 2. Entities
Entities are domain knowledge nodes with properties and relationships:
- Natural language labels (not UUIDs!)
- Entity types: person, project, technology, concept, document
- Graph edges stored inline using InlineEdge pattern
- Flexible properties in JSONB

**Design Philosophy:**
Entity labels are human-readable (e.g., "sarah-chen", "api-design-v2") to enable conversational queries without requiring knowledge of internal IDs.

**Graph Structure:**
```python
entity.graph_edges = [
    {"dst": "related-entity", "type": "relationship", "weight": 0.8}
]
```

### 3. Moments
Moments are temporal narratives and time-bound events:
- Time-indexed classifications
- Present persons and speakers
- Emotion and topic tags
- Reference resources and entities (no duplication)

**Temporal Queries:**
Moments enable chronological memory retrieval:
- "What happened yesterday?"
- "When did we discuss X?"
- "Who was involved in Y?"

## Query System

### LOOKUP Queries (O(1))
Direct entity retrieval by label:
```python
REMQuery(type=QueryType.LOOKUP, entity_label="sarah-chen")
```

### SEARCH Queries (Vector)
Semantic search across entity types:
```python
REMQuery(type=QueryType.SEARCH, query_text="machine learning papers", entity_type="document")
```

### TRAVERSE Queries (Graph)
Navigate relationships with depth control:
```python
REMQuery(type=QueryType.TRAVERSE, entity_label="project-x", edge_types=["implements"], max_depth=2)
```

### SQL Queries (Structured)
Direct SQL for complex temporal/structured queries:
```python
REMQuery(type=QueryType.SQL, sql="SELECT * FROM entities WHERE created_at > '2024-01-01'")
```

## Memory Evolution Through Dreaming

REM uses a "dreaming" process to evolve raw data into structured knowledge:

**Stage 0: Raw Resources (0% answerable)**
- Only raw content ingested
- No entities or moments extracted

**Stage 1: Entity Extraction (20% answerable)**
- Entities extracted from resources
- LOOKUP queries work
- Basic entity references available

**Stage 2: Moments Generated (50% answerable)**
- Temporal narratives created
- Chronological queries work
- Event classification complete

**Stage 3: Affinity Matching (80% answerable)**
- Entity relationships discovered
- Graph traversal works
- Semantic connections established

**Stage 4: Multiple Dreaming Cycles (100% answerable)**
- Full query capabilities
- Optimized paths computed
- Comprehensive knowledge graph

## Cloud-Native Deployment

REM is designed for Kubernetes deployment:
- PostgreSQL with pgvector (CloudNativePG operator)
- FastAPI REST and streaming endpoints
- MCP server for tool integration
- OpenTelemetry for observability
- ArgoCD for GitOps deployment

**Scaling:**
- HPA for API replicas (2-10)
- KEDA for background workers (0-20)
- Karpenter for node autoscaling
- Spot instances for cost optimization

## Best Practices

1. **Use natural language labels**: Makes queries conversational
2. **Multi-index retrieval**: Combine LOOKUP, SEARCH, TRAVERSE for comprehensive results
3. **Iterated retrieval**: Let agents conduct multi-turn database conversations
4. **Tenant isolation**: Always scope queries by tenant_id
5. **Hybrid storage**: Leverage vectors + graph + time indexes together

## Performance Characteristics

- LOOKUP: O(1) with btree index
- SEARCH: O(n log k) with HNSW vector index
- TRAVERSE: O(k^d) where k=avg edges, d=depth
- SQL: Depends on query complexity and indexes

## Integration Patterns

REM integrates with:
- Pydantic AI for agent development
- FastMCP for tool interfaces
- OpenTelemetry for tracing
- Arize Phoenix for LLM observability

---

This architecture enables AI agents to maintain rich, queryable memory that evolves over time through automated knowledge extraction and relationship discovery."""
        * 2,  # Double the content to ensure it's long enough for compression
        "timestamp": "2025-01-20T13:00:30Z",
    },
]

# Multi-turn technical conversation
MULTI_TURN_TECHNICAL = [
    {
        "role": "user",
        "content": "What's the difference between Resources and Entities?",
        "timestamp": "2025-01-20T14:00:00Z",
    },
    {
        "role": "assistant",
        "content": "Resources are raw content (documents, messages) with embeddings. Entities are extracted knowledge nodes with labels and relationships. Think of Resources as 'what was said' and Entities as 'what it means'.",
        "timestamp": "2025-01-20T14:00:05Z",
    },
    {
        "role": "user",
        "content": "Can a Resource reference an Entity?",
        "timestamp": "2025-01-20T14:00:30Z",
    },
    {
        "role": "assistant",
        "content": "Yes! Resources have a `related_entities` field that lists entity labels mentioned in the content. They also have `graph_paths` (InlineEdge objects) for direct graph connectivity.",
        "timestamp": "2025-01-20T14:00:35Z",
    },
    {
        "role": "user",
        "content": "How are entity labels generated?",
        "timestamp": "2025-01-20T14:01:00Z",
    },
    {
        "role": "assistant",
        "content": "Entity labels are typically slugified from natural names: 'Sarah Chen' → 'sarah-chen', 'API Design v2' → 'api-design-v2'. They're designed to be memorable and conversational, not opaque UUIDs.",
        "timestamp": "2025-01-20T14:01:05Z",
    },
]

# All sample conversations for easy access
ALL_SAMPLE_CONVERSATIONS = {
    "rem_intro": REM_INTRO_CONVERSATION,
    "technical_deep_dive": TECHNICAL_DEEP_DIVE,
    "practical_implementation": PRACTICAL_IMPLEMENTATION,
    "compression_test": COMPRESSION_TEST_CONVERSATION,
    "multi_turn": MULTI_TURN_TECHNICAL,
}
