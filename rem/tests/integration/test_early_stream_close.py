"""
Test what happens when client closes stream early (after [DONE]).

Hypothesis: When client closes connection, server generator is cancelled
and post-yield cleanup code doesn't run.
"""

import pytest
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient


class TestEarlyStreamClose:
    """Test behavior when client closes stream early."""

    @pytest.mark.asyncio
    async def test_client_break_after_done(self):
        """
        When client breaks after seeing [DONE], does post-yield code run?
        """
        post_yield_executed = []
        
        async def my_generator():
            yield b"data: {\"content\": \"hello\"}\n\n"
            yield b"data: [DONE]\n\n"
            # Does this run when client breaks after [DONE]?
            post_yield_executed.append("cleanup_ran")
        
        app = FastAPI()
        
        @app.get("/stream")
        async def stream():
            return StreamingResponse(my_generator(), media_type="text/event-stream")
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/stream") as response:
                async for line in response.aiter_lines():
                    if "[DONE]" in line:
                        break  # Client breaks early like simulation does
        
        # Give time for cleanup
        await asyncio.sleep(0.2)
        
        print(f"Post-yield executed: {post_yield_executed}")
        # This is the key question!
        assert post_yield_executed == ["cleanup_ran"], \
            f"Post-yield code should run even when client breaks after [DONE]. Got: {post_yield_executed}"

    @pytest.mark.asyncio
    async def test_client_full_consume(self):
        """
        When client fully consumes stream, post-yield code runs.
        """
        post_yield_executed = []
        
        async def my_generator():
            yield b"data: {\"content\": \"hello\"}\n\n"
            yield b"data: [DONE]\n\n"
            post_yield_executed.append("cleanup_ran")
        
        app = FastAPI()
        
        @app.get("/stream")
        async def stream():
            return StreamingResponse(my_generator(), media_type="text/event-stream")
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/stream") as response:
                content = []
                async for line in response.aiter_lines():
                    content.append(line)
                    # Don't break - consume everything
        
        await asyncio.sleep(0.2)
        
        print(f"Full consume - Post-yield executed: {post_yield_executed}")
        assert post_yield_executed == ["cleanup_ran"]


if __name__ == "__main__":
    t = TestEarlyStreamClose()
    try:
        asyncio.run(t.test_client_break_after_done())
        print("✅ test_client_break_after_done")
    except AssertionError as e:
        print(f"❌ test_client_break_after_done: {e}")
    
    asyncio.run(t.test_client_full_consume())
    print("✅ test_client_full_consume")
