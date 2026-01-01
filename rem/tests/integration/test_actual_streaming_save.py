"""
Test the actual stream_openai_response_with_save function.

This tests the real code path to find where assistant messages get lost.
"""

import pytest
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch


class TestActualStreamingSave:
    """Test the actual streaming save function."""

    @pytest.mark.asyncio
    async def test_stream_with_save_accumulates_content(self):
        """Test that stream_openai_response_with_save accumulates and saves content."""
        from rem.api.routers.chat.streaming import stream_openai_response_with_save
        from rem.settings import settings
        
        # Mock agent that yields content
        mock_agent = MagicMock()
        
        # Create mock chunks that would come from stream_openai_response
        mock_chunks = [
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"role":"assistant","content":"Hello"},"index":0}]}\n\n',
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"content":" from"},"index":0}]}\n\n',
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"content":" agent"},"index":0}]}\n\n',
            'data: [DONE]\n\n',
        ]
        
        async def mock_stream_response(*args, **kwargs):
            for chunk in mock_chunks:
                yield chunk
        
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        
        # Track what gets saved
        saved_messages = []
        
        async def mock_store_messages(session_id, messages, user_id, compress=False):
            saved_messages.extend(messages)
        
        with patch("rem.api.routers.chat.streaming.stream_openai_response", mock_stream_response):
            # Patch where SessionMessageStore is USED (not where it's defined)
            with patch("rem.api.routers.chat.streaming.SessionMessageStore") as MockStore:
                mock_store_instance = MagicMock()
                mock_store_instance.store_session_messages = AsyncMock(side_effect=mock_store_messages)
                MockStore.return_value = mock_store_instance
                
                # Ensure postgres is "enabled" for the test
                original_enabled = settings.postgres.enabled
                settings.postgres.enabled = True
                
                try:
                    # Consume the generator
                    chunks_received = []
                    async for chunk in stream_openai_response_with_save(
                        agent=mock_agent,
                        prompt="test",
                        model="test-model",
                        session_id=session_id,
                        user_id=user_id,
                    ):
                        chunks_received.append(chunk)
                    
                    print(f"\nChunks received: {len(chunks_received)}")
                    print(f"Saved messages: {saved_messages}")
                    
                    # Verify chunks were yielded
                    assert len(chunks_received) == 4, f"Expected 4 chunks, got {len(chunks_received)}"
                    
                    # Verify store was called
                    print(f"MockStore called: {MockStore.called}")
                    print(f"store_session_messages called: {mock_store_instance.store_session_messages.called}")
                    
                    # Verify assistant message was saved
                    assistant_msgs = [m for m in saved_messages if m.get("role") == "assistant"]
                    assert len(assistant_msgs) == 1, f"Expected 1 assistant message, got {len(assistant_msgs)}: {saved_messages}"
                    assert assistant_msgs[0]["content"] == "Hello from agent"
                    
                finally:
                    settings.postgres.enabled = original_enabled


if __name__ == "__main__":
    import asyncio
    asyncio.run(TestActualStreamingSave().test_stream_with_save_accumulates_content())
    print("✅ stream_openai_response_with_save works correctly")
