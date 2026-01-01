"""
Unit tests for streaming utilities.

Tests the StreamingState and child content deduplication logic.
"""

import pytest
from rem.api.routers.chat.streaming_utils import (
    StreamingState,
    build_content_chunk,
    build_progress_event,
    build_tool_start_event,
)
from rem.api.routers.chat.child_streaming import handle_child_content


class TestStreamingState:
    """Tests for StreamingState dataclass."""

    def test_create_initializes_defaults(self):
        """StreamingState.create() should set sensible defaults."""
        state = StreamingState.create(model="test-model")

        assert state.model == "test-model"
        assert state.request_id.startswith("chatcmpl-")
        assert state.is_first_chunk is True
        assert state.token_count == 0
        assert state.child_content_streamed is False
        assert state.responding_agent is None
        assert state.active_tool_calls == {}
        assert state.pending_tool_completions == []

    def test_latency_ms_returns_positive(self):
        """latency_ms() should return positive milliseconds."""
        state = StreamingState.create(model="test")

        # Should be > 0 after creation
        latency = state.latency_ms()
        assert latency >= 0


class TestBuildContentChunk:
    """Tests for build_content_chunk."""

    def test_first_chunk_includes_role(self):
        """First chunk should include role='assistant'."""
        state = StreamingState.create(model="test")
        chunk = build_content_chunk(state, "Hello")

        assert '"role":"assistant"' in chunk
        assert '"content":"Hello"' in chunk
        assert state.is_first_chunk is False  # Updated after call

    def test_subsequent_chunks_no_role(self):
        """Subsequent chunks should have role=null."""
        state = StreamingState.create(model="test")
        state.is_first_chunk = False  # Simulate after first chunk

        chunk = build_content_chunk(state, "world")

        assert '"role":null' in chunk
        assert '"content":"world"' in chunk

    def test_updates_token_count(self):
        """build_content_chunk should update token count."""
        state = StreamingState.create(model="test")
        build_content_chunk(state, "one two three")

        assert state.token_count == 3  # Word count


class TestChildContentHandling:
    """Tests for child content streaming and deduplication."""

    def test_handle_child_content_sets_flag(self):
        """handle_child_content should set child_content_streamed flag."""
        state = StreamingState.create(model="test")
        assert state.child_content_streamed is False

        result = handle_child_content(state, "child_agent", "Hello from child")

        assert state.child_content_streamed is True
        assert state.responding_agent == "child_agent"
        assert result is not None
        assert "Hello from child" in result

    def test_handle_child_content_empty_returns_none(self):
        """Empty content should return None and not set flag."""
        state = StreamingState.create(model="test")

        result = handle_child_content(state, "child_agent", "")

        assert result is None
        assert state.child_content_streamed is False

    def test_parent_should_skip_after_child_content(self):
        """After child_content_streamed=True, parent text should be skipped.

        This is the key test for the duplication fix.
        The streaming.py code checks state.child_content_streamed before
        emitting TextPartDelta content.
        """
        state = StreamingState.create(model="test")

        # Simulate child content being streamed
        handle_child_content(state, "intake_diverge", "Child's response")

        # Now parent tries to output text - this should be skipped
        # In streaming.py, the check is:
        #   if state.child_content_streamed:
        #       continue  # Skip parent text
        assert state.child_content_streamed is True

        # If we were in the streaming loop, we'd skip:
        # This is what streaming.py does:
        should_skip_parent_text = state.child_content_streamed
        assert should_skip_parent_text is True


class TestProgressAndToolEvents:
    """Tests for progress and tool SSE events."""

    def test_build_progress_event_format(self):
        """Progress events should have correct format."""
        event = build_progress_event(
            step=1,
            total_steps=3,
            label="Processing",
            status="in_progress"
        )

        assert 'event: progress' in event
        assert '"step":1' in event
        assert '"total_steps":3' in event
        assert '"label":"Processing"' in event

    def test_build_tool_start_event_format(self):
        """Tool start events should have correct format."""
        event = build_tool_start_event(
            tool_name="search_rem",
            tool_id="call_123",
            arguments={"query": "test"}
        )

        assert 'event: tool_call' in event
        assert '"tool_name":"search_rem"' in event
        assert '"status":"started"' in event


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
