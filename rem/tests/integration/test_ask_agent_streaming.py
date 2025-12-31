"""Minimal test for ask_agent streaming."""
import asyncio
import pytest
from rem.agentic.context import AgentContext, agent_context_scope, set_event_sink
from rem.api.mcp_router.tools import ask_agent


@pytest.mark.asyncio
@pytest.mark.llm
async def test_ask_agent_streams_child_content():
    """ask_agent should push child_content events to the queue."""
    queue: asyncio.Queue = asyncio.Queue()
    ctx = AgentContext(user_id="test", tenant_id="test", session_id="test", default_model="openai:gpt-4o-mini")

    set_event_sink(queue)
    try:
        with agent_context_scope(ctx):
            result = await ask_agent(agent_name="rem", input_text="Say: hello")
    finally:
        set_event_sink(None)

    # Collect events
    events = []
    while not queue.empty():
        events.append(await queue.get())

    print(f"\nEvents: {len(events)}")
    for e in events:
        print(f"  {e.get('type')}: {str(e)[:80]}")
    print(f"\nResult: {result}")

    # Must have child_content events
    content_events = [e for e in events if e.get("type") == "child_content"]
    assert len(content_events) > 0, f"No child_content events! Got: {events}"

    # text_response should NOT be in result if content was streamed
    if "text_response" in result:
        print(f"\n⚠ text_response present (duplication source): {result['text_response'][:50]}...")
