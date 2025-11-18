"""Test script for REM chat completions API."""

import asyncio
import json

import httpx


async def test_chat_completions_non_streaming():
    """Test non-streaming chat completions with REM agent."""
    print("\n=== Testing Non-Streaming Chat Completions ===\n")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/v1/chat/completions",
            headers={
                "X-Tenant-Id": "test-tenant",
                "X-User-Id": "test-user",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai:gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "What is a REM LOOKUP query?"}
                ],
                "stream": False,
            },
            timeout=60.0,
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response:\n{json.dumps(response.json(), indent=2)}")


async def test_chat_completions_streaming():
    """Test streaming chat completions with REM agent."""
    print("\n=== Testing Streaming Chat Completions ===\n")

    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "http://localhost:8000/v1/chat/completions",
            headers={
                "X-Tenant-Id": "test-tenant",
                "X-User-Id": "test-user",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai:gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Explain the graph edge pattern in REM"}
                ],
                "stream": True,
            },
            timeout=60.0,
        ) as response:
            print(f"Status Code: {response.status_code}")
            print("Streaming response:\n")

            async for line in response.aiter_lines():
                if line.strip():
                    if line.startswith("data: "):
                        data = line[6:]  # Remove "data: " prefix
                        if data != "[DONE]":
                            try:
                                chunk = json.loads(data)
                                delta = chunk["choices"][0]["delta"]
                                if "content" in delta and delta["content"]:
                                    print(delta["content"], end="", flush=True)
                            except json.JSONDecodeError:
                                pass

            print("\n\n[DONE]")


async def test_with_custom_schema():
    """Test with query-agent schema."""
    print("\n=== Testing with Custom Schema (query-agent) ===\n")

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/v1/chat/completions",
            headers={
                "X-Tenant-Id": "test-tenant",
                "X-User-Id": "test-user",
                "X-Agent-Schema": "query-agent",  # Use query-agent schema
                "Content-Type": "application/json",
            },
            json={
                "model": "openai:gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "Find all documents Sarah authored"}
                ],
                "stream": False,
            },
            timeout=60.0,
        )

        print(f"Status Code: {response.status_code}")
        print(f"Response:\n{json.dumps(response.json(), indent=2)}")


async def main():
    """Run all tests."""
    try:
        await test_chat_completions_non_streaming()
        await test_chat_completions_streaming()
        await test_with_custom_schema()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
