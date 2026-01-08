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
- min_similarity (optional): Minimum similarity 0.0-1.0 (default: 0.3)
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

    @mcp.resource("rem://agents/{agent_name}")
    def get_agent_schema(agent_name: str) -> str:
        """
        Get a specific agent schema by name.

        Args:
            agent_name: Name of the agent (e.g., "ask_rem", "agent-builder")

        Returns:
            Full agent schema as YAML string, or error message if not found.
        """
        import importlib.resources
        import yaml
        from pathlib import Path

        try:
            # Find packaged agent schemas
            agents_ref = importlib.resources.files("rem") / "schemas" / "agents"
            agents_dir = Path(str(agents_ref))

            if not agents_dir.exists():
                return f"# Agent Not Found\n\nNo agent schemas directory found."

            # Search for agent file (try multiple extensions)
            for ext in [".yaml", ".yml", ".json"]:
                # Try exact match first
                agent_file = agents_dir / f"{agent_name}{ext}"
                if agent_file.exists():
                    with open(agent_file, "r") as f:
                        content = f.read()
                    return f"# Agent Schema: {agent_name}\n\n```yaml\n{content}\n```"

                # Try recursive search
                matches = list(agents_dir.rglob(f"{agent_name}{ext}"))
                if matches:
                    with open(matches[0], "r") as f:
                        content = f.read()
                    return f"# Agent Schema: {agent_name}\n\n```yaml\n{content}\n```"

            # Not found - list available agents
            available = [f.stem for f in agents_dir.rglob("*.yaml")] + \
                       [f.stem for f in agents_dir.rglob("*.yml")]
            return f"# Agent Not Found\n\nAgent '{agent_name}' not found.\n\nAvailable agents: {', '.join(sorted(set(available)))}"

        except Exception as e:
            return f"# Error\n\nError loading agent '{agent_name}': {e}"


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


def register_session_resources(mcp: FastMCP):
    """
    Register session resources for loading conversation history.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.resource("rem://sessions/{session_id}")
    async def get_session_messages(session_id: str) -> str:
        """
        Load a conversation session by ID.

        Returns the full message history including user messages, assistant responses,
        and tool calls. Useful for evaluators and analysis agents.

        Args:
            session_id: Session UUID or identifier

        Returns:
            Formatted conversation history as markdown string with:
            - Message type (user/assistant/tool)
            - Content
            - Timestamps
            - Tool call details (if any)
        """
        from ...services.postgres import get_postgres_service

        pg = get_postgres_service()
        await pg.connect()

        try:
            # Query messages for session
            query = """
            SELECT id, message_type, content, metadata, created_at
            FROM messages
            WHERE session_id = $1
            ORDER BY created_at ASC
            """
            messages = await pg.fetch(query, session_id)

            if not messages:
                return f"# Session Not Found\n\nNo messages found for session_id: {session_id}"

            # Format output
            output = [f"# Session: {session_id}\n"]
            output.append(f"**Total messages:** {len(messages)}\n")

            for i, msg in enumerate(messages, 1):
                msg_type = msg['message_type']
                content = msg['content'] or "(empty)"
                created = msg['created_at']
                metadata = msg.get('metadata') or {}

                # Format based on message type
                if msg_type == 'user':
                    output.append(f"\n## [{i}] USER ({created})")
                    output.append(f"```\n{content[:1000]}{'...' if len(content) > 1000 else ''}\n```")
                elif msg_type == 'assistant':
                    output.append(f"\n## [{i}] ASSISTANT ({created})")
                    output.append(f"```\n{content[:1000]}{'...' if len(content) > 1000 else ''}\n```")
                elif msg_type == 'tool':
                    tool_name = metadata.get('tool_name', 'unknown')
                    output.append(f"\n## [{i}] TOOL: {tool_name} ({created})")
                    # Truncate tool results more aggressively
                    output.append(f"```json\n{content[:500]}{'...' if len(content) > 500 else ''}\n```")
                else:
                    output.append(f"\n## [{i}] {msg_type.upper()} ({created})")
                    output.append(f"```\n{content[:500]}{'...' if len(content) > 500 else ''}\n```")

            return "\n".join(output)

        finally:
            await pg.disconnect()

    @mcp.resource("rem://sessions")
    async def list_recent_sessions() -> str:
        """
        List recent sessions with basic info.

        Returns the most recent 20 sessions with:
        - Session ID
        - First user message (preview)
        - Message count
        - Timestamp
        """
        from ...services.postgres import get_postgres_service

        pg = get_postgres_service()
        await pg.connect()

        try:
            # Query recent sessions
            query = """
            SELECT
                session_id,
                MIN(created_at) as started_at,
                COUNT(*) as message_count,
                MIN(CASE WHEN message_type = 'user' THEN content END) as first_message
            FROM messages
            WHERE session_id IS NOT NULL
            GROUP BY session_id
            ORDER BY MIN(created_at) DESC
            LIMIT 20
            """
            sessions = await pg.fetch(query)

            if not sessions:
                return "# Recent Sessions\n\nNo sessions found."

            output = ["# Recent Sessions\n"]
            output.append(f"Showing {len(sessions)} most recent sessions:\n")

            for session in sessions:
                session_id = session['session_id']
                started = session['started_at']
                count = session['message_count']
                first_msg = session['first_message'] or "(no user message)"
                preview = first_msg[:80] + "..." if len(first_msg) > 80 else first_msg

                output.append(f"\n## {session_id}")
                output.append(f"- **Started:** {started}")
                output.append(f"- **Messages:** {count}")
                output.append(f"- **First message:** {preview}")
                output.append(f"- **Load:** `rem://sessions/{session_id}`")

            return "\n".join(output)

        finally:
            await pg.disconnect()


def register_user_resources(mcp: FastMCP):
    """
    Register user profile resources for on-demand profile loading.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.resource("user://profile/{user_id}")
    async def get_user_profile(user_id: str) -> str:
        """
        Load a user's profile by ID.

        Returns the user's profile information including:
        - Email and name
        - Summary (AI-generated profile summary)
        - Interests and preferred topics
        - Activity level

        This resource is protected - each user can only access their own profile.
        The user_id should match the authenticated user's ID from the JWT token.

        Args:
            user_id: User UUID from authentication

        Returns:
            Formatted user profile as markdown string, or error if not found
        """
        from ...services.postgres import get_postgres_service
        from ...services.postgres.repository import Repository
        from ...models.entities.user import User

        pg = get_postgres_service()
        await pg.connect()

        try:
            user_repo = Repository(User, "users", db=pg)
            # Look up user by ID (user_id from JWT is the primary key)
            user = await user_repo.get_by_id(user_id, tenant_id=None)

            if not user:
                return f"# User Profile Not Found\n\nNo user found with ID: {user_id}"

            # Build profile output
            output = [f"# User Profile: {user.name or user.email or 'Unknown'}"]
            output.append("")

            if user.email:
                output.append(f"**Email:** {user.email}")

            if user.role:
                output.append(f"**Role:** {user.role}")

            if user.tier:
                output.append(f"**Tier:** {user.tier.value if hasattr(user.tier, 'value') else user.tier}")

            if user.summary:
                output.append(f"\n## Summary\n{user.summary}")

            if user.interests:
                output.append(f"\n## Interests\n- " + "\n- ".join(user.interests[:10]))

            if user.preferred_topics:
                output.append(f"\n## Preferred Topics\n- " + "\n- ".join(user.preferred_topics[:10]))

            if user.activity_level:
                output.append(f"\n**Activity Level:** {user.activity_level}")

            if user.last_active_at:
                output.append(f"**Last Active:** {user.last_active_at}")

            # Add metadata if present (but redact sensitive fields)
            if user.metadata:
                safe_metadata = {k: v for k, v in user.metadata.items()
                               if k not in ('login_code', 'password', 'token', 'secret')}
                if safe_metadata:
                    output.append(f"\n## Additional Info")
                    for key, value in list(safe_metadata.items())[:5]:
                        output.append(f"- **{key}:** {value}")

            return "\n".join(output)

        except Exception as e:
            return f"# Error Loading Profile\n\nFailed to load user profile: {e}"

        finally:
            await pg.disconnect()


# Resource dispatcher for read_resource tool
async def load_resource(uri: str) -> dict | str:
    """
    Load an MCP resource by URI.

    This function is called by the read_resource tool to dispatch to
    registered resource handlers. Supports both regular resources and
    parameterized resource templates (e.g., rem://agents/{agent_name}).

    Args:
        uri: Resource URI (e.g., "rem://agents", "rem://agents/ask_rem", "rem://status")

    Returns:
        Resource data (dict or string)

    Raises:
        ValueError: If URI is invalid or resource not found
    """
    import inspect
    from fastmcp import FastMCP

    # Create temporary MCP instance with resources
    mcp = FastMCP(name="temp")

    # Register all resources
    register_schema_resources(mcp)
    register_agent_resources(mcp)
    register_file_resources(mcp)
    register_status_resources(mcp)
    register_session_resources(mcp)
    register_user_resources(mcp)

    # 1. Try exact match in regular resources
    resources = await mcp.get_resources()
    if uri in resources:
        resource = resources[uri]
        result = resource.fn()
        if inspect.iscoroutine(result):
            result = await result
        return result if result else {"error": "Resource returned None"}

    # 2. Try matching against parameterized resource templates
    templates = await mcp.get_resource_templates()
    for template_uri, template in templates.items():
        params = template.matches(uri)
        if params is not None:
            # Template matched - call function with extracted parameters
            result = template.fn(**params)
            if inspect.iscoroutine(result):
                result = await result
            return result if result else {"error": "Resource returned None"}

    # 3. Not found - include both resources and templates in error
    available = list(resources.keys()) + list(templates.keys())
    raise ValueError(f"Resource not found: {uri}. Available resources: {available}")
