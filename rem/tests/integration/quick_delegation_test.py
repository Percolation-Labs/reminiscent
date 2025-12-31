"""
Quick test for multi-agent delegation streaming.
Tests that text_response from ask_agent is streamed to client.
"""

import asyncio
import json
import uuid
import httpx

API_BASE = "http://localhost:8000"


async def test_delegation_streaming():
    """Test basic streaming with the default rem agent first."""
    session_id = str(uuid.uuid4())
    print(f"Session: {session_id}")

    # Use the rem agent - just test that streaming works at all
    url = f"{API_BASE}/api/v1/chat/completions"
    payload = {
        "model": "rem",
        "messages": [{"role": "user", "content": "Say hello in exactly 3 words"}],
        "stream": True,
        "user": "test-user",
        "extra_body": {"session_id": session_id}
    }

    accumulated_content = ""
    events = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue

                data_str = line[6:]
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                    events.append(data)

                    if "choices" in data:
                        for choice in data["choices"]:
                            delta = choice.get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                accumulated_content += content
                                print(f"Content chunk: '{content}'")
                except json.JSONDecodeError:
                    events.append({"raw": data_str})

    print(f"\n=== Results ===")
    print(f"Total content: '{accumulated_content}'")
    print(f"Total events: {len(events)}")

    # Check session messages were saved
    await asyncio.sleep(1)  # Wait for async save

    try:
        messages_url = f"{API_BASE}/api/v1/sessions/{session_id}/messages"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(messages_url, params={"user_id": "test-user"})
            if response.status_code == 200:
                messages = response.json()
                print(f"\n=== Session Messages ({len(messages)}) ===")
                for msg in messages:
                    role = msg.get("role")
                    content = str(msg.get("content", ""))[:80]
                    print(f"  {role}: {content}...")
            else:
                print(f"Could not fetch session messages: {response.status_code}")
    except Exception as e:
        print(f"Error fetching session: {e}")

    # Assert basics
    assert accumulated_content, "No content was streamed!"
    assert len(accumulated_content) > 0, "Content was empty!"
    print("\n✓ Basic streaming test PASSED")


if __name__ == "__main__":
    asyncio.run(test_delegation_streaming())
