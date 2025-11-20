"""
MCP Resources for REM system information.

Resources are read-only data sources that LLMs can access for context.
They provide schema information, documentation, and system status.

Design Pattern:
- Resources are registered with the FastMCP server
- Resources return structured data (typically as strings or JSON)
- Resources don't modify system state (read-only)
- Resources help LLMs understand available operations

Available Resources:
- rem://schema/entities - Entity schemas documentation
- rem://schema/query-types - REM query types documentation
- rem://status - System health and statistics
"""

from fastmcp import FastMCP


def register_schema_resources(mcp: FastMCP):
    """
    Register schema documentation resources.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.resource("rem://schema/entities")
    def get_entity_schemas() -> str:
        """
        Get REM entity schemas documentation.

        Returns complete schema information for all entity types:
        - Resource: Chunked, embedded content
        - Entity: Domain knowledge nodes
        - Moment: Temporal narratives
        - Message: Conversation messages
        - User: System users
        - File: File uploads
        """
        return """
# REM Entity Schemas

## Resource
Chunked, embedded content from documents, files, conversations.

Fields:
- id: UUID (auto-generated)
- tenant_id: Tenant identifier
- user_id: Optional user ownership
- name: Resource name/label (used for LOOKUP)
- content: Main text content
- category: Optional category (document, conversation, etc.)
- related_entities: JSONB array of extracted entity references
- graph_paths: JSONB array of InlineEdge objects
- resource_timestamp: Timestamp of resource creation
- metadata: JSONB flexible metadata dict
- created_at, updated_at, deleted_at: Temporal tracking

## Entity
Domain knowledge nodes with properties and relationships.

NOTE: Entities are stored within resources/moments, not in a separate table.
Entity IDs are human-readable labels (e.g., "sarah-chen", "api-design-v2").

## Moment
Temporal narratives and time-bound events.

Fields:
- id: UUID (auto-generated)
- tenant_id: Tenant identifier
- user_id: Optional user ownership
- name: Moment name/label (used for LOOKUP)
- moment_type: Type (meeting, coding_session, conversation, etc.)
- resource_timestamp: Start time
- resource_ends_timestamp: End time
- present_persons: JSONB array of Person objects
- speakers: JSONB array of Speaker objects
- emotion_tags: Array of emotion tags
- topic_tags: Array of topic tags
- summary: Natural language summary
- source_resource_ids: Array of referenced resource UUIDs
- created_at, updated_at, deleted_at: Temporal tracking

## Message
Conversation messages with agents.

Fields:
- id: UUID (auto-generated)
- tenant_id: Tenant identifier
- user_id: Optional user ownership
- role: Message role (user, assistant, system)
- content: Message text
- session_id: Conversation session identifier
- metadata: JSONB flexible metadata dict
- created_at, updated_at, deleted_at: Temporal tracking

## User
System users with authentication.

Fields:
- id: UUID (auto-generated)
- tenant_id: Tenant identifier
- name: User name
- email: User email
- metadata: JSONB flexible metadata dict
- created_at, updated_at, deleted_at: Temporal tracking

## File
File uploads with S3 storage.

Fields:
- id: UUID (auto-generated)
- tenant_id: Tenant identifier
- user_id: Optional user ownership
- name: File name
- s3_key: S3 object key
- s3_bucket: S3 bucket name
- content_type: MIME type
- size_bytes: File size
- metadata: JSONB flexible metadata dict
- created_at, updated_at, deleted_at: Temporal tracking
"""

    @mcp.resource("rem://schema/query-types")
    def get_query_types() -> str:
        """
        Get REM query types documentation.

        Returns comprehensive documentation for all REM query types
        with examples and parameter specifications.
        """
        return """
# REM Query Types

## LOOKUP
O(1) entity resolution across ALL tables using KV_STORE.

Parameters:
- entity_key (required): Entity label/name (e.g., "sarah-chen", "api-design-v2")
- user_id (optional): User scoping for private entities

Example:
```
rem_query(query_type="lookup", entity_key="Sarah Chen", tenant_id="acme")
```

Returns:
- entity_key: The looked-up key
- entity_type: Entity type (person, document, etc.)
- entity_id: UUID of the entity
- content_summary: Summary of entity content
- metadata: Additional metadata

## FUZZY
Fuzzy text matching using pg_trgm similarity.

Parameters:
- query_text (required): Query string
- threshold (optional): Similarity threshold 0.0-1.0 (default: 0.7)
- limit (optional): Max results (default: 10)
- user_id (optional): User scoping

Example:
```
rem_query(query_type="fuzzy", query_text="sara", threshold=0.7, tenant_id="acme")
```

Returns:
- Entities matching query with similarity scores
- Ordered by similarity (highest first)

## SEARCH
Semantic vector search using embeddings (table-specific).

Parameters:
- query_text (required): Natural language query
- table_name (required): Table to search (resources, moments, etc.)
- field_name (optional): Field to search (defaults to "content")
- provider (optional): Embedding provider (default: from LLM__EMBEDDING_PROVIDER setting)
- min_similarity (optional): Minimum similarity 0.0-1.0 (default: 0.7)
- limit (optional): Max results (default: 10)
- user_id (optional): User scoping

Example:
```
rem_query(
    query_type="search",
    query_text="database migration",
    table_name="resources",
    tenant_id="acme"
)
```

Returns:
- Semantically similar entities
- Ordered by similarity score

## SQL
Direct SQL queries with WHERE clauses (tenant-scoped).

Parameters:
- table_name (required): Table to query
- where_clause (optional): SQL WHERE condition
- limit (optional): Max results

Example:
```
rem_query(
    query_type="sql",
    table_name="moments",
    where_clause="moment_type='meeting' AND resource_timestamp > '2025-01-01'",
    tenant_id="acme"
)
```

Returns:
- Matching rows from table
- Automatically scoped to tenant

## TRAVERSE
Multi-hop graph traversal with depth control.

Parameters:
- start_key (required): Starting entity key
- max_depth (optional): Maximum traversal depth (default: 1)
  - depth=0: PLAN mode (analyze edges without traversal)
  - depth=1+: Full traversal with cycle detection
- rel_type (optional): Filter by relationship type (e.g., "manages", "authored_by")
- user_id (optional): User scoping

Example:
```
rem_query(
    query_type="traverse",
    start_key="Sarah Chen",
    max_depth=2,
    rel_type="manages",
    tenant_id="acme"
)
```

Returns:
- Traversed entities with depth info
- Relationship types and weights
- Path information for each node

## Multi-Turn Exploration

REM supports iterated retrieval where LLMs conduct multi-turn conversations
with the database:

Turn 1: Find entry point
```
LOOKUP "Sarah Chen"
```

Turn 2: Analyze neighborhood (PLAN mode)
```
TRAVERSE start_key="Sarah Chen" max_depth=0
```

Turn 3: Selective traversal
```
TRAVERSE start_key="Sarah Chen" rel_type="manages" max_depth=2
```
"""


def register_status_resources(mcp: FastMCP):
    """
    Register system status resources.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.resource("rem://status")
    def get_system_status() -> str:
        """
        Get REM system health and statistics.

        Returns system information including:
        - Service health
        - Database connection status
        - Environment configuration
        - Available query types
        """
        from ...settings import settings

        return f"""
# REM System Status

## Environment
- Environment: {settings.environment}
- Team: {settings.team}
- Root Path: {settings.root_path or '/'}

## LLM Configuration
- Default Model: {settings.llm.default_model}
- Default Temperature: {settings.llm.default_temperature}
- Embedding Provider: {settings.llm.embedding_provider}
- Embedding Model: {settings.llm.embedding_model}
- OpenAI API Key: {"✓ Configured" if settings.llm.openai_api_key else "✗ Not configured"}
- Anthropic API Key: {"✓ Configured" if settings.llm.anthropic_api_key else "✗ Not configured"}

## Database
- PostgreSQL: {settings.postgres.connection_string}

## S3 Storage
- Bucket: {settings.s3.bucket_name}
- Region: {settings.s3.region}

## Observability
- OTEL Enabled: {settings.otel.enabled}
- Phoenix Enabled: {settings.phoenix.enabled}

## Authentication
- Auth Enabled: {settings.auth.enabled}

## Available Query Types
- LOOKUP: O(1) entity resolution
- FUZZY: Fuzzy text matching
- SEARCH: Semantic vector search
- SQL: Direct SQL queries
- TRAVERSE: Multi-hop graph traversal

## MCP Tools
- rem_query: Execute REM queries
- ask_rem: Natural language to REM query
- create_resource: Create new resource
- create_moment: Create temporal narrative
- update_graph_edges: Update entity graph edges

## Status
✓ System operational
✓ Ready to process queries
"""
