"""
REM Agents - Specialized agents for REM operations.

Most agents are defined as YAML schemas in src/rem/schemas/agents/.
Use create_agent_from_schema_file() to instantiate agents.

The SSE Simulator is a special programmatic "agent" that generates
scripted SSE events for testing and demonstration - it doesn't use an LLM.

Agent Manager provides functions for saving/loading user-created agents.
"""

from .sse_simulator import (
    stream_simulator_events,
    stream_minimal_demo,
    stream_error_demo,
)

from .agent_manager import (
    save_agent,
    get_agent,
    list_agents,
    delete_agent,
    build_agent_spec,
)

__all__ = [
    # SSE Simulator (programmatic, no LLM)
    "stream_simulator_events",
    "stream_minimal_demo",
    "stream_error_demo",
    # Agent Manager
    "save_agent",
    "get_agent",
    "list_agents",
    "delete_agent",
    "build_agent_spec",
]
