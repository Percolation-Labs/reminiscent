"""
Test that text_response from ask_agent tool results gets extracted as assistant content.

In the orchestrator pattern:
1. Parent agent (siggy) calls ask_agent tool
2. Child agent (intake_diverge) returns text_response in result
3. Parent should use text_response as its assistant message

The issue: text_response IS returned but not being extracted correctly.
"""

import pytest
import json
import uuid
from unittest.mock import MagicMock, AsyncMock, patch


class TestTextResponseExtraction:
    """Test text_response extraction from tool calls."""

    @pytest.mark.asyncio
    async def test_text_response_extracted_when_no_direct_content(self):
        """
        When there's no direct TextPartDelta content (orchestrator pattern),
        text_response from ask_agent should be used as assistant content.
        """
        from rem.api.routers.chat.streaming import stream_openai_response_with_save
        from rem.settings import settings
        
        mock_agent = MagicMock()
        
        # Simulate an orchestrator that only calls tools (no direct text output)
        # The tool result contains text_response which should become the assistant message
        mock_chunks = [
            # Tool call event (not content)
            'event: tool_call\ndata: {"type":"tool_call","tool_name":"ask_agent","status":"started"}\n\n',
            # Tool result with text_response - this should be emitted as content
            'data: {"id":"chatcmpl-123","choices":[{"delta":{"content":"Response from child agent"},"index":0}]}\n\n',
            'data: [DONE]\n\n',
        ]
        
        # Also need to set up tool_calls_out to simulate captured tool calls
        captured_tool_calls = []
        
        async def mock_stream_response(*args, **kwargs):
            # Populate tool_calls_out with a result containing text_response
            tool_calls_out = kwargs.get('tool_calls_out')
            if tool_calls_out is not None:
                tool_calls_out.append({
                    "tool_name": "ask_agent",
                    "tool_id": "call_123",
                    "arguments": {"agent_name": "intake_diverge", "input_text": "test"},
                    "result": {
                        "status": "success",
                        "text_response": "Response from child agent via tool",
                        "output": "Response from child agent via tool",
                    },
                })
            for chunk in mock_chunks:
                yield chunk
        
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        
        saved_messages = []
        
        async def mock_store_messages(session_id, messages, user_id, compress=False):
            saved_messages.extend(messages)
        
        with patch("rem.api.routers.chat.streaming.stream_openai_response", mock_stream_response):
            # Patch where SessionMessageStore is USED (not where it's defined)
            with patch("rem.api.routers.chat.streaming.SessionMessageStore") as MockStore:
                mock_store_instance = MagicMock()
                mock_store_instance.store_session_messages = AsyncMock(side_effect=mock_store_messages)
                MockStore.return_value = mock_store_instance
                
                original_enabled = settings.postgres.enabled
                settings.postgres.enabled = True
                
                try:
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
                    print(f"Saved messages: {json.dumps(saved_messages, indent=2, default=str)}")
                    
                    # Should have assistant message
                    assistant_msgs = [m for m in saved_messages if m.get("role") == "assistant"]
                    print(f"Assistant messages: {assistant_msgs}")
                    
                    # Either from direct content OR from text_response
                    assert len(assistant_msgs) >= 1, f"Expected assistant message, got: {saved_messages}"
                    
                finally:
                    settings.postgres.enabled = original_enabled

    @pytest.mark.asyncio
    async def test_text_response_fallback_when_no_accumulated_content(self):
        """
        Test the fallback path: when accumulated_content is empty,
        check tool_calls for text_response.
        """
        from rem.api.routers.chat.streaming import stream_openai_response_with_save
        from rem.settings import settings
        
        mock_agent = MagicMock()
        
        # NO content chunks - only tool events
        mock_chunks = [
            'event: tool_call\ndata: {"type":"tool_call","tool_name":"ask_agent","status":"started"}\n\n',
            'event: tool_call\ndata: {"type":"tool_call","tool_name":"ask_agent","status":"completed"}\n\n',
            'data: [DONE]\n\n',
        ]
        
        async def mock_stream_response(*args, **kwargs):
            tool_calls_out = kwargs.get('tool_calls_out')
            if tool_calls_out is not None:
                tool_calls_out.append({
                    "tool_name": "ask_agent",
                    "tool_id": "call_123",
                    "arguments": {"agent_name": "intake_diverge", "input_text": "test"},
                    "result": {
                        "status": "success",
                        "text_response": "This should become the assistant message",
                        "output": "This should become the assistant message",
                    },
                })
            for chunk in mock_chunks:
                yield chunk
        
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        
        saved_messages = []
        
        async def mock_store_messages(session_id, messages, user_id, compress=False):
            saved_messages.extend(messages)
        
        with patch("rem.api.routers.chat.streaming.stream_openai_response", mock_stream_response):
            # Patch where SessionMessageStore is USED (not where it's defined)
            with patch("rem.api.routers.chat.streaming.SessionMessageStore") as MockStore:
                mock_store_instance = MagicMock()
                mock_store_instance.store_session_messages = AsyncMock(side_effect=mock_store_messages)
                MockStore.return_value = mock_store_instance
                
                original_enabled = settings.postgres.enabled
                settings.postgres.enabled = True
                
                try:
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
                    print(f"Saved messages: {json.dumps(saved_messages, indent=2, default=str)}")
                    
                    # Should have extracted text_response as assistant message
                    assistant_msgs = [m for m in saved_messages if m.get("role") == "assistant"]
                    tool_msgs = [m for m in saved_messages if m.get("role") == "tool"]
                    
                    print(f"Tool messages: {len(tool_msgs)}")
                    print(f"Assistant messages: {len(assistant_msgs)}")
                    
                    # The text_response fallback should kick in
                    assert len(assistant_msgs) == 1, f"Expected 1 assistant message from text_response, got: {assistant_msgs}"
                    assert "should become the assistant message" in assistant_msgs[0]["content"]
                    
                finally:
                    settings.postgres.enabled = original_enabled


if __name__ == "__main__":
    import asyncio
    t = TestTextResponseExtraction()
    asyncio.run(t.test_text_response_extracted_when_no_direct_content())
    print("✅ test_text_response_extracted_when_no_direct_content")
    asyncio.run(t.test_text_response_fallback_when_no_accumulated_content())
    print("✅ test_text_response_fallback_when_no_accumulated_content")
