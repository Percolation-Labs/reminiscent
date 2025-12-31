"""
Test that stream_openai_response_with_save actually saves assistant messages.

This is the critical path:
1. stream_openai_response yields chunks
2. stream_openai_response_with_save wraps it and accumulates content
3. After streaming, it should save to database

The issue: assistant messages are NOT being saved.
"""

import pytest
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch


class TestStreamingSave:
    """Test the streaming save logic."""

    @pytest.mark.asyncio
    async def test_accumulated_content_from_openai_format(self):
        """Test that OpenAI-format chunks are correctly accumulated."""
        
        # Simulate chunks in OpenAI format
        chunks = [
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"role":"assistant","content":"Hello"},"index":0}]}\n\n',
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"content":" world"},"index":0}]}\n\n',
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"content":"!"},"index":0}]}\n\n',
            'data: [DONE]\n\n',
        ]
        
        accumulated_content = []
        
        for chunk in chunks:
            # This is the extraction logic from stream_openai_response_with_save
            if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    data_str = chunk[6:].strip()
                    if data_str:
                        data = json.loads(data_str)
                        if "choices" in data and data["choices"]:
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                accumulated_content.append(content)
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass
        
        full_content = "".join(accumulated_content)
        assert full_content == "Hello world!", f"Expected 'Hello world!', got '{full_content}'"

    @pytest.mark.asyncio
    async def test_generator_completes_after_all_yields(self):
        """
        Test that code after async for loop executes when generator is consumed.
        
        This simulates what happens in stream_openai_response_with_save.
        """
        post_loop_executed = False
        accumulated = []
        
        async def mock_generator():
            yield "chunk1"
            yield "chunk2"
            yield "chunk3"
        
        async def wrapper():
            nonlocal post_loop_executed, accumulated
            async for chunk in mock_generator():
                accumulated.append(chunk)
            # This code should run after generator is exhausted
            post_loop_executed = True
        
        # Consume the wrapper generator
        gen = wrapper()
        await gen  # This should complete the coroutine
        
        assert post_loop_executed, "Code after async for should execute"
        assert accumulated == ["chunk1", "chunk2", "chunk3"]

    @pytest.mark.asyncio
    async def test_async_generator_post_yield_execution(self):
        """
        Test async generator with code after yield - does it run?
        
        This is the actual pattern used in stream_openai_response_with_save.
        """
        post_yield_values = []
        
        async def gen_with_cleanup():
            yield "a"
            yield "b"
            # Code after all yields - does this run?
            post_yield_values.append("cleanup_ran")
        
        # Consume generator
        results = []
        async for item in gen_with_cleanup():
            results.append(item)
        
        assert results == ["a", "b"]
        assert post_yield_values == ["cleanup_ran"], "Post-yield code should run when generator exhausted"

    @pytest.mark.asyncio 
    async def test_nested_async_generator_propagation(self):
        """
        Test that wrapping an async generator properly propagates all items
        and allows post-loop code to run.
        """
        inner_completed = False
        outer_completed = False
        
        async def inner_gen():
            nonlocal inner_completed
            yield "inner1"
            yield "inner2"
            inner_completed = True
        
        async def outer_gen():
            nonlocal outer_completed
            async for item in inner_gen():
                yield f"outer({item})"
            # This should run after inner is exhausted
            outer_completed = True
        
        results = []
        async for item in outer_gen():
            results.append(item)
        
        assert results == ["outer(inner1)", "outer(inner2)"]
        assert inner_completed, "Inner generator post-yield should run"
        assert outer_completed, "Outer generator post-yield should run"


if __name__ == "__main__":
    import asyncio
    
    async def run_tests():
        t = TestStreamingSave()
        await t.test_accumulated_content_from_openai_format()
        print("✅ test_accumulated_content_from_openai_format")
        await t.test_generator_completes_after_all_yields()
        print("✅ test_generator_completes_after_all_yields")
        await t.test_async_generator_post_yield_execution()
        print("✅ test_async_generator_post_yield_execution")
        await t.test_nested_async_generator_propagation()
        print("✅ test_nested_async_generator_propagation")
    
    asyncio.run(run_tests())
