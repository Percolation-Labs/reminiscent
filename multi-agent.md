# Multi-Agent Design Document

## Implementation Status

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 | ✅ Complete | Context propagation via ContextVar |
| Phase 1 | ✅ Complete | Agent schema in metadata |
| Phase 2 | 🔜 Future | SSE event relay (nested agent events) |
| Phase 3 | ✅ Complete | `ask_agent` MCP tool |
| Phase 4 | ✅ Complete | Integration tests |

## Overview

This document outlines enhancements to REM's multi-agent capabilities, focusing on:
1. ✅ Automatic agent schema storage in metadata
2. 🔜 SSE event propagation from child agents to parent orchestrators (future)
3. ✅ A new `ask_agent` MCP tool for agent-to-agent communication

---

## Current State

### Architecture Summary

| Component | Location | Purpose |
|-----------|----------|---------|
| MCP Tools | `rem/src/rem/api/mcp_router/tools.py` | Tool definitions including `ask_rem_agent`, `register_metadata`, `save_agent` |
| SSE Events | `rem/src/rem/api/routers/chat/sse_events.py` | Event types: `text_delta`, `metadata`, `tool_call`, `progress`, etc. |
| Streaming | `rem/src/rem/api/routers/chat/streaming.py` | Agent execution with SSE emission |
| Agent Factory | `rem/src/rem/agentic/providers/pydantic_ai.py` | `create_agent()` function |
| Agent Manager | `rem/src/rem/agentic/agents/agent_manager.py` | CRUD operations for agent schemas |
| Schema Model | `rem/src/rem/models/entities/schema.py` | Database entity for agent storage |

### Current Limitations

1. **No agent-to-agent tool**: `ask_rem_agent` is hardcoded for REM query translation only
2. **No SSE propagation**: Child agent events are not relayed to parent
3. **Agent schema not auto-stored**: When `register_metadata` is called, the originating agent schema is not automatically included
4. **Context not propagated to child agents**: Critical issue - parent agent context is NOT passed to called agents

### Critical Issue: Context Loss in Tool Calls

When `ask_rem_agent` is called, it creates a **new context** rather than inheriting from the caller:

```python
# Current behavior in tools.py (lines 412-416)
context = AgentContext(
    user_id=user_id,
    tenant_id=user_id or "default",  # WRONG: loses parent's tenant_id
    default_model=settings.llm.default_model,  # WRONG: ignores parent's model
    # MISSING: session_id, is_eval, agent_schema_uri from parent
)
```

**What gets lost:**
- `session_id` - Child agent has no session continuity with parent
- `tenant_id` - Falls back to user_id instead of parent's tenant
- `default_model` - Uses global default, not parent's override
- `is_eval` - Evaluation mode flag not propagated
- Parent's `agent_schema_uri` - No lineage tracking

**Root cause:** MCP tools are stateless functions. They receive only their declared parameters, not the execution context of the calling agent. FastMCP does not provide a mechanism to inject context into tool calls.

---

## Design Goals

### 1. Automatic Agent Schema in Metadata

When `register_metadata()` is called or metadata is auto-generated, include the agent schema being used.

**Current behavior** (`streaming.py:550-580`):
```python
# Default metadata emitted at end of response
yield format_sse_event(MetadataEvent(
    message_id=message_id,
    agent_schema=agent_schema,  # Already passed through
    confidence=registered_confidence,
    ...
))
```

**Enhancement needed**:
- Ensure `agent_schema` is always populated from context
- Store `agent_schema` in assistant message metadata when persisting

**Files to modify**:
- `rem/src/rem/api/routers/chat/streaming.py` - Ensure agent_schema flows to metadata
- `rem/src/rem/api/mcp_router/tools.py` - `register_metadata()` should accept optional `agent_schema` override

### 2. SSE Event Propagation for Multi-Agent

When a parent agent calls a child agent via `ask_agent`, the child's SSE events should propagate to the parent's stream.

**Event flow**:
```
User Request
    │
    ▼
Parent Agent (e.g., orchestrator)
    │
    ├── text_delta: "I'll analyze this using..."
    │
    ├── tool_call: ask_agent("sentiment-analyzer", {...})
    │       │
    │       ▼
    │   Child Agent (sentiment-analyzer)
    │       ├── text_delta: "Analyzing sentiment..."  ← PROPAGATE
    │       ├── progress: {step: "processing"}        ← PROPAGATE
    │       ├── metadata: {confidence: 0.95}          ← PROPAGATE
    │       └── done                                  ← PROPAGATE
    │
    ├── tool_result: {sentiment: "positive", ...}
    │
    └── text_delta: "The analysis shows..."
```

**Event wrapping for nested agents**:
```python
class NestedAgentEvent(BaseModel):
    """Wrapper for events from child agents"""
    parent_message_id: str
    child_agent: str        # Agent schema name
    child_message_id: str
    event: SSEEvent         # Original event from child
    depth: int = 1          # Nesting level
```

### 3. New `ask_agent` MCP Tool

A general-purpose tool for invoking any registered agent.

**Signature**:
```python
async def ask_agent(
    agent_name: str,
    input_text: str,
    input_data: dict[str, Any] | None = None,
    stream_events: bool = True,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """
    Invoke another agent by name and return its response.

    Args:
        agent_name: Name of the agent schema (e.g., "sentiment-analyzer")
        input_text: The user message/query to send to the agent
        input_data: Optional structured input matching agent's expected schema
        stream_events: If True, propagate child's SSE events to parent stream
        timeout_seconds: Maximum execution time

    Returns:
        {
            "status": "success" | "error",
            "output": {...},           # Agent's structured output
            "text_response": "...",    # Agent's text response
            "metadata": {...},         # Registered metadata from child
            "agent_schema": "...",     # Child agent's schema name
            "trace_id": "...",         # OTEL trace for debugging
        }
    """
```

---

## Implementation Plan

### Phase 0: Context Propagation (PREREQUISITE)

**This must be done first** - without it, child agents lose user context.

**Task 0.1**: Add ContextVar to AgentContext
- File: `rem/src/rem/agentic/context.py`
- Add `_current_agent_context` ContextVar
- Add `get_current_context()` and `set_current_context()` functions
- Add `@contextmanager` for scoped context setting

**Task 0.2**: Set context in streaming layer
- File: `rem/src/rem/api/routers/chat/streaming.py`
- Wrap agent execution with context setting
- Ensure context is cleared after execution (even on error)

**Task 0.3**: Set context in CLI/direct invocation
- File: `rem/src/rem/agentic/providers/pydantic_ai.py`
- Set context when running agents directly (not via API)

**Task 0.4**: Fix existing `ask_rem_agent` to use context
- File: `rem/src/rem/api/mcp_router/tools.py`
- Update to inherit from parent context via ContextVar
- Keep explicit `user_id` parameter as override

### Phase 1: Agent Schema in Metadata (Low Risk)

**Task 1.1**: Ensure agent_schema flows through streaming
- File: `rem/src/rem/api/routers/chat/streaming.py`
- Verify `agent_schema` is extracted from context and included in all MetadataEvents
- Add to message persistence (assistant message metadata)

**Task 1.2**: Enhance register_metadata tool
- File: `rem/src/rem/api/mcp_router/tools.py`
- Add optional `agent_schema` parameter (auto-populated from context if not provided)

**Task 1.3**: Store in assistant response metadata
- File: `rem/src/rem/api/routers/chat/streaming.py`
- When saving assistant message, include `agent_schema` in metadata field

### Phase 2: SSE Event Propagation (Medium Complexity)

**Task 2.1**: Create event relay mechanism
- New file: `rem/src/rem/agentic/multi_agent/event_relay.py`
- Define `NestedAgentEvent` wrapper
- Create async generator for relaying child events

**Task 2.2**: Modify agent execution for nested calls
- File: `rem/src/rem/agentic/providers/pydantic_ai.py`
- Add optional event callback to `run_agent_streaming()`
- Support passing parent's event emitter to child

**Task 2.3**: Integrate with streaming layer
- File: `rem/src/rem/api/routers/chat/streaming.py`
- When processing `ask_agent` tool call, intercept child's event stream
- Re-emit wrapped events to parent stream

### Phase 3: ask_agent Tool (Core Feature)

**Task 3.1**: Implement ask_agent tool
- File: `rem/src/rem/api/mcp_router/tools.py`
- Load agent by name from schemas table (via agent_manager)
- Create child AgentContext inheriting parent's session
- Execute agent with event relay

**Task 3.2**: Register in MCP server
- File: `rem/src/rem/api/mcp_router/server.py`
- Add `mcp.tool()(ask_agent)` registration

**Task 3.3**: Add to default REM agent tools
- File: `rem/schemas/agents/rem.json` (or equivalent)
- Include `ask_agent` in tools list with usage instructions

### Phase 4: Testing & Validation

**Test 4.1**: Self-referential test
- Create test agent that calls itself (with recursion limit)
- Verify events propagate correctly

**Test 4.2**: Orchestrator pattern test
- Create orchestrator agent with multiple child agents
- Verify parallel execution works
- Verify metadata aggregation

**Test 4.3**: Integration test
- File: `rem/tests/integration/test_multi_agent.py`
- Test event ordering, metadata propagation, error handling

---

## Technical Details

### Event Propagation Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Parent Agent Stream                      │
│                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │  text_delta  │───▶│  tool_call   │───▶│  tool_result │  │
│  │  (direct)    │    │  ask_agent   │    │  (merged)    │  │
│  └──────────────┘    └──────┬───────┘    └──────────────┘  │
│                             │                               │
│                             ▼                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Child Agent Execution                    │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐           │   │
│  │  │ text_δ   │  │ progress │  │ metadata │   ...     │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘           │   │
│  └───────┼─────────────┼─────────────┼─────────────────┘   │
│          │             │             │                      │
│          ▼             ▼             ▼                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Wrapped & Re-emitted to Client               │   │
│  │  NestedAgentEvent { child_agent, depth, event }     │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Context Inheritance

Child agents inherit from parent context:
```python
child_context = AgentContext(
    user_id=parent_context.user_id,          # Same user scope
    tenant_id=parent_context.tenant_id,      # Same tenant
    session_id=parent_context.session_id,    # Same session for continuity
    default_model=parent_context.default_model,
    agent_schema_uri=f"rem://schema/{agent_name}",
    is_eval=parent_context.is_eval,
    parent_trace_id=parent_context.trace_id, # NEW: trace correlation
)
```

### Context Propagation Solution

Since MCP tools are stateless, we need to pass context explicitly. Two approaches:

#### Option A: Context as Tool Parameter (Explicit)

Add optional context fields to `ask_agent` tool:

```python
async def ask_agent(
    agent_name: str,
    input_text: str,
    # Context propagation fields (optional, auto-populated if available)
    user_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    model_override: str | None = None,
    is_eval: bool = False,
    parent_agent_schema: str | None = None,  # For lineage tracking
    parent_trace_id: str | None = None,      # For OTEL correlation
) -> dict[str, Any]:
```

**Pros:** Explicit, works with any MCP client
**Cons:** Verbose, requires caller to pass context fields

#### Option B: Context via ContextVar (Implicit) - RECOMMENDED

Use Python's `contextvars` to thread context through tool calls:

```python
# In rem/src/rem/agentic/context.py
from contextvars import ContextVar

# Thread-local context for current agent execution
_current_agent_context: ContextVar[AgentContext | None] = ContextVar(
    "current_agent_context", default=None
)

def get_current_context() -> AgentContext | None:
    """Get the current agent context from context var."""
    return _current_agent_context.get()

def set_current_context(ctx: AgentContext) -> None:
    """Set the current agent context."""
    _current_agent_context.set(ctx)
```

Then in streaming.py, set context before tool execution:
```python
# Before running agent
set_current_context(context)
try:
    result = await agent.run(...)
finally:
    set_current_context(None)
```

And in tools.py, retrieve context:
```python
async def ask_agent(agent_name: str, input_text: str, ...) -> dict:
    # Get parent context from contextvar
    parent_context = get_current_context()

    # Build child context inheriting from parent
    child_context = AgentContext(
        user_id=parent_context.user_id if parent_context else user_id,
        tenant_id=parent_context.tenant_id if parent_context else "default",
        session_id=parent_context.session_id if parent_context else None,
        default_model=parent_context.default_model if parent_context else settings.llm.default_model,
        is_eval=parent_context.is_eval if parent_context else False,
        agent_schema_uri=agent_name,
    )
```

**Pros:** Transparent, no API changes, works with existing tools
**Cons:** Implicit behavior, requires async context propagation

#### Option C: Hybrid Approach - BEST

- Use ContextVar for automatic propagation
- Allow explicit overrides via parameters
- Parameters take precedence over contextvar

```python
async def ask_agent(
    agent_name: str,
    input_text: str,
    # Explicit overrides (optional)
    user_id: str | None = None,
    session_id: str | None = None,
    model_override: str | None = None,
) -> dict[str, Any]:
    parent_context = get_current_context()

    child_context = AgentContext(
        # Explicit > Parent > Default
        user_id=user_id or (parent_context.user_id if parent_context else None),
        session_id=session_id or (parent_context.session_id if parent_context else None),
        default_model=model_override or (parent_context.default_model if parent_context else settings.llm.default_model),
        # Always inherit these from parent if available
        tenant_id=parent_context.tenant_id if parent_context else "default",
        is_eval=parent_context.is_eval if parent_context else False,
    )
```

### Metadata Aggregation

Parent agent can aggregate child metadata:
```python
# In parent's response metadata
{
    "agent_schema": "orchestrator",
    "child_agents": [
        {
            "agent": "sentiment-analyzer",
            "confidence": 0.95,
            "trace_id": "abc123"
        },
        {
            "agent": "entity-extractor",
            "confidence": 0.87,
            "trace_id": "def456"
        }
    ],
    "aggregated_confidence": 0.91  # Computed from children
}
```

### Error Handling

```python
class ChildAgentError(Exception):
    """Raised when a child agent fails"""
    def __init__(
        self,
        agent_name: str,
        error_message: str,
        trace_id: str | None = None,
    ):
        self.agent_name = agent_name
        self.error_message = error_message
        self.trace_id = trace_id
```

On child failure:
1. Emit `error` event with child context
2. Return error result to parent tool call
3. Parent can retry or handle gracefully

---

## Usage Examples

### Example 1: Simple Agent Call

```python
# From an orchestrator agent's tool call
result = await ask_agent(
    agent_name="sentiment-analyzer",
    input_text="I love this product! Best purchase ever.",
)
# Returns: {"status": "success", "output": {"sentiment": "positive", "score": 0.95}}
```

### Example 2: Orchestrator Pattern

Agent schema for orchestrator:
```json
{
    "type": "object",
    "description": "You are an orchestrator that coordinates multiple specialized agents to answer complex queries. Use ask_agent to delegate to specialists.",
    "properties": {
        "analysis_summary": {"type": "string"},
        "specialist_results": {"type": "array"}
    },
    "json_schema_extra": {
        "kind": "agent",
        "name": "orchestrator",
        "tools": [
            {"name": "ask_agent", "mcp_server": "rem"},
            {"name": "search_rem", "mcp_server": "rem"}
        ]
    }
}
```

### Example 3: Self-Test (Agent Calls Itself)

```python
# Create a simple echo agent that can call itself
await save_agent(
    name="echo-agent",
    description="Echo the input. If depth < 3, call yourself with depth+1.",
    tools=["ask_agent"],
    ...
)

# Test: ask_agent("echo-agent", "test", {"depth": 0})
# Expected: 3 levels of nested events, then final response
```

---

## Configuration

### New Settings (optional)

```python
# rem/src/rem/settings.py
class MultiAgentSettings(BaseSettings):
    max_nesting_depth: int = 5           # Prevent infinite recursion
    event_relay_enabled: bool = True      # Can disable for performance
    child_timeout_seconds: int = 300      # Per-child timeout
    aggregate_metadata: bool = True       # Auto-aggregate child metadata
```

---

## Migration Notes

### Backwards Compatibility

- Existing agents continue to work unchanged
- `ask_rem_agent` remains for REM-specific queries
- `ask_agent` is a new, general-purpose alternative

### Gradual Rollout

1. Deploy Phase 1 (metadata) first - no API changes
2. Deploy Phase 2 (event relay) - new event types, clients can ignore
3. Deploy Phase 3 (ask_agent tool) - new capability

---

## Open Questions

1. **Recursion limits**: Should there be a hard limit on nesting depth? (Proposed: 5)
2. **Parallel execution**: Should `ask_agent` support calling multiple agents in parallel?
3. **Caching**: Should child agent responses be cached for identical inputs?
4. **Rate limiting**: Should child agent calls count against parent's rate limits?

---

## Success Criteria

1. **Metadata includes agent schema**: All MetadataEvents include originating agent
2. **Events propagate**: Client sees all child agent events with proper nesting context
3. **ask_agent works**: Can invoke any registered agent from another agent
4. **Self-test passes**: Agent can call itself with proper recursion handling
5. **Orchestrator pattern**: Multi-agent workflows execute correctly

---

## Files to Create/Modify

### New Files
- `rem/src/rem/agentic/multi_agent/__init__.py`
- `rem/src/rem/agentic/multi_agent/event_relay.py`
- `rem/tests/integration/test_multi_agent.py`

### Modified Files

**Phase 0 (Context Propagation):**
- `rem/src/rem/agentic/context.py` - Add ContextVar, get/set functions
- `rem/src/rem/api/routers/chat/streaming.py` - Set context before agent execution
- `rem/src/rem/agentic/providers/pydantic_ai.py` - Set context for CLI/direct calls
- `rem/src/rem/api/mcp_router/tools.py` - Fix `ask_rem_agent` to use parent context

**Phase 1-3 (Multi-Agent):**
- `rem/src/rem/api/mcp_router/tools.py` - Add `ask_agent` tool
- `rem/src/rem/api/mcp_router/server.py` - Register new tool
- `rem/src/rem/api/routers/chat/streaming.py` - Event relay integration
- `rem/src/rem/api/routers/chat/sse_events.py` - Add `NestedAgentEvent` type
- `rem/src/rem/agentic/providers/pydantic_ai.py` - Event callback support
- `rem/src/rem/agentic/agents/agent_manager.py` - Helper for nested execution

---

## Summary

The key insight is that **context propagation is the foundation** for multi-agent support. Without it:
- Child agents can't access user-scoped data
- Session continuity is broken
- Model overrides are lost
- Evaluation mode isn't respected

The recommended approach uses Python's `contextvars` (Option C - Hybrid) to:
1. Automatically inherit context from parent agent
2. Allow explicit overrides when needed
3. Work transparently with existing code
