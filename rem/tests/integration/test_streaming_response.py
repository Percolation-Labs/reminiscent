"""
Test FastAPI StreamingResponse behavior with async generators.

Key question: Does StreamingResponse fully consume the generator,
allowing post-yield code to execute?
"""

import pytest
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
import httpx


class TestStreamingResponseBehavior:
    """Test how StreamingResponse handles async generators."""

    def test_streaming_response_consumes_generator(self):
        """Test that StreamingResponse fully consumes the generator."""
        
        post_yield_executed = []
        
        async def my_generator():
            yield b"chunk1"
            yield b"chunk2"
            yield b"chunk3"
            # This should run after all yields when generator is consumed
            post_yield_executed.append("ran")
        
        app = FastAPI()
        
        @app.get("/stream")
        async def stream():
            return StreamingResponse(my_generator(), media_type="text/plain")
        
        # Use TestClient which should consume the entire response
        with TestClient(app) as client:
            response = client.get("/stream")
            content = response.content
            
        assert content == b"chunk1chunk2chunk3"
        # Key question: did post-yield code run?
        assert post_yield_executed == ["ran"], f"Post-yield should run, got: {post_yield_executed}"

    @pytest.mark.asyncio
    async def test_httpx_async_stream_consumes_generator(self):
        """Test with httpx async streaming (closer to real usage)."""
        
        post_yield_executed = []
        
        async def my_generator():
            yield b"a"
            yield b"b"
            post_yield_executed.append("ran")
        
        app = FastAPI()
        
        @app.get("/stream")
        async def stream():
            return StreamingResponse(my_generator(), media_type="text/plain")
        
        from httpx import ASGITransport, AsyncClient
        
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/stream") as response:
                content = b""
                async for chunk in response.aiter_bytes():
                    content += chunk
        
        assert content == b"ab"
        # Give a moment for cleanup
        await asyncio.sleep(0.1)
        assert post_yield_executed == ["ran"], f"Post-yield should run, got: {post_yield_executed}"


if __name__ == "__main__":
    t = TestStreamingResponseBehavior()
    t.test_streaming_response_consumes_generator()
    print("✅ TestClient consumes generator fully")
    
    asyncio.run(t.test_httpx_async_stream_consumes_generator())
    print("✅ httpx async stream consumes generator fully")
