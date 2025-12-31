"""
Integration test for multi-agent delegation streaming.

Tests that when an orchestrator agent delegates to a child agent via ask_agent,
the child's text_response is:
1. Streamed to the client as content chunks (SSE)
2. Saved to the session as an assistant message

This requires a running REM API with postgres.
Run with: POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem" pytest tests/integration/test_agent_delegation_streaming.py -v -s
"""

import asyncio
import json
import uuid
import httpx
import pytest
from pathlib import Path

# Test configuration
API_BASE = "http://localhost:8000"
TEST_USER_ID = "test-user-streaming"


@pytest.fixture
def session_id():
    """Generate a unique session ID for each test."""
    return str(uuid.uuid4())


@pytest.fixture
def orchestrator_schema(tmp_path):
    """Create a temporary orchestrator agent schema that uses ask_agent."""
    schema = {
        "type": "object",
        "description": """You are a simple orchestrator that delegates to a child agent.

When the user says anything, you MUST:
1. Call register_metadata with confidence=0.9
2. Call ask_agent with agent_name="test_child" and input_text=user's message
3. Do NOT add any text of your own - just delegate

You are an orchestrator. You do NOT respond directly.""",
        "properties": {
            "answer": {"type": "string"}
        },
        "required": ["answer"],
        "json_schema_extra": {
            "kind": "agent",
            "name": "test_orchestrator",
            "version": "1.0.0",
            "structured_output": False,
            "tools": [
                {"name": "register_metadata"},
                {"name": "ask_agent"}
            ]
        }
    }

    schema_path = tmp_path / "test_orchestrator.yaml"
    import yaml
    with open(schema_path, "w") as f:
        yaml.dump(schema, f)

    return schema_path


@pytest.fixture
def child_schema(tmp_path):
    """Create a temporary child agent schema."""
    schema = {
        "type": "object",
        "description": """You are a simple child agent that responds directly.

When called, respond with: "Hello from child agent! I received: {user_message}"
Keep your response brief and include the phrase "child agent response" so we can verify it.""",
        "properties": {
            "answer": {"type": "string"}
        },
        "required": ["answer"],
        "json_schema_extra": {
            "kind": "agent",
            "name": "test_child",
            "version": "1.0.0",
            "structured_output": False,
            "tools": []
        }
    }

    schema_path = tmp_path / "test_child.yaml"
    import yaml
    with open(schema_path, "w") as f:
        yaml.dump(schema, f)

    return schema_path


async def stream_chat_completion(
    session_id: str,
    message: str,
    agent_schema: str = "test_orchestrator",
) -> tuple[str, list[dict]]:
    """
    Make a streaming chat completion request and collect all SSE events.

    Returns:
        tuple: (accumulated_content, list_of_events)
    """
    url = f"{API_BASE}/api/v1/chat/completions"

    payload = {
        "model": agent_schema,
        "messages": [{"role": "user", "content": message}],
        "stream": True,
        "user": TEST_USER_ID,
        "extra_body": {
            "session_id": session_id,
        }
    }

    accumulated_content = ""
    events = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Remove "data: " prefix
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    events.append(data)

                    # Extract content from OpenAI-format chunks
                    if "choices" in data:
                        for choice in data["choices"]:
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                accumulated_content += content

                except json.JSONDecodeError:
                    # Non-JSON event (like custom SSE events)
                    events.append({"raw": data_str})

    return accumulated_content, events


async def get_session_messages(session_id: str) -> list[dict]:
    """Fetch session messages from the API."""
    url = f"{API_BASE}/api/v1/sessions/{session_id}/messages"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, params={"user_id": TEST_USER_ID})
        response.raise_for_status()
        return response.json()


@pytest.mark.asyncio
@pytest.mark.llm
async def test_child_agent_response_is_streamed(session_id):
    """
    Test that when orchestrator delegates via ask_agent, the child's
    text_response is streamed as content to the client.
    """
    # Make a streaming request to the orchestrator
    content, events = await stream_chat_completion(
        session_id=session_id,
        message="Hello, please delegate this to the child agent",
        agent_schema="test_orchestrator",
    )

    print(f"\n=== Streamed Content ===")
    print(content)
    print(f"\n=== Events ({len(events)}) ===")
    for i, event in enumerate(events):
        if "choices" in event:
            delta = event.get("choices", [{}])[0].get("delta", {})
            if delta.get("content"):
                print(f"  [{i}] Content: {delta.get('content')[:50]}...")
        elif "type" in event:
            event_type = event.get('type')
            print(f"  [{i}] Event type: {event_type}")
            if event_type == "error":
                print(f"      ERROR: {event.get('message', event)}")

    # Verify we got content from the child agent
    assert content, "No content was streamed"
    assert len(content) > 10, f"Content too short: {content}"

    # The content should come from the child agent's text_response
    # (The orchestrator doesn't produce direct text, only tool calls)
    print(f"\n✓ Received {len(content)} chars of streamed content")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_session_messages_saved_after_delegation(session_id):
    """
    Test that after orchestrator delegation, the session contains:
    1. User message
    2. Tool calls (register_metadata, ask_agent)
    3. Assistant message (from text_response)
    """
    # Make the streaming request
    content, _ = await stream_chat_completion(
        session_id=session_id,
        message="Test message for session storage",
        agent_schema="test_orchestrator",
    )

    # Wait a moment for async session save
    await asyncio.sleep(1)

    # Fetch session messages
    messages = await get_session_messages(session_id)

    print(f"\n=== Session Messages ({len(messages)}) ===")
    for i, msg in enumerate(messages):
        role = msg.get("role")
        content_preview = str(msg.get("content", ""))[:80]
        tool_name = msg.get("tool_name", "")
        print(f"  [{i}] {role}: {content_preview}... {f'(tool: {tool_name})' if tool_name else ''}")

    # Verify message structure
    roles = [m.get("role") for m in messages]

    assert "user" in roles, "No user message found"
    assert "tool" in roles, "No tool calls found"
    assert "assistant" in roles, "No assistant message found"

    # Verify assistant message has content (from text_response)
    assistant_messages = [m for m in messages if m.get("role") == "assistant"]
    assert assistant_messages, "No assistant messages"

    assistant_content = assistant_messages[-1].get("content", "")
    assert assistant_content, "Assistant message has no content"
    assert len(assistant_content) > 10, f"Assistant content too short: {assistant_content}"

    print(f"\n✓ Session contains {len(messages)} messages with proper structure")
    print(f"✓ Assistant message: {assistant_content[:100]}...")


if __name__ == "__main__":
    # Quick manual test
    async def main():
        session_id = str(uuid.uuid4())
        print(f"Session: {session_id}")

        print("\n--- Testing streaming ---")
        content, events = await stream_chat_completion(
            session_id=session_id,
            message="Hello, what is 2+2?",
            agent_schema="rem",  # Use default REM agent for quick test
        )

        print(f"\nContent received: {content[:200] if content else 'NONE'}...")
        print(f"Events: {len(events)}")

        # Check for content in events
        content_events = [e for e in events if "choices" in e and e.get("choices", [{}])[0].get("delta", {}).get("content")]
        print(f"Content events: {len(content_events)}")

    asyncio.run(main())
