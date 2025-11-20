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
]
