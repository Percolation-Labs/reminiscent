"""
Integration test for agent using MCP tools end-to-end.

Tests the full workflow:
1. Agent receives natural language question
2. Agent automatically invokes search_rem tool
3. Tool executes REM query
4. Agent synthesizes answer from results

This is the complete user experience - if this passes, we know the system works.
"""
import asyncio
import pytest
from rem.agentic import create_agent
from rem.agentic.context import AgentContext
from rem.utils.schema_loader import load_agent_schema
from rem.settings import settings


@pytest.mark.asyncio
@pytest.mark.llm
async def test_agent_uses_search_rem_tool():
    """Test agent automatically uses search_rem tool to answer questions."""
    print("\n" + "=" * 80)
    print("Testing: Agent with MCP tools (full end-to-end)")
    print("=" * 80)

    # Create agent with REM schema (has search_rem tool)
    schema = load_agent_schema('rem')
    context = AgentContext(user_id=settings.test.effective_user_id)
    agent = await create_agent(context=context, agent_schema_override=schema)

    print("\n✓ Agent created with REM schema")
    print(f"  Tools available: {len(agent.agent.tools) if hasattr(agent, 'agent') and hasattr(agent.agent, 'tools') else 'N/A'}")

    # Ask a question that requires using the search_rem tool
    query = "Who is Sarah Chen?"
    print(f"\n✓ Asking agent: '{query}'")

    result = await agent.run(query)

    print(f"\n✓ Agent response received")
    print(f"  Response type: {type(result.output)}")

    # Inspect all messages to see tool calls
    tool_calls_found = []
    tool_returns_found = []

    for i, msg in enumerate(result.all_messages()):
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                part_type = type(part).__name__

                if part_type == 'ToolCallPart':
                    tool_calls_found.append({
                        'tool_name': part.tool_name,
                        'args': part.args
                    })
                    print(f"\n  [Message {i}] Tool Call: {part.tool_name}")
                    print(f"    Args: {part.args}")

                elif part_type == 'ToolReturnPart':
                    tool_returns_found.append({
                        'tool_name': part.tool_name,
                        'content': str(part.content)[:200]  # First 200 chars
                    })
                    print(f"\n  [Message {i}] Tool Return: {part.tool_name}")
                    print(f"    Content preview: {str(part.content)[:200]}...")

    # Assertions
    print("\n" + "=" * 80)
    print("Validation:")
    print("=" * 80)

    assert len(tool_calls_found) > 0, "Agent should have called at least one tool"
    print(f"✓ Agent called {len(tool_calls_found)} tool(s)")

    # Check that search_rem was called
    search_rem_calls = [tc for tc in tool_calls_found if tc['tool_name'] == 'search_rem']
    assert len(search_rem_calls) > 0, "Agent should have called search_rem tool"
    print(f"✓ search_rem tool was called {len(search_rem_calls)} time(s)")

    # Check the first search_rem call had correct structure
    first_call = search_rem_calls[0]
    assert 'query_type' in first_call['args'], "search_rem call should have query_type parameter"
    assert first_call['args']['query_type'].lower() in ['lookup', 'fuzzy', 'search'], \
        f"query_type should be valid REM query type, got: {first_call['args']['query_type']}"
    print(f"✓ search_rem called with query_type: {first_call['args']['query_type']}")

    # Check tool returned results
    assert len(tool_returns_found) > 0, "Tools should have returned results"
    print(f"✓ Tools returned {len(tool_returns_found)} result(s)")

    # Check agent produced a response
    assert result.output is not None, "Agent should produce an output"
    print(f"✓ Agent produced output: {type(result.output).__name__}")

    # Check response mentions Sarah Chen (basic sanity check)
    response_text = str(result.output)
    assert 'sarah' in response_text.lower() or 'chen' in response_text.lower(), \
        "Agent response should mention Sarah Chen"
    print(f"✓ Agent response mentions Sarah Chen")

    print("\n" + "=" * 80)
    print("Final Agent Response:")
    print("=" * 80)
    print(response_text)
    print("=" * 80)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_agent_multi_turn_reasoning():
    """Test agent can do multi-turn reasoning with multiple tool calls."""
    print("\n" + "=" * 80)
    print("Testing: Multi-turn reasoning with tools")
    print("=" * 80)

    schema = load_agent_schema('rem')
    context = AgentContext(user_id=settings.test.effective_user_id)
    agent = await create_agent(context=context, agent_schema_override=schema)

    # More complex question that might require multiple queries
    query = "What is Sarah Chen's role and who does she manage?"
    print(f"\n✓ Asking agent: '{query}'")

    result = await agent.run(query)

    # Count tool calls
    tool_calls = []
    for msg in result.all_messages():
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                if type(part).__name__ == 'ToolCallPart':
                    tool_calls.append(part.tool_name)

    print(f"\n✓ Agent made {len(tool_calls)} tool call(s): {tool_calls}")

    # Agent should call at least one tool
    assert len(tool_calls) > 0, "Agent should call tools for this question"

    # Check response quality
    response_text = str(result.output).lower()
    assert 'sarah' in response_text or 'chen' in response_text, \
        "Response should mention Sarah Chen"

    print(f"\n✓ Agent response:")
    print(str(result.output))


if __name__ == "__main__":
    print("=" * 80)
    print("Test 1: Agent uses search_rem tool")
    print("=" * 80)
    asyncio.run(test_agent_uses_search_rem_tool())

    print("\n" + "=" * 80)
    print("Test 2: Multi-turn reasoning")
    print("=" * 80)
    asyncio.run(test_agent_multi_turn_reasoning())

    print("\n" + "=" * 80)
    print("✅ All Agent + Tools Tests Passed!")
    print("=" * 80)
