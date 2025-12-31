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
from pydantic import BaseModel, Field, field_validator


class MCPToolReference(BaseModel):
    """
    Reference to an MCP tool available to the agent.

    Tools are functions that agents can call during execution to
    interact with external systems, retrieve data, or perform actions.

    Two usage patterns:
    1. With mcp_servers config: Just declare name + description, tools loaded from MCP servers
    2. Explicit MCP server: Specify mcp_server to load tool from specific server

    Example (declarative with mcp_servers):
        {
            "name": "search_rem",
            "description": "Execute REM queries for entity lookup and search"
        }

    Example (explicit server):
        {
            "name": "lookup_entity",
            "mcp_server": "rem",
            "description": "Lookup entities by exact key"
        }
    """

    name: str = Field(
        description=(
            "Tool name as defined in the MCP server. "
            "Must match the tool name exposed by the MCP server exactly."
        )
    )

    mcp_server: str | None = Field(
        default=None,
        description=(
            "MCP server identifier (optional when using mcp_servers config). "
            "If not specified, tool is expected from configured mcp_servers. "
            "Resolved via environment variable: MCP_SERVER_{NAME} or MCP__{NAME}__URL."
        )
    )

    description: str | None = Field(
        default=None,
        description=(
            "Tool description for the agent. Explains what the tool does "
            "and when to use it. This is visible to the LLM."
        ),
    )


class MCPResourceReference(BaseModel):
    """
    Reference to MCP resources accessible to the agent.

    Resources are data sources that can be read by agents, such as
    knowledge graph entities, files, or API endpoints.

    Two formats supported:
    1. uri: Exact URI or URI with query params
    2. uri_pattern: Regex pattern for flexible matching

    Example (exact URI):
        {
            "uri": "rem://agents",
            "name": "Agent Schemas",
            "description": "List all available agent schemas"
        }

    Example (pattern):
        {
            "uri_pattern": "rem://resources/.*",
            "mcp_server": "rem"
        }
    """

    # Support both exact URI and pattern
    uri: str | None = Field(
        default=None,
        description=(
            "Exact resource URI or URI with query parameters. "
            "Examples: 'rem://agents', 'rem://resources?category=drug.*'"
        )
    )

    uri_pattern: str | None = Field(
        default=None,
        description=(
            "Regex pattern matching resource URIs. "
            "Examples: 'rem://resources/.*' (all resources). "
            "Use uri for exact URIs, uri_pattern for regex matching."
        )
    )

    name: str | None = Field(
        default=None,
        description="Human-readable name for the resource."
    )

    description: str | None = Field(
        default=None,
        description="Description of what the resource provides."
    )

    mcp_server: str | None = Field(
        default=None,
        description=(
            "MCP server identifier (optional when using mcp_servers config). "
            "Resolved via environment variable MCP_SERVER_{NAME}."
        )
    )


class MCPServerConfig(BaseModel):
    """
    MCP server configuration for in-process tool loading.

    Example:
        {
            "type": "local",
            "module": "rem.mcp_server",
            "id": "rem-local"
        }
    """

    type: Literal["local"] = Field(
        default="local",
        description="Server type. Currently only 'local' (in-process) is supported.",
    )

    module: str = Field(
        description=(
            "Python module path containing the MCP server. "
            "The module must export an 'mcp' object that supports get_tools(). "
            "Example: 'rem.mcp_server'"
        )
    )

    id: str = Field(
        default="mcp-server",
        description=(
            "Server identifier for logging and debugging. "
            "Defaults to 'mcp-server' if not specified. "
            "Example: 'rem-local'"
        )
    )


class AgentSchemaMetadata(BaseModel):
    """
    REM-specific metadata for agent schemas.

    This is stored in the `json_schema_extra` field of the JSON Schema
    and extends standard JSON Schema with REM agent conventions.

    All fields are optional but recommended for production agents.
    """

    kind: str | None = Field(
        default=None,
        description=(
            "Schema kind/type. Determines how the schema is processed. "
            "Values: 'agent', 'evaluator', 'engram'. "
            "Examples: 'agent' for agents, 'evaluator' for LLM-as-a-Judge evaluators, "
            "'engram' for memory documents. "
            "Used by processors to route schemas to the correct handler."
        )
    )

    name: str = Field(
        description=(
            "Unique schema identifier (kebab-case). "
            "Examples: 'query-agent', 'cv-parser', 'rem-lookup-correctness'. "
            "Used in URLs, file paths, database keys, and references. "
            "Must be unique within the kind namespace."
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

    # System prompt override (takes precedence over description when present)
    system_prompt: str | None = Field(
        default=None,
        description=(
            "Custom system prompt that overrides or extends the schema description. "
            "When present, this is combined with the main schema.description field "
            "to form the complete system prompt. Use this for detailed instructions "
            "that you don't want in the public schema description."
        ),
    )

    # Structured output toggle
    structured_output: bool | None = Field(
        default=None,
        description=(
            "Whether to enforce structured JSON output. "
            "When False, the agent produces free-form text and schema properties "
            "are converted to prompt guidance instead. "
            "Default: None (uses LLM__DEFAULT_STRUCTURED_OUTPUT setting, which defaults to False)."
        ),
    )

    # MCP server configurations (for dynamic tool loading)
    mcp_servers: list[MCPServerConfig] = Field(
        default_factory=list,
        description=(
            "MCP server configurations for dynamic tool loading. "
            "Servers are loaded in-process at agent creation time. "
            "All tools from configured servers become available to the agent. "
            "If not specified, defaults to rem.mcp_server (REM's built-in tools)."
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

    override_temperature: float | None = Field(
        default=None,
        description=(
            "Override default LLM temperature (0.0-1.0) for this agent. "
            "If None, uses global settings.llm.default_temperature."
        ),
    )

    override_max_iterations: int | None = Field(
        default=None,
        description=(
            "Override maximum iterations for this agent. "
            "If None, uses global settings.llm.default_max_iterations."
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
            "kind": "agent",
            "name": "query-agent",
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

    json_schema_extra: AgentSchemaMetadata | dict[str, Any] = Field(
        default_factory=dict,
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
        description="Schema title. If not provided, derived from name.",
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
        >>> print(validated.json_schema_extra["name"])
        "query-agent"
    """
    return AgentSchema.model_validate(schema)


def create_agent_schema(
    description: str,
    properties: dict[str, Any],
    required: list[str],
    name: str,
    kind: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    resources: list[dict[str, Any]] | None = None,
    version: str = "1.0.0",
    override_temperature: float | None = None,
    override_max_iterations: int | None = None,
    **kwargs,
) -> AgentSchema:
    """
    Create agent schema programmatically.

    Args:
        description: System prompt
        properties: Output schema properties
        required: Required field names
        name: Schema name in kebab-case (e.g., 'query-agent')
        kind: Schema kind ('agent' or 'evaluator'), optional
        tools: MCP tool references
        resources: MCP resource patterns
        version: Schema version
        override_temperature: Override default LLM temperature for this agent.
        override_max_iterations: Override maximum iterations for this agent.
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
        ...     kind="agent",
        ...     name="assistant",
        ...     tools=[{"name": "search", "mcp_server": "rem"}],
        ...     version="1.0.0"
        ... )
        >>> schema.json_schema_extra["tools"][0]["name"]
        "search"
    """
    metadata = AgentSchemaMetadata(
        kind=kind,
        name=name,
        tools=[MCPToolReference.model_validate(t) for t in (tools or [])],
        resources=[MCPResourceReference.model_validate(r) for r in (resources or [])],
        version=version,
        override_temperature=override_temperature,
        override_max_iterations=override_max_iterations,
    )

    return AgentSchema(
        description=description,
        properties=properties,
        required=required,
        json_schema_extra=metadata.model_dump(),
        **kwargs,
    )


# =============================================================================
# YAML and Database Serialization
# =============================================================================


def schema_to_dict(schema: AgentSchema, exclude_none: bool = True) -> dict[str, Any]:
    """
    Serialize AgentSchema to a dictionary suitable for YAML or database storage.

    This produces the canonical format used in:
    - YAML files (schemas/agents/*.yaml)
    - Database spec column (schemas table)
    - API responses

    Args:
        schema: AgentSchema instance to serialize
        exclude_none: If True, omit None values from output

    Returns:
        Dictionary representation of the schema

    Example:
        >>> schema = AgentSchema(
        ...     description="System prompt...",
        ...     properties={"answer": {"type": "string"}},
        ...     json_schema_extra={"name": "my-agent", "structured_output": False}
        ... )
        >>> d = schema_to_dict(schema)
        >>> d["json_schema_extra"]["name"]
        "my-agent"
    """
    return schema.model_dump(exclude_none=exclude_none)


def schema_from_dict(data: dict[str, Any]) -> AgentSchema:
    """
    Deserialize a dictionary to AgentSchema.

    This handles:
    - YAML files loaded with yaml.safe_load()
    - Database spec column (JSON)
    - API request bodies

    Args:
        data: Dictionary containing schema data

    Returns:
        Validated AgentSchema instance

    Raises:
        ValidationError: If data doesn't match schema structure

    Example:
        >>> data = {"type": "object", "description": "...", "properties": {}, "json_schema_extra": {"name": "test"}}
        >>> schema = schema_from_dict(data)
        >>> schema.json_schema_extra["name"]
        "test"
    """
    return AgentSchema.model_validate(data)


def schema_to_yaml(schema: AgentSchema) -> str:
    """
    Serialize AgentSchema to YAML string.

    The output format matches the canonical schema file format:
    ```yaml
    type: object
    description: |
      System prompt here...
    properties:
      answer:
        type: string
    json_schema_extra:
      name: my-agent
      system_prompt: |
        Extended prompt here...
    ```

    Args:
        schema: AgentSchema instance to serialize

    Returns:
        YAML string representation

    Example:
        >>> schema = create_agent_schema(
        ...     description="You are a test agent",
        ...     properties={"answer": {"type": "string"}},
        ...     required=["answer"],
        ...     name="test-agent"
        ... )
        >>> yaml_str = schema_to_yaml(schema)
        >>> "test-agent" in yaml_str
        True
    """
    import yaml

    return yaml.dump(
        schema_to_dict(schema),
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )


def schema_from_yaml(yaml_content: str) -> AgentSchema:
    """
    Deserialize YAML string to AgentSchema.

    Args:
        yaml_content: YAML string containing schema definition

    Returns:
        Validated AgentSchema instance

    Raises:
        yaml.YAMLError: If YAML parsing fails
        ValidationError: If schema structure is invalid

    Example:
        >>> yaml_str = '''
        ... type: object
        ... description: Test agent
        ... properties:
        ...   answer:
        ...     type: string
        ... json_schema_extra:
        ...   name: test
        ... '''
        >>> schema = schema_from_yaml(yaml_str)
        >>> schema.json_schema_extra["name"]
        "test"
    """
    import yaml

    data = yaml.safe_load(yaml_content)
    return schema_from_dict(data)


def schema_from_yaml_file(file_path: str) -> AgentSchema:
    """
    Load AgentSchema from a YAML file.

    Args:
        file_path: Path to YAML file

    Returns:
        Validated AgentSchema instance

    Raises:
        FileNotFoundError: If file doesn't exist
        yaml.YAMLError: If YAML parsing fails
        ValidationError: If schema structure is invalid

    Example:
        >>> schema = schema_from_yaml_file("schemas/agents/rem.yaml")
        >>> schema.json_schema_extra["name"]
        "rem"
    """
    with open(file_path, "r") as f:
        return schema_from_yaml(f.read())


def get_system_prompt(schema: AgentSchema | dict[str, Any]) -> str:
    """
    Extract the complete system prompt from a schema.

    Combines:
    1. schema.description (base system prompt / public description)
    2. json_schema_extra.system_prompt (extended instructions if present)

    Args:
        schema: AgentSchema instance or raw dict

    Returns:
        Complete system prompt string

    Example:
        >>> schema = AgentSchema(
        ...     description="Base description",
        ...     properties={},
        ...     json_schema_extra={"name": "test", "system_prompt": "Extended instructions"}
        ... )
        >>> prompt = get_system_prompt(schema)
        >>> "Base description" in prompt and "Extended instructions" in prompt
        True
    """
    if isinstance(schema, dict):
        base = schema.get("description", "")
        extra = schema.get("json_schema_extra", {})
        custom = extra.get("system_prompt") if isinstance(extra, dict) else None
    else:
        base = schema.description
        extra = schema.json_schema_extra
        if isinstance(extra, dict):
            custom = extra.get("system_prompt")
        elif isinstance(extra, AgentSchemaMetadata):
            custom = extra.system_prompt
        else:
            custom = None

    if custom:
        return f"{base}\n\n{custom}" if base else custom
    return base


def get_metadata(schema: AgentSchema | dict[str, Any]) -> AgentSchemaMetadata:
    """
    Extract and validate metadata from a schema.

    Args:
        schema: AgentSchema instance or raw dict

    Returns:
        Validated AgentSchemaMetadata instance

    Example:
        >>> schema = {"json_schema_extra": {"name": "test", "system_prompt": "hello"}}
        >>> meta = get_metadata(schema)
        >>> meta.name
        "test"
        >>> meta.system_prompt
        "hello"
    """
    if isinstance(schema, dict):
        extra = schema.get("json_schema_extra", {})
    else:
        extra = schema.json_schema_extra

    if isinstance(extra, AgentSchemaMetadata):
        return extra
    return AgentSchemaMetadata.model_validate(extra)
