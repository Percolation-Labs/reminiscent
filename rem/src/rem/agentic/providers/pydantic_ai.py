"""
Pydantic AI agent factory with dynamic JsonSchema to Pydantic model conversion.

AgentRuntime Pattern:
    The create_agent() factory returns an AgentRuntime object containing:
    - agent: The Pydantic AI Agent instance
    - temperature: Resolved temperature (schema override or settings default)
    - max_iterations: Resolved max iterations (schema override or settings default)

    This ensures runtime configuration is determined once at agent creation,
    not re-computed at every call site.

Known Issues:
    1. Cerebras Qwen Strict Mode Incompatibility
       - Cerebras qwen-3-32b requires additionalProperties=false for all object fields
       - Cannot use dict[str, Any] for flexible parameters (breaks Qwen compatibility)
       - Cannot use minimum/maximum constraints on number fields (Qwen rejects these)
       - Workaround: Use cerebras:llama-3.3-70b instead (fully compatible)
       - Future fix: Redesign REM agent to use discriminated union instead of dict

Key Design Pattern:
    1. JsonSchema → Pydantic Model (json-schema-to-pydantic library)
    2. Agent schema contains both system prompt AND output schema
    3. MCP tools loaded dynamically from schema metadata
    4. Result type can be stripped of description to avoid duplication with system prompt
    5. OTEL instrumentation conditional based on settings

Unique Design:
    - Agent schemas are JSON Schema with embedded metadata:
      - description: System prompt for agent
      - properties: Output schema fields
      - json_schema_extra.tools: MCP tool configurations
      - json_schema_extra.resources: MCP resource configurations
    - Dynamic model creation from schema using json-schema-to-pydantic
    - Tools and resources loaded from MCP servers via schema config
    - Stripped descriptions to avoid LLM schema bloat

TODO:
    Model Cache Implementation (Critical for Production Scale)
    Current bottleneck: Every agent.run() call creates a new Agent instance with
    model initialization overhead. At scale (100+ requests/sec), this becomes expensive.

    Need two-tier caching strategy:

    1. Schema Cache (see rem/utils/schema_loader.py TODO):
       - Filesystem schemas: LRU cache, no TTL (immutable)
       - Database schemas: TTL cache (5-15 min)
       - Reduces disk I/O and DB queries

    2. Model Instance Cache (THIS TODO):
       - Cache Pydantic AI Model() instances (connection pools, tokenizers)
       - Key: (provider, model_name) → Model instance
       - Benefits:
         * Reuse HTTP connection pools (httpx.AsyncClient)
         * Reuse tokenizer instances
         * Faster model initialization
         * Lower memory footprint
       - Implementation:
         ```python
         _model_cache: dict[tuple[str, str], Model] = {}

         def get_or_create_model(model_name: str) -> Model:
             cache_key = _parse_model_name(model_name)  # ("anthropic", "claude-3-5-sonnet")
             if cache_key not in _model_cache:
                 _model_cache[cache_key] = Model(model_name)
             return _model_cache[cache_key]
         ```
       - Considerations:
         * Max cache size (LRU eviction, e.g., 20 models)
         * Thread safety (asyncio.Lock for cache access)
         * Model warmup on server startup for hot paths
         * Clear cache on model config changes

    3. Agent Instance Caching (Advanced):
       - Cache complete Agent instances (model + schema + tools)
       - Key: (schema_name, model_name) → Agent instance
       - Benefits:
         * Skip schema parsing and model creation entirely
         * Fastest possible agent.run() latency
       - Challenges:
         * Agent state management (stateless required)
         * Tool/resource updates (cache invalidation)
         * Memory usage (agents are heavier than models)
       - Recommendation: Start with Model cache, add Agent cache if profiling shows benefit

    Profiling Targets (measure before optimizing):
    - schema_loader.load_agent_schema() calls per request
    - create_agent() execution time (model init overhead)
    - Model() instance creation time by provider
    - Agent.run() total latency breakdown

    Related Files:
    - rem/utils/schema_loader.py (schema caching TODO)
    - rem/agentic/providers/pydantic_ai.py:339 (create_agent - this file)
    - rem/services/schema_repository.py (database schema loading)

    Priority: HIGH (blocks production scaling beyond 50 req/sec)

    4. Response Format Control (structured_output enhancement):
       - Current: structured_output is bool (True=strict schema, False=free-form text)
       - Missing: OpenAI JSON mode (valid JSON without strict schema enforcement)
       - Missing: Completions API support (some models only support completions, not chat)

       Proposed schema field values for `structured_output`:
         - True (default): Strict structured output using provider's native schema support
         - False: Free-form text response (properties converted to prompt guidance)
         - "json": JSON mode - ensures valid JSON but no schema enforcement
                   (OpenAI: response_format={"type": "json_object"})
         - "text": Explicit free-form text (alias for False)

       Implementation:
         a) Update AgentSchemaMetadata.structured_output type:
            structured_output: bool | Literal["json", "text"] = True
         b) In create_agent(), handle each mode:
            - True: Use output_type with Pydantic model (current behavior)
            - False/"text": Convert properties to prompt guidance (current behavior)
            - "json": Use provider's JSON mode without strict schema
         c) Provider-specific JSON mode:
            - OpenAI: model_settings={"response_format": {"type": "json_object"}}
            - Anthropic: Not supported natively, use prompt guidance
            - Others: Fallback to prompt guidance with JSON instruction

       Related: Some providers (Cerebras) have completions-only models where
       structured output isn't available. Consider model capability detection.

       Priority: MEDIUM (enables more flexible output control)

Example Agent Schema:
{
  "type": "object",
  "description": "Agent that answers REM queries...",
  "properties": {
    "answer": {"type": "string", "description": "Query answer"},
    "confidence": {"type": "number"}
  },
  "required": ["answer", "confidence"],
  "json_schema_extra": {
    "kind": "agent",
    "name": "query-agent",
    "tools": [
      {"name": "search_knowledge_base", "mcp_server": "rem"}
    ],
    "resources": [
      {"uri_pattern": "cda://.*", "mcp_server": "rem"}
    ]
  }
}
"""

from typing import Any

from loguru import logger
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, Model

try:
    from json_schema_to_pydantic import PydanticModelBuilder

    JSON_SCHEMA_TO_PYDANTIC_AVAILABLE = True
except ImportError:
    JSON_SCHEMA_TO_PYDANTIC_AVAILABLE = False
    logger.warning(
        "json-schema-to-pydantic not installed. "
        "Install with: pip install 'rem[schema]' or pip install json-schema-to-pydantic"
    )

from ..context import AgentContext
from ...settings import settings


class AgentRuntime:
    """
    Agent runtime configuration bundle with delegation pattern.

    Contains the agent instance and its resolved runtime parameters
    (temperature, max_iterations) determined from schema overrides + settings defaults.

    Delegates run() and iter() calls to the inner agent with automatic UsageLimits.
    This allows callers to use AgentRuntime as a drop-in replacement for Agent.
    """

    def __init__(self, agent: Agent[None, Any], temperature: float, max_iterations: int):
        self.agent = agent
        self.temperature = temperature
        self.max_iterations = max_iterations

    async def run(self, *args, **kwargs):
        """Delegate to agent.run() with automatic UsageLimits."""
        from pydantic_ai import UsageLimits

        # Only apply usage_limits if not already provided
        if "usage_limits" not in kwargs:
            kwargs["usage_limits"] = UsageLimits(request_limit=self.max_iterations)
        return await self.agent.run(*args, **kwargs)

    def iter(self, *args, **kwargs):
        """Delegate to agent.iter() with automatic UsageLimits."""
        from pydantic_ai import UsageLimits

        # Only apply usage_limits if not already provided
        if "usage_limits" not in kwargs:
            kwargs["usage_limits"] = UsageLimits(request_limit=self.max_iterations)
        return self.agent.iter(*args, **kwargs)


def _get_builtin_tools() -> list:
    """
    Get built-in tools that are always available to agents.

    Currently returns empty list - all tools come from MCP servers.
    The register_metadata tool is available via the REM MCP server and
    agents can opt-in by configuring mcp_servers in their schema.

    Returns:
        List of Pydantic AI tool functions (currently empty)
    """
    # NOTE: register_metadata is now an MCP tool, not a built-in.
    # Agents that want it should configure mcp_servers to load from rem.mcp_server.
    # This allows agents to choose which tools they need.
    return []


def _create_model_from_schema(agent_schema: dict[str, Any]) -> type[BaseModel]:
    """
    Create Pydantic model dynamically from JSON Schema.

    Uses json-schema-to-pydantic library for robust conversion of:
    - Nested objects
    - Arrays
    - Required fields
    - Validation constraints

    Args:
        agent_schema: JSON Schema dict with agent output structure

    Returns:
        Dynamically created Pydantic BaseModel class

    Example:
        schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1}
            },
            "required": ["answer", "confidence"]
        }
        Model = _create_model_from_schema(schema)
        # Model is now a Pydantic class with answer: str and confidence: float fields
    """
    if not JSON_SCHEMA_TO_PYDANTIC_AVAILABLE:
        raise ImportError(
            "json-schema-to-pydantic is required for dynamic schema conversion. "
            "Install with: pip install 'rem[schema]' or pip install json-schema-to-pydantic"
        )

    # Create Pydantic model from JSON Schema
    builder = PydanticModelBuilder()
    model = builder.create_pydantic_model(agent_schema, root_schema=agent_schema)

    # Override model name with schema name if available
    json_extra = agent_schema.get("json_schema_extra", {})
    schema_name = json_extra.get("name")
    if schema_name:
        # Convert kebab-case to PascalCase for class name
        class_name = "".join(word.capitalize() for word in schema_name.split("-"))
        model.__name__ = class_name
        model.__qualname__ = class_name

    logger.debug(
        f"Created Pydantic model '{model.__name__}' from JSON Schema with fields: "
        f"{list(model.model_fields.keys())}"
    )

    return model


def _prepare_schema_for_qwen(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Prepare JSON schema for Cerebras Qwen strict mode compatibility.

    Cerebras Qwen strict mode requirements:
    1. additionalProperties MUST be false (this is mandatory in strict mode)
    2. All object types must have explicit properties field
    3. Cannot use minimum/maximum constraints (Pydantic ge/le works fine)

    This function transforms schemas to meet these requirements:
    - Changes additionalProperties from true to false
    - Adds empty properties {} to objects that don't have it
    - Preserves all other schema features

    IMPORTANT: This breaks dict[str, Any] flexibility!
    - dict[str, Any] generates {"type": "object", "additionalProperties": true}
    - Qwen requires additionalProperties: false
    - Result: Empty dict {} becomes the only valid value

    Recommendation: Don't use dict[str, Any] with Qwen. Use explicit Pydantic models instead.

    Args:
        schema: JSON schema dict (typically from model.model_json_schema())

    Returns:
        Modified schema compatible with Cerebras Qwen strict mode

    Example:
        # Pydantic generates for dict[str, Any]:
        {"type": "object", "additionalProperties": true}

        # Qwen requires:
        {"type": "object", "properties": {}, "additionalProperties": false}

        # This means dict can only be {}
    """
    def fix_object_properties(obj: dict[str, Any]) -> None:
        """Recursively fix object schemas for Qwen strict mode."""
        if isinstance(obj, dict):
            # Fix current object if it's type=object
            if obj.get("type") == "object":
                # Add empty properties if missing
                if "properties" not in obj and "anyOf" not in obj and "oneOf" not in obj:
                    obj["properties"] = {}

                # Force additionalProperties to false (required by Qwen strict mode)
                if "additionalProperties" in obj:
                    obj["additionalProperties"] = False

            # Remove minimum/maximum from number fields (Qwen rejects these)
            if obj.get("type") == "number":
                if "minimum" in obj or "maximum" in obj:
                    logger.warning(f"Stripping min/max from number field in Qwen schema: {obj.keys()}")
                obj.pop("minimum", None)
                obj.pop("maximum", None)

            # Recursively fix nested schemas
            for key, value in obj.items():
                if isinstance(value, dict):
                    fix_object_properties(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            fix_object_properties(item)

    # Work on a copy to avoid mutating original
    import copy
    schema_copy = copy.deepcopy(schema)
    fix_object_properties(schema_copy)

    return schema_copy


def _convert_properties_to_prompt(properties: dict[str, Any]) -> str:
    """
    Convert schema properties to prompt guidance text.

    When structured_output is disabled, this converts the properties
    definition into natural language guidance that informs the agent
    about the expected response structure without forcing JSON output.

    Args:
        properties: JSON Schema properties dict

    Returns:
        Prompt text describing the expected response elements

    Example:
        properties = {
            "answer": {"type": "string", "description": "The answer"},
            "confidence": {"type": "number", "description": "Confidence 0-1"}
        }
        # Returns:
        # "## Response Structure\n\nYour response should include:\n- **answer**: The answer\n..."
    """
    if not properties:
        return ""

    lines = ["## Response Guidelines", "", "Your response should address the following elements:"]

    for field_name, field_def in properties.items():
        field_type = field_def.get("type", "any")
        description = field_def.get("description", "")

        # Format based on type
        if field_type == "array":
            type_hint = "list"
        elif field_type == "number":
            type_hint = "number"
            # Include min/max if specified
            if "minimum" in field_def or "maximum" in field_def:
                min_val = field_def.get("minimum", "")
                max_val = field_def.get("maximum", "")
                if min_val != "" and max_val != "":
                    type_hint = f"number ({min_val}-{max_val})"
        elif field_type == "boolean":
            type_hint = "yes/no"
        else:
            type_hint = field_type

        # Build field description
        field_line = f"- **{field_name}**"
        if type_hint and type_hint != "string":
            field_line += f" ({type_hint})"
        if description:
            field_line += f": {description}"

        lines.append(field_line)

    lines.append("")
    lines.append("Respond naturally in prose, addressing these elements where relevant.")

    return "\n".join(lines)


def _create_schema_wrapper(
    result_type: type[BaseModel], strip_description: bool = True
) -> type[BaseModel]:
    """
    Create wrapper model that customizes schema generation.

    Prevents redundant descriptions in LLM schema while keeping
    docstrings in Python code for documentation.

    Design Pattern
    - Agent schema.description contains full system prompt
    - Output model description would duplicate this
    - Stripping description reduces token usage without losing information

    Args:
        result_type: Original Pydantic model with docstring
        strip_description: If True, removes model-level description from schema

    Returns:
        Wrapper model that generates schema without description field

    Example:
        class AgentOutput(BaseModel):
            \"\"\"Agent output with answer and confidence.\"\"\"
            answer: str
            confidence: float

        Wrapped = _create_schema_wrapper(AgentOutput, strip_description=True)
        # Wrapped.model_json_schema() excludes top-level description
    """
    if not strip_description:
        return result_type

    # Create model that overrides schema generation
    class SchemaWrapper(result_type):  # type: ignore
        @classmethod
        def model_json_schema(cls, **kwargs):
            schema = super().model_json_schema(**kwargs)
            # Remove model-level description to avoid duplication with system prompt
            schema.pop("description", None)
            # Prepare schema for Qwen compatibility
            schema = _prepare_schema_for_qwen(schema)
            return schema

    # Preserve original model name for debugging
    SchemaWrapper.__name__ = result_type.__name__
    return SchemaWrapper


async def create_agent_from_schema_file(
    schema_name_or_path: str,
    context: AgentContext | None = None,
    model_override: KnownModelName | Model | None = None,
) -> Agent:
    """
    Create agent from schema file (YAML/JSON).

    Handles path resolution automatically:
    - "contract-analyzer" → searches schemas/agents/examples/contract-analyzer.yaml
    - "moment-builder" → searches schemas/agents/core/moment-builder.yaml
    - "rem" → searches schemas/agents/rem.yaml
    - "/absolute/path.yaml" → loads directly
    - "relative/path.yaml" → loads relative to cwd

    Args:
        schema_name_or_path: Schema name or file path
        context: Optional agent context
        model_override: Optional model override

    Returns:
        Configured Agent instance

    Example:
        # Load by name (searches package schemas)
        agent = await create_agent_from_schema_file("contract-analyzer")

        # Load from custom path
        agent = await create_agent_from_schema_file("./my-agent.yaml")
    """
    from ...utils.schema_loader import load_agent_schema

    # Load schema using centralized utility
    agent_schema = load_agent_schema(schema_name_or_path)

    # Create agent using existing factory
    return await create_agent(
        context=context,
        agent_schema_override=agent_schema,
        model_override=model_override,
    )


async def create_agent(
    context: AgentContext | None = None,
    agent_schema_override: dict[str, Any] | None = None,
    model_override: KnownModelName | Model | None = None,
    result_type: type[BaseModel] | None = None,
    strip_model_description: bool = True,
) -> AgentRuntime:
    """
    Create agent from context with dynamic schema loading.

    Provider-agnostic interface - currently implemented with Pydantic AI.

    Design Pattern:
    1. Load agent schema from context.agent_schema_uri or use override
    2. Extract system prompt from schema.description
    3. Create dynamic Pydantic model from schema.properties
    4. Load MCP tools from schema.json_schema_extra.tools
    5. Create agent with model, prompt, output_type, and tools
    6. Enable OTEL instrumentation conditionally

    All configuration comes from context unless explicitly overridden.
    MCP server URLs resolved from environment variables (MCP_SERVER_{NAME}).

    Args:
        context: AgentContext with schema URI, model, session info
        agent_schema_override: Optional explicit schema (bypasses context.agent_schema_uri)
        model_override: Optional explicit model (bypasses context.default_model)
        result_type: Optional Pydantic model for structured output
        strip_model_description: If True, removes model docstring from LLM schema

    Returns:
        Configured Pydantic.AI Agent with MCP tools

    Example:
        # From context with schema URI
        context = AgentContext(
            user_id="user123",
            tenant_id="acme-corp",
            agent_schema_uri="rem-agents-query-agent"
        )
        agent = await create_agent(context)

        # With explicit schema and result type
        schema = {...}  # JSON Schema
        class Output(BaseModel):
            answer: str
            confidence: float

        agent = await create_agent(
            agent_schema_override=schema,
            result_type=Output
        )
    """
    # Initialize OTEL instrumentation if enabled (idempotent)
    if settings.otel.enabled:
        from ..otel import setup_instrumentation

        setup_instrumentation()

    # Load agent schema from context or use override
    agent_schema = agent_schema_override
    if agent_schema is None and context and context.agent_schema_uri:
        # TODO: Load schema from schema registry or file
        # from ..schema import load_agent_schema
        # agent_schema = load_agent_schema(context.agent_schema_uri)
        pass

    # Determine model: validate override against allowed list, fallback to context or settings
    from rem.agentic.llm_provider_models import get_valid_model_or_default

    default_model = context.default_model if context else settings.llm.default_model
    model = get_valid_model_or_default(model_override, default_model)

    # Extract schema fields using typed helpers
    from ..schema import get_system_prompt, get_metadata

    if agent_schema:
        system_prompt = get_system_prompt(agent_schema)
        metadata = get_metadata(agent_schema)
        resource_configs = metadata.resources if hasattr(metadata, 'resources') else []

        # DEPRECATED: mcp_servers in agent schemas is ignored
        # MCP servers are now always auto-detected at the application level
        if hasattr(metadata, 'mcp_servers') and metadata.mcp_servers:
            logger.warning(
                "DEPRECATED: mcp_servers in agent schema is ignored. "
                "MCP servers are auto-detected from tools.mcp_server module. "
                "Remove mcp_servers from your agent schema."
            )

        if metadata.system_prompt:
            logger.debug("Using custom system_prompt from json_schema_extra")
    else:
        system_prompt = ""
        metadata = None
        resource_configs = []

    # Auto-detect MCP server at application level
    # Convention: tools/mcp_server.py exports `mcp` FastMCP instance
    # Falls back to REM's built-in MCP server if no local server found
    import importlib
    import os
    import sys

    # Ensure current working directory is in sys.path for local imports
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    mcp_server_configs = []
    auto_detect_modules = [
        "tools.mcp_server",  # Convention: tools/mcp_server.py
        "mcp_server",        # Alternative: mcp_server.py in root
    ]
    for module_path in auto_detect_modules:
        try:
            mcp_module = importlib.import_module(module_path)
            if hasattr(mcp_module, "mcp"):
                logger.info(f"Auto-detected local MCP server: {module_path}")
                mcp_server_configs = [{"type": "local", "module": module_path, "id": "auto-detected"}]
                break
        except ImportError as e:
            logger.debug(f"MCP server auto-detect: {module_path} not found ({e})")
            continue
        except Exception as e:
            logger.warning(f"MCP server auto-detect: {module_path} failed to load: {e}")
            continue

    # Fall back to REM's default MCP server if no local server found
    if not mcp_server_configs:
        logger.info("No local MCP server found, using REM default (rem.mcp_server)")
        mcp_server_configs = [{"type": "local", "module": "rem.mcp_server", "id": "rem"}]

    # Extract temperature and max_iterations from schema metadata (with fallback to settings defaults)
    if metadata:
        temperature = metadata.override_temperature if metadata.override_temperature is not None else settings.llm.default_temperature
        max_iterations = metadata.override_max_iterations if metadata.override_max_iterations is not None else settings.llm.default_max_iterations
        # Use schema-level structured_output if set, otherwise fall back to global setting
        use_structured_output = metadata.structured_output if metadata.structured_output is not None else settings.llm.default_structured_output
    else:
        temperature = settings.llm.default_temperature
        max_iterations = settings.llm.default_max_iterations
        use_structured_output = settings.llm.default_structured_output

    # Build list of tools - start with built-in tools
    tools = _get_builtin_tools()

    # Get agent name from metadata for logging
    agent_name = metadata.name if metadata and hasattr(metadata, 'name') else "unknown"

    logger.info(
        f"Creating agent '{agent_name}': model={model}, mcp_servers={len(mcp_server_configs)}, "
        f"resources={len(resource_configs)}, builtin_tools={len(tools)}"
    )

    # Set agent resource attributes for OTEL (before creating agent)
    if settings.otel.enabled and agent_schema:
        from ..otel import set_agent_resource_attributes

        set_agent_resource_attributes(agent_schema=agent_schema)

    # Extract schema metadata for search_rem tool description suffix
    # This allows entity schemas to add context-specific notes to the search_rem tool
    search_rem_suffix = None
    if metadata:
        # Check for default_search_table in metadata (set by entity schemas)
        extra = agent_schema.get("json_schema_extra", {}) if agent_schema else {}
        default_table = extra.get("default_search_table")
        has_embeddings = extra.get("has_embeddings", False)

        if default_table:
            # Build description suffix for search_rem
            search_rem_suffix = f"\n\nFor this schema, use `search_rem` to query `{default_table}`. "
            if has_embeddings:
                search_rem_suffix += f"SEARCH works well on {default_table} (has embeddings). "
            search_rem_suffix += f"Example: `SEARCH \"your query\" FROM {default_table} LIMIT 10`"

    # Add tools from MCP server (in-process, no subprocess)
    # Track loaded MCP servers for resource resolution
    loaded_mcp_server = None

    for server_config in mcp_server_configs:
        server_type = server_config.get("type")
        server_id = server_config.get("id", "mcp-server")

        if server_type == "local":
            # Import MCP server directly (in-process)
            module_path = server_config.get("module", "rem.mcp_server")

            try:
                # Dynamic import of MCP server module
                import importlib
                mcp_module = importlib.import_module(module_path)
                mcp_server = mcp_module.mcp

                # Store the loaded server for resource resolution
                loaded_mcp_server = mcp_server

                # Extract tools from MCP server (get_tools is async)
                from ..mcp.tool_wrapper import create_mcp_tool_wrapper

                # Await async get_tools() call
                mcp_tools_dict = await mcp_server.get_tools()

                for tool_name, tool_func in mcp_tools_dict.items():
                    # Add description suffix to search_rem tool if schema specifies a default table
                    tool_suffix = search_rem_suffix if tool_name == "search_rem" else None

                    wrapped_tool = create_mcp_tool_wrapper(
                        tool_name,
                        tool_func,
                        user_id=context.user_id if context else None,
                        description_suffix=tool_suffix,
                    )
                    tools.append(wrapped_tool)
                    logger.debug(f"Loaded MCP tool: {tool_name}" + (" (with schema suffix)" if tool_suffix else ""))

                logger.info(f"Loaded {len(mcp_tools_dict)} tools from MCP server: {server_id} (in-process)")

            except Exception as e:
                logger.error(f"Failed to load MCP server {server_id}: {e}", exc_info=True)
        else:
            logger.warning(f"Unsupported MCP server type: {server_type}")

    # Convert resources to tools (MCP convenience syntax)
    # Resources declared in agent YAML become callable tools - eliminates
    # the artificial MCP distinction between tools and resources
    #
    # Supports both concrete and template URIs:
    # - Concrete: "rem://agents" -> no-param tool
    # - Template: "patient-profile://field/{field_key}" -> tool with field_key param
    from ..mcp.tool_wrapper import create_resource_tool

    # Collect all resource URIs from both resources section AND tools section
    resource_uris = []

    # From resources section (legacy format)
    if resource_configs:
        for resource_config in resource_configs:
            if hasattr(resource_config, 'uri'):
                uri = resource_config.uri
                usage = resource_config.description or ""
            else:
                uri = resource_config.get("uri", "")
                usage = resource_config.get("description", "")
            if uri:
                resource_uris.append((uri, usage))

    # From tools section - detect URIs (anything with ://)
    # This allows unified syntax: resources as tools
    tool_configs = metadata.tools if metadata and hasattr(metadata, 'tools') else []
    for tool_config in tool_configs:
        if hasattr(tool_config, 'name'):
            tool_name = tool_config.name
            tool_desc = tool_config.description or ""
        else:
            tool_name = tool_config.get("name", "")
            tool_desc = tool_config.get("description", "")

        # Auto-detect resource URIs (anything with :// scheme)
        if "://" in tool_name:
            resource_uris.append((tool_name, tool_desc))

    # Create tools from collected resource URIs
    # Pass the loaded MCP server so resources can be resolved from it
    logger.info(f"Creating {len(resource_uris)} resource tools with mcp_server={'set' if loaded_mcp_server else 'None'}")
    for uri, usage in resource_uris:
        resource_tool = create_resource_tool(uri, usage, mcp_server=loaded_mcp_server)
        tools.append(resource_tool)
        logger.debug(f"Loaded resource as tool: {uri}")

    # Create dynamic result_type from schema if not provided
    # Note: use_structured_output is set earlier from metadata.structured_output
    if result_type is None and agent_schema and "properties" in agent_schema:
        if use_structured_output:
            # Pre-process schema for Qwen compatibility (strips min/max, sets additionalProperties=False)
            # This ensures the generated Pydantic model doesn't have incompatible constraints
            sanitized_schema = _prepare_schema_for_qwen(agent_schema)
            result_type = _create_model_from_schema(sanitized_schema)
            logger.debug(f"Created dynamic Pydantic model: {result_type.__name__}")
        else:
            # Convert properties to prompt guidance instead of structured output
            # This informs the agent about expected response structure without forcing it
            properties_prompt = _convert_properties_to_prompt(agent_schema.get("properties", {}))
            if properties_prompt:
                system_prompt = system_prompt + "\n\n" + properties_prompt
            logger.debug("Structured output disabled - properties converted to prompt guidance")

    # Create agent with optional output_type for structured output and tools
    if result_type:
        # Wrap result_type to strip description if needed
        wrapped_result_type = _create_schema_wrapper(
            result_type, strip_description=strip_model_description
        )
        # Use InstrumentationSettings with version=3 to include agent name in span names
        from pydantic_ai.models.instrumented import InstrumentationSettings
        instrumentation = InstrumentationSettings(version=3) if settings.otel.enabled else False

        agent = Agent(
            model=model,
            name=agent_name,  # Used for OTEL span names (version 3: "invoke_agent {name}")
            system_prompt=system_prompt,
            output_type=wrapped_result_type,
            tools=tools,
            instrument=instrumentation,
            model_settings={"temperature": temperature},
            retries=settings.llm.max_retries,
        )
    else:
        from pydantic_ai.models.instrumented import InstrumentationSettings
        instrumentation = InstrumentationSettings(version=3) if settings.otel.enabled else False

        agent = Agent(
            model=model,
            name=agent_name,  # Used for OTEL span names (version 3: "invoke_agent {name}")
            system_prompt=system_prompt,
            tools=tools,
            instrument=instrumentation,
            model_settings={"temperature": temperature},
            retries=settings.llm.max_retries,
        )

    # TODO: Set agent context attributes for OTEL spans
    # if context:
    #     from ..otel import set_agent_context_attributes
    #     set_agent_context_attributes(context)

    return AgentRuntime(
        agent=agent,
        temperature=temperature,
        max_iterations=max_iterations,
    )
