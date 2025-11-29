"""
REM Query Models

REM provides schema-agnostic query operations optimized for LLM-augmented
iterated retrieval. Unlike traditional SQL, REM queries work with natural
language labels instead of UUIDs and support multi-turn exploration.

Query Types (Performance Contract):
- LOOKUP: O(1) schema-agnostic entity resolution
- FUZZY: Indexed fuzzy text matching across all entities
- SEARCH: Indexed semantic vector search
- SQL: Direct table queries (provider dialect)
- TRAVERSE: Iterative O(1) lookups on graph edges

Key Design Principles:
1. Natural language surface area (labels, not UUIDs)
2. Schema-agnostic operations (no table name required for LOOKUP/FUZZY/TRAVERSE)
3. Multi-turn iteration with stage tracking and memos
4. O(1) performance guarantees for entity resolution

Iterated Retrieval Pattern:
- Stage 1: Find entry point (LOOKUP/SEARCH)
- Stage 2: Analyze neighborhood (TRAVERSE DEPTH 0 = PLAN mode)
- Stage 3: Selective traversal (TRAVERSE with edge filters)
- Stage 4: Refinement based on results

Example Multi-Turn Query:
```python
# Turn 1: PLAN mode to analyze edges
TRAVERSE WITH LOOKUP "sarah chen" DEPTH 0

# Turn 2: Follow specific edge types
TRAVERSE manages,mentors WITH LOOKUP "sarah chen" DEPTH 2

# Turn 3: Refine based on results
TRAVERSE authored_by WITH LOOKUP "api-design-v2" DEPTH 1
```

REM Query Contract (MANDATORY for all providers):
| Query Type | Performance | Schema | Multi-Match | Required |
|------------|-------------|--------|-------------|----------|
| LOOKUP | O(1) | Agnostic | Yes | ✅ |
| FUZZY | Indexed | Agnostic | Yes | ✅ |
| SEARCH | Indexed | Specific | Yes | ✅ |
| SQL | O(n) | Specific | No | ✅ |
| TRAVERSE | O(k) | Agnostic | Yes | ✅ |
"""

from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """
    REM query types.

    Each type has specific performance and schema requirements
    defined in the REM contract.
    """

    LOOKUP = "LOOKUP"
    FUZZY = "FUZZY"
    SEARCH = "SEARCH"
    SQL = "SQL"
    TRAVERSE = "TRAVERSE"


class LookupParameters(BaseModel):
    """
    LOOKUP query parameters.

    Performance: O(1) per key
    Schema: Agnostic - No table name required
    Multi-match: Returns entities from ALL tables with matching keys
    """

    key: Union[str, list[str]] = Field(
        ..., description="Entity identifier(s) - single key or list of keys (natural language labels)"
    )
    user_id: Optional[str] = Field(
        default=None, description="Optional user ID filter for multi-user tenants"
    )


class FuzzyParameters(BaseModel):
    """
    FUZZY query parameters.

    Performance: Indexed - FTS or trigram index required
    Schema: Agnostic - Searches across all entity names
    Multi-match: Returns entities from ALL tables matching fuzzy pattern
    """

    query_text: str = Field(..., description="Fuzzy search text")
    threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Similarity threshold"
    )
    limit: int = Field(default=5, gt=0, description="Maximum results")


class SearchParameters(BaseModel):
    """
    SEARCH query parameters.

    Performance: Indexed - Vector index required (IVF, HNSW)
    Schema: Table-specific - Requires table name
    """

    query_text: str = Field(..., description="Semantic search query")
    table_name: str = Field(..., description="Table to search (resources, moments, etc.)")
    limit: int = Field(default=10, gt=0, description="Maximum results")
    min_similarity: float = Field(
        default=0.3, ge=0.0, le=1.0, description="Minimum similarity score (0.3 recommended for general queries)"
    )


class SQLParameters(BaseModel):
    """
    SQL query parameters.

    Performance: O(n) - Table scan with optional indexes
    Schema: Table-specific - Requires table name and column knowledge
    Provider-specific: Uses native SQL dialect

    Supports two modes:
    1. Structured: table_name + where_clause + order_by + limit
    2. Raw: raw_query (full SQL statement like SELECT...)
    """

    raw_query: Optional[str] = Field(
        default=None, description="Raw SQL query (e.g., SELECT * FROM resources WHERE...)"
    )
    table_name: Optional[str] = Field(default=None, description="Table to query (structured mode)")
    where_clause: Optional[str] = Field(
        default=None, description="SQL WHERE clause (structured mode)"
    )
    order_by: Optional[str] = Field(default=None, description="SQL ORDER BY clause (structured mode)")
    limit: Optional[int] = Field(default=None, description="SQL LIMIT (structured mode)")


class TraverseParameters(BaseModel):
    """
    TRAVERSE query parameters.

    Performance: O(k) where k = number of keys traversed
    Schema: Agnostic - Follows graph edges across tables
    Implementation: Iterative LOOKUP calls on edge destinations

    Syntax: TRAVERSE {edge_filter} WITH [REM_QUERY] DEPTH [0-N]

    Depth Modes:
    - 0: PLAN mode (analyze edges without traversal)
    - 1: Single-hop traversal (default)
    - N: Multi-hop traversal (N hops from source)

    Plan Memo:
    Agent-maintained scratchpad for tracking multi-turn progress.
    Kept terse for fast token generation.
    Example: "Goal: org chart. Step 1: find CEO"
    """

    initial_query: str = Field(
        ..., description="Initial query to find entry nodes (LOOKUP key, SEARCH text, etc.)"
    )
    edge_types: list[str] = Field(
        default_factory=lambda: ["*"],
        description="Edge types to follow (e.g., ['manages', 'reports-to']). Default: ['*'] (all)",
    )
    max_depth: int = Field(
        default=1, ge=0, description="Maximum traversal depth. 0 = PLAN mode (no traversal)"
    )
    order_by: str = Field(
        default="edge.created_at DESC",
        description="Result ordering (edge.created_at, node.name, edge.weight)",
    )
    limit: int = Field(default=9, gt=0, description="Maximum nodes to return")
    plan_memo: Optional[str] = Field(
        default=None,
        description="Agent's terse scratchpad for tracking multi-turn progress",
    )


class RemQuery(BaseModel):
    """
    REM query plan.

    Combines query type with type-specific parameters.
    Used by both direct REM queries and ask_rem() natural language interface.
    """

    query_type: QueryType = Field(..., description="REM query type")
    parameters: (
        LookupParameters
        | FuzzyParameters
        | SearchParameters
        | SQLParameters
        | TraverseParameters
    ) = Field(..., description="Query parameters")
    user_id: Optional[str] = Field(
        default=None,
        description="User identifier (UUID5 hash of email). None = anonymous (shared/public data only)"
    )


class TraverseStage(BaseModel):
    """
    TRAVERSE execution stage information.

    Captures query execution details for LLM interaction and multi-turn planning.
    """

    depth: int = Field(..., description="Traversal depth for this stage")
    executed: str = Field(..., description="Query executed at this stage")
    found: dict[str, int] = Field(
        ..., description="Discovery stats (nodes, edges counts)"
    )
    plan_memo: Optional[str] = Field(
        default=None, description="Agent's memo echoed from request"
    )


class TraverseResponse(BaseModel):
    """
    TRAVERSE query response.

    Returns nodes, execution stages, and metadata for LLM-driven iteration.
    """

    nodes: list[dict[str, Any]] = Field(
        default_factory=list, description="Discovered nodes"
    )
    stages: list[TraverseStage] = Field(
        default_factory=list, description="Execution stage information"
    )
    source_nodes: list[str] = Field(
        default_factory=list, description="Initial entry node labels"
    )
    edge_summary: list[tuple[str, str, str]] = Field(
        default_factory=list,
        description="Edge shorthand tuples (src, rel_type, dst) for analysis",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Query metadata (total_nodes, max_depth_reached, etc.)"
    )
