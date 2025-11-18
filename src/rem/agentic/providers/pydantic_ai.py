"""
Pydantic AI agent factory with dynamic JsonSchema to Pydantic model conversion.

Key Design Pattern 
1. JsonSchema → Pydantic Model (json-schema-to-pydantic library)
2. Agent schema contains both system prompt AND output schema
3. MCP tools loaded dynamically from schema metadata
4. Result type can be stripped of description to avoid duplication with system prompt
5. OTEL instrumentation conditional based on settings

Unique Design 
- Agent schemas are JSON Schema with embedded metadata:
  - description: System prompt for agent
  - properties: Output schema fields
  - json_schema_extra.tools: MCP tool configurations
  - json_schema_extra.resources: MCP resource configurations

- Dynamic model creation from schema using json-schema-to-pydantic
- Tools and resources loaded from MCP servers via schema config
- Stripped descriptions to avoid LLM schema bloat

Example Agent Schema:
{
  "type": "object",
  "description": "Agent that answers REM queries...",
  "properties": {
    "answer": {"type": "string", "description": "Query answer"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  },
  "required": ["answer", "confidence"],
  "json_schema_extra": {
    "fully_qualified_name": "rem.agents.QueryAgent",
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

    # Override model name with FQN if available
    fqn = agent_schema.get("json_schema_extra", {}).get("fully_qualified_name")
    if fqn:
        class_name = fqn.rsplit(".", 1)[-1]
        model.__name__ = class_name
        model.__qualname__ = class_name

    logger.debug(
        f"Created Pydantic model '{model.__name__}' from JSON Schema with fields: "
        f"{list(model.model_fields.keys())}"
    )

    return model


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
            return schema

    # Preserve original model name for debugging
    SchemaWrapper.__name__ = result_type.__name__
    return SchemaWrapper


async def create_pydantic_ai_agent(
    context: AgentContext | None = None,
    agent_schema_override: dict[str, Any] | None = None,
    model_override: KnownModelName | Model | None = None,
    result_type: type[BaseModel] | None = None,
    strip_model_description: bool = True,
) -> Agent:
    """
    Create Pydantic AI agent from context with dynamic schema loading.

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
        agent = await create_pydantic_ai_agent(context)

        # With explicit schema and result type
        schema = {...}  # JSON Schema
        class Output(BaseModel):
            answer: str
            confidence: float

        agent = await create_pydantic_ai_agent(
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

    # Determine model: override > context.default_model > settings
    model = (
        model_override or (context.default_model if context else settings.llm.default_model)
    )

    # Extract schema fields
    system_prompt = agent_schema.get("description", "") if agent_schema else ""
    metadata = agent_schema.get("json_schema_extra", {}) if agent_schema else {}
    tool_configs = metadata.get("tools", [])
    resource_configs = metadata.get("resources", [])

    logger.info(
        f"Creating agent: model={model}, tools={len(tool_configs)}, resources={len(resource_configs)}"
    )

    # Set agent resource attributes for OTEL (before creating agent)
    if settings.otel.enabled and agent_schema:
        from ..otel import set_agent_resource_attributes

        set_agent_resource_attributes(agent_schema=agent_schema)

    # Build list of Tool instances from tool and resource configs
    tools = []
    if tool_configs:
        # TODO: Load MCP tools dynamically
        # from ..mcp.tool_wrapper import build_mcp_tools
        # tools = await build_mcp_tools(tool_configs)
        pass

    if resource_configs:
        # TODO: Convert resources to tools (MCP convenience syntax)
        # from ..mcp.tool_wrapper import build_resource_tools
        # resource_tools = build_resource_tools(resource_configs)
        # tools.extend(resource_tools)
        pass

    # Create dynamic result_type from schema if not provided
    if result_type is None and agent_schema and "properties" in agent_schema:
        result_type = _create_model_from_schema(agent_schema)
        logger.debug(f"Created dynamic Pydantic model: {result_type.__name__}")

    # Create agent with optional output_type for structured output and tools
    if result_type:
        # Wrap result_type to strip description if needed
        wrapped_result_type = _create_schema_wrapper(
            result_type, strip_description=strip_model_description
        )
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            output_type=wrapped_result_type,
            tools=tools,
            instrument=settings.otel.enabled,  # Conditional OTEL instrumentation
        )
    else:
        agent = Agent(
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            instrument=settings.otel.enabled,
        )

    # TODO: Set agent context attributes for OTEL spans
    # if context:
    #     from ..otel import set_agent_context_attributes
    #     set_agent_context_attributes(context)

    return agent
