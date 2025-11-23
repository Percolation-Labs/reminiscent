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
- user_id: User identifier (primary data scoping field)
- tenant_id: Tenant identifier (legacy, set to user_id)
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
- user_id: User identifier (primary data scoping field)
- tenant_id: Tenant identifier (legacy, set to user_id)
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
- user_id: User identifier (primary data scoping field)
- tenant_id: Tenant identifier (legacy, set to user_id)
- role: Message role (user, assistant, system)
- content: Message text
- session_id: Conversation session identifier
- metadata: JSONB flexible metadata dict
- created_at, updated_at, deleted_at: Temporal tracking

## User
System users with authentication.

Fields:
- id: UUID (auto-generated)
- user_id: User identifier (primary data scoping field)
- tenant_id: Tenant identifier (legacy, set to user_id)
- name: User name
- email: User email
- metadata: JSONB flexible metadata dict
- created_at, updated_at, deleted_at: Temporal tracking

## File
File uploads with S3 storage.

Fields:
- id: UUID (auto-generated)
- user_id: User identifier (primary data scoping field)
- tenant_id: Tenant identifier (legacy, set to user_id)
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
rem_query(query_type="lookup", entity_key="Sarah Chen", user_id="user-123")
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
rem_query(query_type="fuzzy", query_text="sara", threshold=0.7, user_id="user-123")
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
    user_id="user-123"
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
    user_id="user-123"
)
```

Returns:
- Matching rows from table
- Automatically scoped to user_id

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
    user_id="user-123"
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


def register_agent_resources(mcp: FastMCP):
    """
    Register agent schema resources.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.resource("rem://agents")
    def list_available_agents() -> str:
        """
        List all available agent schemas.

        Returns a list of agent schemas packaged with REM, including:
        - Agent name
        - Description
        - Available tools
        - Version information

        TODO: Add pagination support if agent count grows large (not needed for now)
        """
        import importlib.resources
        import yaml
        from pathlib import Path

        try:
            # Find packaged agent schemas
            agents_ref = importlib.resources.files("rem") / "schemas" / "agents"
            agents_dir = Path(str(agents_ref))

            if not agents_dir.exists():
                return "# Available Agents\n\nNo agent schemas found in package."

            # Discover all agent schemas recursively
            agent_files = sorted(agents_dir.rglob("*.yaml")) + sorted(agents_dir.rglob("*.yml")) + sorted(agents_dir.rglob("*.json"))

            if not agent_files:
                return "# Available Agents\n\nNo agent schemas found."

            output = ["# Available Agent Schemas\n"]
            output.append("Packaged agent schemas available for use:\n")

            for agent_file in agent_files:
                try:
                    with open(agent_file, "r") as f:
                        schema = yaml.safe_load(f)

                    agent_name = agent_file.stem
                    description = schema.get("description", "No description")
                    # Get first 200 characters of description
                    desc_snippet = description[:200] + "..." if len(description) > 200 else description

                    # Get additional metadata
                    extra = schema.get("json_schema_extra", {})
                    version = extra.get("version", "unknown")
                    tools = extra.get("tools", [])

                    output.append(f"\n## {agent_name}")
                    output.append(f"**Path:** `agents/{agent_file.name}`")
                    output.append(f"**Version:** {version}")
                    output.append(f"**Description:** {desc_snippet}")
                    if tools:
                        output.append(f"**Tools:** {', '.join(tools[:5])}" + (" ..." if len(tools) > 5 else ""))

                    # Usage example
                    output.append(f"\n**Usage:**")
                    output.append(f"```python")
                    output.append(f'rem ask agents/{agent_file.name} "Your query here"')
                    output.append(f"```")

                except Exception as e:
                    output.append(f"\n## {agent_file.stem}")
                    output.append(f"⚠️  Error loading schema: {e}")

            return "\n".join(output)

        except Exception as e:
            return f"# Available Agents\n\nError listing agents: {e}"


def register_file_resources(mcp: FastMCP):
    """
    Register file operation resources.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.resource("rem://files/presigned-url/{s3_key}")
    def get_presigned_url(s3_key: str, expiration: int = 3600) -> str:
        """
        Generate presigned URL for S3 object download.

        Args:
            s3_key: S3 object key (e.g., "tenant/files/uuid/file.pdf")
            expiration: URL expiration time in seconds (default: 3600 = 1 hour)

        Returns:
            Presigned URL for downloading the file

        Raises:
            RuntimeError: If S3 is not configured

        Example:
            >>> url = get_presigned_url("acme/files/123/document.pdf")
            >>> # Returns: https://s3.amazonaws.com/bucket/acme/files/123/document.pdf?signature=...
        """
        from ...settings import settings

        # Check if S3 is configured
        if not settings.s3.bucket_name:
            raise RuntimeError(
                "S3 is not configured. Cannot generate presigned URLs.\n"
                "Configure S3 settings in ~/.rem/config.yaml or environment variables."
            )

        import aioboto3
        import asyncio
        from botocore.exceptions import ClientError

        async def _generate_url():
            session = aioboto3.Session()
            async with session.client(
                "s3",
                endpoint_url=settings.s3.endpoint_url,
                aws_access_key_id=settings.s3.access_key_id,
                aws_secret_access_key=settings.s3.secret_access_key,
                region_name=settings.s3.region,
            ) as s3_client:
                try:
                    url = await s3_client.generate_presigned_url(
                        "get_object",
                        Params={
                            "Bucket": settings.s3.bucket_name,
                            "Key": s3_key,
                        },
                        ExpiresIn=expiration,
                    )
                    return url
                except ClientError as e:
                    raise RuntimeError(f"Failed to generate presigned URL: {e}")

        # Run async function
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in async context, create new loop
            import nest_asyncio
            nest_asyncio.apply()
            url = loop.run_until_complete(_generate_url())
        else:
            url = asyncio.run(_generate_url())

        return url


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
- search_rem: Execute REM queries (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
- ask_rem_agent: Natural language to REM query conversion
- ingest_into_rem: File ingestion pipeline
- read_resource: Access MCP resources

## Status
✓ System operational
✓ Ready to process queries
"""


# Resource dispatcher for read_resource tool
async def load_resource(uri: str) -> dict | str:
    """
    Load an MCP resource by URI.

    This function is called by the read_resource tool to dispatch to
    registered resource handlers.

    Args:
        uri: Resource URI (e.g., "rem://schemas", "rem://status")

    Returns:
        Resource data (dict or string)

    Raises:
        ValueError: If URI is invalid or resource not found
    """
    # Create temporary MCP instance with resources
    from fastmcp import FastMCP

    mcp = FastMCP(name="temp")

    # Register all resources
    register_schema_resources(mcp)
    register_agent_resources(mcp)
    register_file_resources(mcp)
    register_status_resources(mcp)

    # Get resource handlers from MCP internal registry
    # FastMCP stores resources in a dict by URI
    if hasattr(mcp, "_resources"):
        if uri in mcp._resources:
            handler = mcp._resources[uri]
            if callable(handler):
                result = handler()
                return result if result else {"error": "Resource returned None"}

    # If not found, raise error
    raise ValueError(f"Resource not found: {uri}. Available resources: {list(mcp._resources.keys()) if hasattr(mcp, '_resources') else 'unknown'}")
