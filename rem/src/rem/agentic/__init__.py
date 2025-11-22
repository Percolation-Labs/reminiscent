"""
REM Agentic Framework.

Provider-agnostic agent orchestration with JSON Schema agents,
MCP tool integration, and structured output.
"""

from .context import AgentContext
from .query import AgentQuery
from .schema import (
    AgentSchema,
    AgentSchemaMetadata,
    MCPToolReference,
    MCPResourceReference,
    validate_agent_schema,
    create_agent_schema,
)
from .providers.pydantic_ai import create_agent_from_schema_file, create_agent
from .query_helper import ask_rem, REMQueryOutput

__all__ = [
    # Context and Query
    "AgentContext",
    "AgentQuery",
    # Schema Protocol
    "AgentSchema",
    "AgentSchemaMetadata",
    "MCPToolReference",
    "MCPResourceReference",
    "validate_agent_schema",
    "create_agent_schema",
    # Agent Factories
    "create_agent_from_schema_file",
    "create_agent",
    # REM Query Helpers
    "ask_rem",
    "REMQueryOutput",
]
