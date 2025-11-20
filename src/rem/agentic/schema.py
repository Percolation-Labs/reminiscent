"""
Agent Schema Protocol - Pydantic models for REM agent schemas.

This module defines the structure of agent schemas used in REM.
Agent schemas are JSON Schema documents with REM-specific extensions
in the `json_schema_extra` field.

The schema protocol serves as:
1. Documentation for agent schema structure
2. Validation for agent schema files
3. Type hints for schema manipulation
4. Single source of truth for schema conventions
"""

from typing import Any, Literal
from pydantic import BaseModel, Field


class MCPToolReference(BaseModel):
    """
    Reference to an MCP tool available to the agent.

    Tools are functions that agents can call during execution to
    interact with external systems, retrieve data, or perform actions.

    Example:
        {
            "name": "lookup_entity",
            "mcp_server": "rem",
            "description": "Lookup entities by exact key with O(1) performance"
        }
    """

    name: str = Field(
        description=(
            "Tool name as defined in the MCP server. "
            "Must match the tool name exposed by the MCP server exactly."
        )
    )

    mcp_server: str = Field(
        description=(
            "MCP server identifier. Resolved via environment variable: "
            "MCP_SERVER_{NAME} or MCP__{NAME}__URL. "
            "Common values: 'rem' (REM knowledge graph), 'filesystem', 'web'."
        )
    )

    description: str | None = Field(
        default=None,
        description=(
            "Optional description override. If provided, replaces the tool's "
            "description from the MCP server in the agent's context. "
            "Use this to provide agent-specific guidance on tool usage."
        ),
    )


class MCPResourceReference(BaseModel):
    """
    Reference to MCP resources accessible to the agent.

    Resources are data sources that can be read by agents, such as
    knowledge graph entities, files, or API endpoints.

    Example:
        {
            "uri_pattern": "rem://resources/.*",
            "mcp_server": "rem"
        }
    """

    uri_pattern: str = Field(
        description=(
            "Regex pattern matching resource URIs. "
            "Examples: "
            "'rem://resources/.*' (all resources), "
            "'rem://moments/.*' (all moments), "
            "'file:///data/.*' (local files). "
            "Supports full regex syntax for flexible matching."
        )
    )

    mcp_server: str = Field(
        description=(
            "MCP server identifier that provides these resources. "
            "Resolved via environment variable MCP_SERVER_{NAME}. "
            "The server must expose resources matching the uri_pattern."
        )
    )


class AgentSchemaMetadata(BaseModel):
    """
    REM-specific metadata for agent schemas.

    This is stored in the `json_schema_extra` field of the JSON Schema
    and extends standard JSON Schema with REM agent conventions.

    All fields are optional but recommended for production agents.
    """

    fully_qualified_name: str = Field(
        description=(
            "Fully qualified Python module path for the agent. "
            "Format: 'package.module.ClassName'. "
            "Examples: 'rem.agents.QueryAgent', 'rem.agents.SummarizationAgent'. "
            "Used for dynamic model naming and introspection."
        )
    )

    name: str | None = Field(
        default=None,
        description=(
            "Human-readable agent name. "
            "Examples: 'Query Agent', 'Summarization Agent'. "
            "Used in UI displays and logs. If not provided, derived from "
            "fully_qualified_name."
        ),
    )

    short_name: str | None = Field(
        default=None,
        description=(
            "Short identifier for the agent (lowercase, hyphenated). "
            "Examples: 'query-agent', 'summarize'. "
            "Used in URLs, file paths, and references. "
            "If not provided, derived from name or fully_qualified_name."
        ),
    )

    version: str | None = Field(
        default=None,
        description=(
            "Semantic version of the agent schema. "
            "Format: 'MAJOR.MINOR.PATCH' (e.g., '1.0.0', '2.1.3'). "
            "Increment MAJOR for breaking changes, MINOR for new features, "
            "PATCH for bug fixes. Used for schema evolution and compatibility."
        ),
    )

    tools: list[MCPToolReference] = Field(
        default_factory=list,
        description=(
            "MCP tools available to the agent. "
            "Tools are loaded dynamically from MCP servers at agent creation time. "
            "The agent can call these tools during execution to retrieve data, "
            "perform actions, or interact with external systems."
        ),
    )

    resources: list[MCPResourceReference] = Field(
        default_factory=list,
        description=(
            "MCP resources accessible to the agent. "
            "Resources are data sources that can be read by the agent, "
            "such as knowledge graph entities, files, or API endpoints. "
            "URI patterns are matched against resource URIs to determine access."
        ),
    )

    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Categorization tags for the agent. "
            "Examples: ['query', 'knowledge-graph'], ['summarization', 'nlp']. "
            "Used for discovery, filtering, and organization of agents."
        ),
    )

    author: str | None = Field(
        default=None,
        description=(
            "Agent author or team. "
            "Examples: 'REM Team', 'john@example.com'. "
            "Used for attribution and maintenance tracking."
        ),
    )

    model_config = {"extra": "allow"}  # Allow additional custom metadata


class AgentSchema(BaseModel):
    """
    Complete REM agent schema following JSON Schema Draft 7.

    Agent schemas are JSON Schema documents that define:
    1. System prompt (in `description` field)
    2. Structured output format (in `properties` field)
    3. REM-specific metadata (in `json_schema_extra` field)

    This is the single source of truth for agent behavior, output structure,
    and available tools/resources.

    Design Pattern:
    - JSON Schema as the schema language (framework-agnostic)
    - System prompt embedded in description (visible to LLM)
    - Output structure as standard JSON Schema properties
    - REM extensions in json_schema_extra (invisible to LLM)

    Example:
        ```json
        {
          "type": "object",
          "description": "You are a Query Agent that answers questions...",
          "properties": {
            "answer": {"type": "string", "description": "Query answer"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
          },
          "required": ["answer", "confidence"],
          "json_schema_extra": {
            "fully_qualified_name": "rem.agents.QueryAgent",
            "version": "1.0.0",
            "tools": [{"name": "lookup_entity", "mcp_server": "rem"}]
          }
        }
        ```
    """

    type: Literal["object"] = Field(
        default="object",
        description="JSON Schema type. Must be 'object' for agent schemas.",
    )

    description: str = Field(
        description=(
            "System prompt for the agent. This is the primary instruction "
            "given to the LLM explaining:\n"
            "- Agent's role and purpose\n"
            "- Available capabilities\n"
            "- Workflow and reasoning steps\n"
            "- Guidelines and constraints\n"
            "- Output format expectations\n\n"
            "This field is visible to the LLM and should be comprehensive, "
            "clear, and actionable. Use markdown formatting for structure."
        )
    )

    properties: dict[str, Any] = Field(
        description=(
            "Output schema properties following JSON Schema Draft 7. "
            "Each property defines:\n"
            "- type: JSON type (string, number, boolean, array, object)\n"
            "- description: Field purpose and content guidance\n"
            "- Validation: minimum, maximum, pattern, enum, etc.\n\n"
            "These properties define the structured output the agent produces. "
            "The agent must return a JSON object matching this schema."
        )
    )

    required: list[str] = Field(
        default_factory=list,
        description=(
            "List of required property names. "
            "The agent must include these fields in its output. "
            "Optional fields can be omitted. "
            "Example: ['answer', 'confidence']"
        ),
    )

    json_schema_extra: AgentSchemaMetadata = Field(
        default_factory=AgentSchemaMetadata,
        description=(
            "REM-specific metadata extending JSON Schema. "
            "Contains agent identification, versioning, and MCP configuration. "
            "This field is not visible to the LLM - it's used by the REM system "
            "for agent creation, tool loading, and resource access control."
        ),
    )

    # Additional JSON Schema fields (optional)
    title: str | None = Field(
        default=None,
        description="Schema title. If not provided, derived from fully_qualified_name.",
    )

    definitions: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Reusable schema definitions for complex nested types. "
            "Use JSON Schema $ref to reference definitions. "
            "Example: {'EntityKey': {'type': 'string', 'pattern': '^[a-z0-9-]+$'}}"
        ),
    )

    additionalProperties: bool = Field(
        default=False,
        description=(
            "Whether to allow additional properties not defined in schema. "
            "Default: False (strict validation). Set to True for flexible schemas."
        ),
    )

    model_config = {"extra": "allow"}  # Support full JSON Schema extensions


# Convenience type aliases for common use cases
AgentSchemaDict = dict[str, Any]  # Raw JSON Schema dict
AgentSchemaJSON = str  # JSON-serialized schema


def validate_agent_schema(schema: dict[str, Any]) -> AgentSchema:
    """
    Validate agent schema structure.

    Args:
        schema: Raw agent schema dict

    Returns:
        Validated AgentSchema instance

    Raises:
        ValidationError: If schema is invalid

    Example:
        >>> schema = load_schema("agents/query_agent.json")
        >>> validated = validate_agent_schema(schema)
        >>> print(validated.json_schema_extra.fully_qualified_name)
        "rem.agents.QueryAgent"
    """
    return AgentSchema.model_validate(schema)


def create_agent_schema(
    description: str,
    properties: dict[str, Any],
    required: list[str],
    fully_qualified_name: str,
    tools: list[dict[str, Any]] | None = None,
    resources: list[dict[str, Any]] | None = None,
    version: str = "1.0.0",
    **kwargs,
) -> AgentSchema:
    """
    Create agent schema programmatically.

    Args:
        description: System prompt
        properties: Output schema properties
        required: Required field names
        fully_qualified_name: Python module path
        tools: MCP tool references
        resources: MCP resource patterns
        version: Schema version
        **kwargs: Additional JSON Schema fields

    Returns:
        AgentSchema instance

    Example:
        >>> schema = create_agent_schema(
        ...     description="You are a helpful assistant...",
        ...     properties={
        ...         "answer": {"type": "string", "description": "Response"},
        ...         "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        ...     },
        ...     required=["answer"],
        ...     fully_qualified_name="rem.agents.Assistant",
        ...     tools=[{"name": "search", "mcp_server": "rem"}],
        ...     version="1.0.0"
        ... )
        >>> schema.json_schema_extra.tools[0].name
        "search"
    """
    metadata = AgentSchemaMetadata(
        fully_qualified_name=fully_qualified_name,
        tools=[MCPToolReference.model_validate(t) for t in (tools or [])],
        resources=[MCPResourceReference.model_validate(r) for r in (resources or [])],
        version=version,
    )

    return AgentSchema(
        description=description,
        properties=properties,
        required=required,
        json_schema_extra=metadata,
        **kwargs,
    )
