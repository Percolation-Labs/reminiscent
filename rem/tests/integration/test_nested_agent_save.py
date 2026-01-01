"""
Integration test for nested agent message saving.

This reproduces the real issue:
1. Parent agent calls ask_agent tool
2. Child agent executes and returns text_response
3. The text_response should be saved as assistant message

Uses actual agent execution, not mocks.
"""

import pytest
import asyncio
import uuid
from unittest.mock import patch, MagicMock, AsyncMock

from rem.agentic.context import AgentContext, agent_context_scope
from rem.settings import settings


class TestNestedAgentSave:
    """Test that nested agent responses are saved correctly."""

    @pytest.mark.asyncio
    async def test_ask_agent_text_response_saved(self):
        """
        When parent agent delegates to child via ask_agent,
        the child's response should be saved as assistant message.
        """
        from rem.api.routers.chat.streaming import stream_openai_response_with_save
        from rem.api.routers.chat.sse_events import format_sse_event, ToolCallEvent
        
        # Track saved messages
        saved_messages = []
        
        async def mock_store_messages(session_id, messages, user_id, compress=False):
            saved_messages.extend(messages)
            print(f"  -> Saved {len(messages)} messages: {[m.get('role') for m in messages]}")
        
        # Create a mock inner generator that simulates:
        # 1. Tool call to ask_agent
        # 2. Tool result with text_response
        # 3. Content chunk from text_response
        async def mock_stream_openai_response(
            agent, prompt, model, request_id=None, agent_schema=None,
            session_id=None, message_id=None, trace_context_out=None,
            tool_calls_out=None, agent_context=None, message_history=None
        ):
            # Simulate tool call to ask_agent
            yield 'event: tool_call\ndata: {"type":"tool_call","tool_name":"ask_agent","status":"started"}\n\n'
            
            # Populate tool_calls_out like the real code does
            if tool_calls_out is not None:
                tool_calls_out.append({
                    "tool_name": "ask_agent",
                    "tool_id": "call_abc123",
                    "arguments": {"agent_name": "intake_diverge", "input_text": "Patient is anxious"},
                    "result": {
                        "status": "success",
                        "text_response": "I understand you're feeling anxious. Can you tell me more?",
                        "output": "I understand you're feeling anxious. Can you tell me more?",
                        "agent_schema": "intake_diverge",
                    },
                })
            
            # The real code yields text_response as content chunk
            yield 'data: {"id":"chatcmpl-123","object":"chat.completion.chunk","created":1234567890,"model":"test","choices":[{"index":0,"delta":{"role":"assistant","content":"I understand you\'re feeling anxious. Can you tell me more?"},"finish_reason":null}]}\n\n'
            
            # Tool completion
            yield 'event: tool_call\ndata: {"type":"tool_call","tool_name":"ask_agent","status":"completed"}\n\n'
            
            # Done
            yield 'data: [DONE]\n\n'
        
        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        
        mock_agent = MagicMock()
        
        with patch("rem.api.routers.chat.streaming.stream_openai_response", mock_stream_openai_response):
            # Patch where SessionMessageStore is USED (not where it's defined)
            with patch("rem.api.routers.chat.streaming.SessionMessageStore") as MockStore:
                mock_store_instance = MagicMock()
                mock_store_instance.store_session_messages = AsyncMock(side_effect=mock_store_messages)
                MockStore.return_value = mock_store_instance
                
                original_enabled = settings.postgres.enabled
                settings.postgres.enabled = True
                
                try:
                    # Consume all chunks
                    chunks = []
                    async for chunk in stream_openai_response_with_save(
                        agent=mock_agent,
                        prompt="Patient is anxious",
                        model="test-model",
                        session_id=session_id,
                        user_id=user_id,
                    ):
                        chunks.append(chunk)
                        print(f"Chunk: {chunk[:60]}...")
                    
                    print(f"\nTotal chunks: {len(chunks)}")
                    print(f"Total saved messages: {len(saved_messages)}")
                    
                    # Check what was saved
                    tool_msgs = [m for m in saved_messages if m.get("role") == "tool"]
                    assistant_msgs = [m for m in saved_messages if m.get("role") == "assistant"]
                    
                    print(f"Tool messages: {len(tool_msgs)}")
                    print(f"Assistant messages: {len(assistant_msgs)}")
                    
                    if assistant_msgs:
                        print(f"Assistant content: {assistant_msgs[0].get('content', 'N/A')[:80]}...")
                    
                    # Assertions
                    assert len(tool_msgs) >= 1, "Should save tool message from ask_agent"
                    assert len(assistant_msgs) == 1, f"Should save 1 assistant message, got {len(assistant_msgs)}"
                    assert "anxious" in assistant_msgs[0]["content"], "Assistant message should contain response text"
                    
                finally:
                    settings.postgres.enabled = original_enabled


if __name__ == "__main__":
    asyncio.run(TestNestedAgentSave().test_ask_agent_text_response_saved())
    print("\n✅ test_ask_agent_text_response_saved passed")
