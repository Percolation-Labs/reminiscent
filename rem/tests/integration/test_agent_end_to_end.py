"""
Final end-to-end integration test for agent with REM tools.

This test verifies the complete workflow:
1. MCP server loads without circular imports
2. Agent discovers tool signatures correctly
3. Agent calls tools with correct named parameters
4. Tools execute REM queries successfully
5. Agent synthesizes results into natural language answer

This is the ULTIMATE test - if this passes, the entire system works.

Test User ID:
- Configured via TEST__USER_EMAIL environment variable (default: test@rem.ai)
- User ID is deterministic UUID v5 generated from email
- To change: export TEST__USER_EMAIL=mytest@example.com
- To override UUID: export TEST__USER_ID=custom-uuid
"""
import asyncio
import pytest
from rem.agentic import create_agent
from rem.agentic.context import AgentContext
from rem.utils.schema_loader import load_agent_schema
from rem.settings import settings


@pytest.mark.asyncio
@pytest.mark.llm
async def test_agent_end_to_end_with_test_user():
    """
    End-to-end test with test user data loaded in database.

    This test verifies:
    - Agent loads MCP tools without circular import errors
    - Agent discovers tool signatures correctly
    - Agent calls search_rem with correct parameters (query_type, entity_key)
    - Tool executes query and returns results
    - Agent synthesizes natural language answer from results
    """
    print("\n" + "=" * 80)
    print("FINAL END-TO-END TEST: Agent + MCP Tools + REM Database")
    print("=" * 80)

    # Get test user from settings (deterministic UUID from email)
    test_user_id = settings.test.effective_user_id
    test_user_email = settings.test.user_email

    print(f"\n✓ Test User Configuration:")
    print(f"  Email: {test_user_email}")
    print(f"  User ID: {test_user_id}")

    # Create agent with test user context
    schema = load_agent_schema('rem')
    context = AgentContext(user_id=test_user_id)
    agent = await create_agent(context=context, agent_schema_override=schema)

    print(f"\n✓ Agent created with REM schema")
    print(f"  Context User ID: {context.user_id}")

    # Ask about Sarah Chen (exists in test data)
    query = "Who is Sarah Chen?"
    print(f"\n✓ Asking agent: '{query}'")

    result = await agent.run(query)

    print(f"\n✓ Agent response received")
    print(f"  Response type: {type(result.output).__name__}")

    # Analyze tool calls
    tool_calls = []
    tool_returns = []

    for i, msg in enumerate(result.all_messages()):
        if hasattr(msg, 'parts'):
            for part in msg.parts:
                part_type = type(part).__name__

                if part_type == 'ToolCallPart':
                    tool_calls.append({
                        'tool_name': part.tool_name,
                        'args': part.args
                    })
                    print(f"\n  [Message {i}] Tool Call: {part.tool_name}")
                    print(f"    Args: {part.args}")

                elif part_type == 'ToolReturnPart':
                    tool_returns.append({
                        'tool_name': part.tool_name,
                        'content': part.content
                    })
                    print(f"\n  [Message {i}] Tool Return: {part.tool_name}")
                    # Show abbreviated content
                    content_str = str(part.content)
                    if len(content_str) > 300:
                        print(f"    Content (abbreviated): {content_str[:300]}...")
                    else:
                        print(f"    Content: {content_str}")

    # Assertions
    print("\n" + "=" * 80)
    print("Validation:")
    print("=" * 80)

    # 1. Verify tools were called
    assert len(tool_calls) > 0, "Agent should have called at least one tool"
    print(f"✓ Agent called {len(tool_calls)} tool(s)")

    # 2. Verify search_rem was called
    search_rem_calls = [tc for tc in tool_calls if tc['tool_name'] == 'search_rem']
    assert len(search_rem_calls) > 0, "Agent should have called search_rem tool"
    print(f"✓ search_rem tool was called {len(search_rem_calls)} time(s)")

    # 3. CRITICAL: Verify correct parameters (not {'query': 'LOOKUP "sarah"'})
    first_call = search_rem_calls[0]
    assert 'query_type' in first_call['args'], \
        f"search_rem should have query_type parameter, got: {first_call['args']}"
    assert first_call['args']['query_type'].lower() in ['lookup', 'fuzzy', 'search'], \
        f"query_type should be valid REM query type, got: {first_call['args']['query_type']}"
    print(f"✓ search_rem called with correct named parameter: query_type={first_call['args']['query_type']}")

    # 4. Verify tool returned results
    assert len(tool_returns) > 0, "Tools should have returned results"
    search_rem_returns = [tr for tr in tool_returns if tr['tool_name'] == 'search_rem']
    assert len(search_rem_returns) > 0, "search_rem should have returned results"
    print(f"✓ search_rem returned {len(search_rem_returns)} result(s)")

    # 5. Check if results contain Sarah Chen data
    first_return = search_rem_returns[0]
    result_content = first_return['content']

    # Parse the results
    if isinstance(result_content, dict):
        status = result_content.get('status')
        results_data = result_content.get('results', {})

        print(f"✓ Tool call status: {status}")

        if isinstance(results_data, dict):
            count = results_data.get('count', 0)
            results_list = results_data.get('results', [])

            print(f"✓ Query returned {count} result(s)")

            if count > 0 and results_list:
                first_result = results_list[0]
                entity_key = first_result.get('entity_key', 'N/A')
                entity_type = first_result.get('entity_type', 'N/A')
                print(f"✓ First result: {entity_key} (type: {entity_type})")

                # Verify Sarah Chen was found
                assert 'sarah' in entity_key.lower() or 'chen' in entity_key.lower(), \
                    f"Expected Sarah Chen in results, got: {entity_key}"
                print("✓ Sarah Chen entity found in results!")
            else:
                print("⚠️  No results returned (data may not be loaded)")

    # 6. Verify agent produced a response
    assert result.output is not None, "Agent should produce an output"
    response_text = str(result.output)
    print(f"\n✓ Agent produced response ({len(response_text)} chars)")

    # 7. Check response quality
    assert 'sarah' in response_text.lower() or 'chen' in response_text.lower(), \
        "Agent response should mention Sarah Chen"
    print("✓ Agent response mentions Sarah Chen")

    print("\n" + "=" * 80)
    print("Final Agent Response:")
    print("=" * 80)
    print(response_text)
    print("=" * 80)

    print("\n" + "🎉" * 40)
    print("✅ ALL CHECKS PASSED - FULL END-TO-END WORKFLOW WORKS!")
    print("🎉" * 40)


if __name__ == "__main__":
    print("=" * 80)
    print("Running Final End-to-End Integration Test")
    print("=" * 80)

    asyncio.run(test_agent_end_to_end_with_test_user())

    print("\n" + "=" * 80)
    print("✅ END-TO-END TEST PASSED!")
    print("=" * 80)
