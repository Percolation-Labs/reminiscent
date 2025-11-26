# REM Service

The `RemService` is the high-level query execution engine for REM (Resources-Entities-Moments), a bio-inspired memory infrastructure combining temporal narratives, semantic relationships, and structured knowledge.

## Architecture Overview

REM mirrors human memory systems through three complementary layers:

**Resources**: Chunked, embedded content from documents, files, and conversations. Stored with semantic embeddings for vector search, entity references, and knowledge graph edges.

**Entities**: Domain knowledge nodes with natural language labels (not UUIDs). Examples: "sarah-chen", "tidb-migration-spec". Enables conversational queries without requiring internal ID knowledge.

**Moments**: Temporal narratives (meetings, coding sessions, conversations) with time boundaries, present persons, speakers, emotion tags, and topic tags. Enable chronological memory retrieval.

Core design principle: Multi-index organization (vectors + graph + time + key-value) supporting iterated retrieval where LLMs conduct multi-turn database conversations.

## Query Dialect (AST)

REM queries follow a structured dialect with availability dependent on memory evolution stage.

### Grammar

```
Query ::= LookupQuery | FuzzyQuery | SearchQuery | SqlQuery | TraverseQuery

LookupQuery ::= LOOKUP <key:string|list[string]>
  key         : Single entity name or list of entity names (natural language labels)
  performance : O(1) per key
  available   : Stage 1+
  examples    :
    - LOOKUP "Sarah"
    - LOOKUP ["Sarah", "Mike", "Emily"]
    - LOOKUP "Project Alpha"

FuzzyQuery ::= FUZZY <text:string> [THRESHOLD <t:float>] [LIMIT <n:int>]
  text        : Search text (partial/misspelled)
  threshold   : Similarity score 0.0-1.0 (default: 0.5)
  limit       : Max results (default: 5)
  performance : Indexed (pg_trgm)
  available   : Stage 1+
  example     : FUZZY "sara" THRESHOLD 0.5 LIMIT 10

SearchQuery ::= SEARCH <text:string> [TABLE <table:string>] [WHERE <clause:string>] [LIMIT <n:int>]
  text        : Semantic query text
  table       : Target table (default: "resources")
  clause      : Optional PostgreSQL WHERE clause for hybrid filtering (combines vector + structured)
  limit       : Max results (default: 10)
  performance : Indexed (pgvector)
  available   : Stage 3+
  examples    :
    - SEARCH "database migration" TABLE resources LIMIT 10
    - SEARCH "team discussion" TABLE moments WHERE "moment_type='meeting'" LIMIT 5
    - SEARCH "project updates" WHERE "created_at >= '2024-01-01'" LIMIT 20
    - SEARCH "AI research" WHERE "tags @> ARRAY['machine-learning']" LIMIT 10

  Hybrid Query Support: SEARCH combines semantic vector similarity with structured filtering.
  Use WHERE clause to filter on system fields or entity-specific fields.

SqlQuery ::= SQL <table:string> [WHERE <clause:string>] [ORDER BY <order:string>] [LIMIT <n:int>]
  table       : Table name ("resources", "moments", etc.)
  clause      : PostgreSQL WHERE conditions (any valid PostgreSQL syntax)
  order       : ORDER BY clause
  limit       : Max results
  performance : O(n) with indexes
  available   : Stage 1+
  dialect     : PostgreSQL (supports all PostgreSQL features: JSONB operators, array operators, etc.)
  examples    :
    - SQL moments WHERE "moment_type='meeting'" ORDER BY starts_timestamp DESC LIMIT 10
    - SQL resources WHERE "metadata->>'status' = 'published'" LIMIT 20
    - SQL moments WHERE "tags && ARRAY['urgent', 'bug']" ORDER BY created_at DESC

  PostgreSQL Dialect: SQL queries use PostgreSQL syntax with full support for:
  - JSONB operators (->>, ->, @>, etc.)
  - Array operators (&&, @>, <@, etc.)
  - Advanced filtering and aggregations

TraverseQuery ::= TRAVERSE [<edge_types:list>] WITH <initial_query:Query> [DEPTH <d:int>] [ORDER BY <order:string>] [LIMIT <n:int>]
  edge_types    : Relationship types to follow (e.g., ["manages", "reports-to"], default: all)
  initial_query : Starting query (typically LOOKUP)
  depth         : Number of hops (0=PLAN mode, 1=single hop, N=multi-hop, default: 1)
  order         : Order results (default: "edge.created_at DESC")
  limit         : Max nodes (default: 9)
  performance   : O(k) where k = visited nodes
  available     : Stage 3+
  examples      :
    - TRAVERSE manages WITH LOOKUP "Sally" DEPTH 1
    - TRAVERSE WITH LOOKUP "Sally" DEPTH 0  (PLAN mode: edge analysis only)
    - TRAVERSE manages,reports-to WITH LOOKUP "Sarah" DEPTH 2 LIMIT 5
```

### System Fields (CoreModel)

All REM entities inherit from CoreModel and have these system fields:

* **id** (UUID or string): Unique identifier
* **created_at** (timestamp): Entity creation time (RECOMMENDED for filtering)
* **updated_at** (timestamp): Last modification time (RECOMMENDED for filtering)
* **deleted_at** (timestamp): Soft deletion time (null if active)
* **tenant_id** (string): Optional, for future multi-tenant SaaS use (kept for backward compat)
* **user_id** (string): Owner user identifier (primary isolation scope, auto-filtered)
* **graph_edges** (JSONB array): Knowledge graph edges - USE IN SELECT, NOT WHERE
* **metadata** (JSONB object): Flexible metadata storage
* **tags** (array of strings): Entity tags

**CRITICAL: graph_edges Usage Rules:**

* ✓ DO: Select `graph_edges` in result sets to see relationships
* ✗ DON'T: Filter by `graph_edges` in WHERE clauses (edge names vary by entity)
* ✓ DO: Use TRAVERSE queries to follow graph edges

Example CORRECT:
```sql
SELECT id, name, created_at, graph_edges FROM resources WHERE created_at >= '2024-01-01'
```

Example WRONG:
```sql
-- Edge names are unknown and vary by entity!
SELECT * FROM resources WHERE graph_edges @> '[{"dst": "sarah"}]'
```

### Main Tables (Resources, Moments, Files)

**Resources table:**

* **name** (string): Human-readable resource name
* **uri** (string): Content URI/identifier
* **content** (text): Resource content
* **timestamp** (timestamp): Content creation time (use for temporal filtering)
* **category** (string): Resource category (document, conversation, artifact, etc.)
* **related_entities** (JSONB): Extracted entities

**Moments table:**

* **name** (string): Human-readable moment name
* **moment_type** (string): Moment classification (meeting, coding-session, conversation, etc.)
* **category** (string): Moment category
* **starts_timestamp** (timestamp): Start time (use for temporal filtering)
* **ends_timestamp** (timestamp): End time
* **present_persons** (JSONB): People present in moment
* **emotion_tags** (array): Sentiment tags (happy, frustrated, focused, etc.)
* **topic_tags** (array): Topic/concept tags
* **summary** (text): Natural language description

**Files table:**

* **name** (string): File name
* **uri** (string): File URI/path
* **mime_type** (string): File MIME type
* **size_bytes** (integer): File size
* **processing_status** (string): Processing status (pending, completed, failed)
* **category** (string): File category

### Recommended Filtering Fields

* **Temporal**: created_at, updated_at, timestamp, starts_timestamp, ends_timestamp
* **Categorical**: category, moment_type, mime_type, processing_status
* **Arrays**: tags, emotion_tags, topic_tags (use && or @> operators)
* **Text**: name, content, summary (use ILIKE for pattern matching)

Use these fields in WHERE clauses for both SEARCH (hybrid) and SQL queries.

### Python API

```python
# LOOKUP - O(1) entity retrieval by natural language key
RemQuery(
    query_type=QueryType.LOOKUP,
    parameters=LookupParameters(key="Sarah")
)

# FUZZY - Trigram-based fuzzy text search
RemQuery(
    query_type=QueryType.FUZZY,
    parameters=FuzzyParameters(query_text="sara", threshold=0.5, limit=5)
)

# SEARCH - Vector similarity search using embeddings
RemQuery(
    query_type=QueryType.SEARCH,
    parameters=SearchParameters(query_text="database migration to TiDB", table_name="resources", limit=10)
)

# SQL - Direct SQL execution (tenant-isolated)
RemQuery(
    query_type=QueryType.SQL,
    parameters=SQLParameters(table_name="moments", where_clause="moment_type='meeting'", order_by="resource_timestamp DESC", limit=10)
)

# TRAVERSE - Recursive graph traversal following edges
RemQuery(
    query_type=QueryType.TRAVERSE,
    parameters=TraverseParameters(initial_query="Sally", edge_types=["manages"], max_depth=2, order_by="edge.created_at DESC", limit=9)
)
```

### Query Availability by Evolution Stage

| Query Type | Stage 0 | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------------|---------|---------|---------|---------|---------|
| LOOKUP     | ✗       | ✓       | ✓       | ✓       | ✓       |
| FUZZY      | ✗       | ✓       | ✓       | ✓       | ✓       |
| SEARCH     | ✗       | ✗       | ✗       | ✓       | ✓       |
| SQL        | ✗       | ✓       | ✓       | ✓       | ✓       |
| TRAVERSE   | ✗       | ✗       | ✗       | ✓       | ✓       |

**Stage 0**: No data, all queries fail.

**Stage 1** (20% answerable): Resources seeded with entity extraction. LOOKUP and FUZZY work for finding entities. SQL works for basic filtering.

**Stage 2** (50% answerable): Moments extracted. SQL temporal queries work. LOOKUP includes moment entities.

**Stage 3** (80% answerable): Affinity graph built. SEARCH and TRAVERSE become available. Multi-hop graph queries work.

**Stage 4** (100% answerable): Mature graph with rich historical data. All query types fully functional with high-quality results.

## Query Types

The service supports schema-agnostic and indexed query operations with strict performance contracts:

* **LOOKUP**: O(1) entity retrieval by natural language key (via `kv_store`).
* **FUZZY**: Trigram-based fuzzy text search (indexed).
* **SEARCH**: Vector similarity search using embeddings (requires `pgvector`).
* **SQL**: Direct SQL execution (tenant-isolated).
* **TRAVERSE**: Recursive graph traversal (O(k) where k = visited nodes).

## Graph Traversal (`TRAVERSE`)

The `TRAVERSE` operation allows agents to explore the knowledge graph by following edges between entities.

### Contract
*   **Performance**: O(k) where k is the number of visited nodes.
*   **Polymorphism**: Seamlessly traverses relationships between different entity types (`Resources`, `Moments`, `Users`, etc.).
*   **Filtering**: Supports filtering by relationship type(s).
*   **Cycle Detection**: Built-in cycle detection prevents infinite loops.

### Data Model
Graph traversal relies on the `InlineEdge` Pydantic model stored in the `graph_edges` JSONB column of every entity table.

**Expected JSON Structure (`InlineEdge`):**
```json
{
  "dst": "target-entity-key",      // Human-readable key (NOT UUID)
  "rel_type": "authored_by",       // Relationship type
  "weight": 0.8,                   // Connection strength (0.0-1.0)
  "properties": { ... }            // Additional metadata
}
```

### Usage
The `TRAVERSE` query accepts the following parameters:

*   `initial_query` (str): The starting entity key.
*   `max_depth` (int): Maximum number of hops (default: 1).
*   `edge_types` (list[str]): List of relationship types to follow. If empty or `['*']`, follows all edges.

**Example:**
```python
# Find entities connected to "Project X" via "depends_on" or "related_to" edges, up to 2 hops deep.
result = await rem_service.execute_query(
    RemQuery(
        query_type=QueryType.TRAVERSE,
        parameters=TraverseParameters(
            initial_query="Project X",
            max_depth=2,
            edge_types=["depends_on", "related_to"]
        ),
        user_id="user-123"
    )
)
```

## Memory Evolution Through Dreaming

REM improves query answerability over time through background dreaming workflows:

* **Stage 0**: Raw resources only (0% answerable)
* **Stage 1**: Entity extraction complete (20% answerable, LOOKUP works)
* **Stage 2**: Moments generated (50% answerable, temporal queries work)
* **Stage 3**: Affinity matching complete (80% answerable, semantic/graph queries work)
* **Stage 4**: Multiple dreaming cycles (100% answerable, full query capabilities)

Dreaming workers extract temporal narratives (moments) and build semantic graph edges (affinity) from resources, progressively enriching the knowledge graph.

## Testing Approach

REM testing follows a quality-driven methodology focused on query evolution:

**Critical Principle**: Test with user-known information only. Users provide natural language ("Sarah", "Project Alpha"), not internal representations ("sarah-chen", "project-alpha").

**Quality Validation**:

* Moment quality: Temporal validity, person extraction, speaker identification, tag quality, entity references, temporal coverage, type distribution
* Affinity quality: Edge existence, edge format, semantic relevance, bidirectional edges, entity connections, graph connectivity, edge distribution

**Integration Tests**: Validate progressive query answerability across memory evolution stages. Test suite includes realistic queries simulating multi-turn LLM-database conversations.

See `tests/integration/test_rem_query_evolution.py` for stage-based validation and `tests/integration/test_graph_traversal.py` for graph query testing.

## Architecture Notes

* **Unified View**: The underlying SQL function `rem_traverse` uses a view `all_graph_edges` that unions `graph_edges` from all entity tables (`resources`, `moments`, `users`, etc.). This enables polymorphic traversal without complex joins in the application layer.
* **KV Store**: Edge destinations (`dst`) are resolved to entity IDs using the `kv_store`. This requires that all traversable entities have an entry in the `kv_store` (handled automatically by database triggers).
* **Iterated Retrieval**: REM is architected for multi-turn retrieval where LLMs conduct conversational database exploration. Each query informs the next, enabling emergent information discovery without requiring upfront schema knowledge.

## Scaling & Architectural Decisions

### 1. Hybrid Adjacency List
REM implements a **Hybrid Adjacency List** pattern to balance strict relational guarantees with graph flexibility:
*   **Primary Storage (Source of Truth):** Standard PostgreSQL tables (`resources`, `moments`, etc.) enforce schema validation, constraints, and type safety.
*   **Graph Overlay:** Relationships are stored as "inline edges" within a JSONB column (`graph_edges`) on each entity.
*   **Performance Layer:** A denormalized `UNLOGGED` table (`kv_store`) acts as a high-speed cache, mapping human-readable keys to internal UUIDs and edges. This avoids the traditional "join bomb" of traversing normalized SQL tables while avoiding the operational complexity of a separate graph database (e.g., Neo4j).

### 2. The Pareto Principle in Graph Algorithms
We explicitly choose **Simplicity over Full-Scale Graph Analytics**.
*   **Hypothesis:** For LLM Agent workloads, 80% of the value is derived from **local context retrieval** (1-3 hops via `LOOKUP` and `TRAVERSE`).
*   **Diminishing Returns:** Global graph algorithms (PageRank, Community Detection) offer diminishing returns for real-time agentic retrieval tasks. Agents typically need to answer specific questions ("Who worked on file X?"), which is a local neighborhood problem, not a global cluster analysis problem.
*   **Future Scaling:** If deeper analysis is needed, we prefer **Graph + Vector (RAG)** approaches (using semantic similarity to find implicit links) over complex explicit graph algorithms.