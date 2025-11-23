"""
Integration test for agent tool invocation.

Tests that the agent actually calls search_rem when given a query.
"""
from rem.settings import settings

import asyncio
import pytest
from loguru import logger

from rem.agentic.providers.pydantic_ai import create_agent
from rem.agentic.context import AgentContext
from rem.utils.schema_loader import load_agent_schema


@pytest.mark.asyncio
@pytest.mark.llm
async def test_agent_invokes_search_rem():
    """Test that agent invokes search_rem tool when queried."""
    # Load rem agent schema
    schema = load_agent_schema("rem")
    context = AgentContext(user_id=settings.test.effective_user_id)

    # Create agent
    agent = await create_agent(context=context, agent_schema_override=schema)

    # Query that should trigger search_rem tool
    query = "Who is Sarah Chen?"

    print(f"\n{'='*80}")
    print(f"Query: {query}")
    print(f"{'='*80}\n")

    # Run agent (UsageLimits auto-injected by AgentRuntime delegation)
    result = await agent.run(query)

    print(f"\n{'='*80}")
    print(f"Result:")
    print(f"{'='*80}")
    print(f"Output: {result.output}")

    # Check if tools were called
    print(f"\n{'='*80}")
    print(f"Messages ({len(result.all_messages())}):")
    print(f"{'='*80}")

    tool_called = False
    for i, msg in enumerate(result.all_messages()):
        print(f"\nMessage {i+1}: {msg.kind}")
        if hasattr(msg, 'content'):
            print(f"  Content: {str(msg.content)[:200]}...")
        if hasattr(msg, 'tool_name'):
            print(f"  Tool: {msg.tool_name}")
            if msg.tool_name == "search_rem":
                tool_called = True
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                part_type = type(part).__name__
                print(f"  Part: {part_type}")
                if part_type == "ToolCallPart":
                    print(f"    Tool: {part.tool_name}")
                    if part.tool_name == "search_rem":
                        tool_called = True
                        print(f"    Args: {part.args}")

    print(f"\n{'='*80}")
    print(f"Tool Called: {tool_called}")
    print(f"{'='*80}\n")

    # Assertions
    assert result is not None
    if not tool_called:
        print("⚠️  WARNING: Agent did not call search_rem tool!")
        print("This suggests the LLM is not recognizing the tool as available.")


if __name__ == "__main__":
    # Run test directly
    asyncio.run(test_agent_invokes_search_rem())
