"""
Unit tests for SSE simulator.

Tests cover:
1. Event sequence generation
2. Event type correctness
3. Configuration options
4. Minimal and error demos
"""

import pytest

from rem.agentic.agents.sse_simulator import (
    stream_simulator_events,
    stream_minimal_demo,
    stream_error_demo,
)
from rem.api.routers.chat.sse_events import (
    TextDeltaEvent,
    ReasoningEvent,
    ActionRequestEvent,
    MetadataEvent,
    ProgressEvent,
    ToolCallEvent,
    ErrorEvent,
    DoneEvent,
)


@pytest.mark.asyncio
class TestStreamSimulatorEvents:
    """Test full simulator event stream."""

    async def test_generates_all_event_types(self):
        """Simulator generates all expected event types."""
        event_types = set()

        async for event in stream_simulator_events("demo", delay_ms=1):
            event_types.add(type(event).__name__)

        # Check all event types are present
        assert "ReasoningEvent" in event_types
        assert "ProgressEvent" in event_types
        assert "ToolCallEvent" in event_types
        assert "TextDeltaEvent" in event_types
        assert "MetadataEvent" in event_types
        assert "ActionRequestEvent" in event_types
        assert "DoneEvent" in event_types

    async def test_ends_with_done_event(self):
        """Stream always ends with done event."""
        events = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            events.append(event)

        assert len(events) > 0
        assert isinstance(events[-1], DoneEvent)
        assert events[-1].reason == "stop"

    async def test_reasoning_events_have_content(self):
        """Reasoning events contain content."""
        reasoning_events = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            if isinstance(event, ReasoningEvent):
                reasoning_events.append(event)

        assert len(reasoning_events) > 0
        for event in reasoning_events:
            assert event.content
            assert len(event.content) > 0

    async def test_progress_events_sequence(self):
        """Progress events have correct step sequence."""
        progress_events = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            if isinstance(event, ProgressEvent):
                progress_events.append(event)

        # Should have multiple progress events
        assert len(progress_events) > 0

        # Check all have valid structure
        for event in progress_events:
            assert event.step >= 1
            assert event.total_steps >= event.step
            assert event.label
            assert event.status in ["pending", "in_progress", "completed", "failed"]

    async def test_tool_call_events_have_pairs(self):
        """Tool calls have started/completed pairs."""
        tool_events = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            if isinstance(event, ToolCallEvent):
                tool_events.append(event)

        # Should have even number (pairs)
        assert len(tool_events) > 0
        assert len(tool_events) % 2 == 0

        # Check started/completed pairs
        started = [e for e in tool_events if e.status == "started"]
        completed = [e for e in tool_events if e.status == "completed"]
        assert len(started) == len(completed)

    async def test_text_delta_events_form_content(self):
        """Text delta events combine to form complete content."""
        text_parts = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            if isinstance(event, TextDeltaEvent):
                text_parts.append(event.content)

        full_text = "".join(text_parts)
        assert len(full_text) > 100  # Should have substantial content
        assert "SSE Streaming Demo" in full_text  # Title from demo content

    async def test_metadata_event_structure(self):
        """Metadata event has expected fields."""
        metadata_events = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            if isinstance(event, MetadataEvent):
                metadata_events.append(event)

        assert len(metadata_events) == 1
        metadata = metadata_events[0]

        assert metadata.confidence is not None
        assert 0 <= metadata.confidence <= 1
        assert metadata.sources is not None
        assert len(metadata.sources) > 0
        assert metadata.model_version == "simulator-v1.0.0"

    async def test_action_request_event_structure(self):
        """Action request has valid card structure."""
        action_events = []
        async for event in stream_simulator_events("demo", delay_ms=1):
            if isinstance(event, ActionRequestEvent):
                action_events.append(event)

        assert len(action_events) == 1
        action = action_events[0]

        card = action.card
        assert card.id
        assert card.prompt
        assert len(card.actions) > 0
        assert len(card.inputs) > 0

        # Check action structure
        for action_btn in card.actions:
            assert action_btn.id
            assert action_btn.title


@pytest.mark.asyncio
class TestSimulatorConfiguration:
    """Test simulator configuration options."""

    async def test_exclude_reasoning(self):
        """Can exclude reasoning events."""
        event_types = set()
        async for event in stream_simulator_events(
            "demo", delay_ms=1, include_reasoning=False
        ):
            event_types.add(type(event).__name__)

        assert "ReasoningEvent" not in event_types
        assert "DoneEvent" in event_types  # Still ends properly

    async def test_exclude_progress(self):
        """Can exclude progress events."""
        event_types = set()
        async for event in stream_simulator_events(
            "demo", delay_ms=1, include_progress=False
        ):
            event_types.add(type(event).__name__)

        assert "ProgressEvent" not in event_types

    async def test_exclude_tool_calls(self):
        """Can exclude tool call events."""
        event_types = set()
        async for event in stream_simulator_events(
            "demo", delay_ms=1, include_tool_calls=False
        ):
            event_types.add(type(event).__name__)

        assert "ToolCallEvent" not in event_types

    async def test_exclude_actions(self):
        """Can exclude action request events."""
        event_types = set()
        async for event in stream_simulator_events(
            "demo", delay_ms=1, include_actions=False
        ):
            event_types.add(type(event).__name__)

        assert "ActionRequestEvent" not in event_types

    async def test_exclude_metadata(self):
        """Can exclude metadata events."""
        event_types = set()
        async for event in stream_simulator_events(
            "demo", delay_ms=1, include_metadata=False
        ):
            event_types.add(type(event).__name__)

        assert "MetadataEvent" not in event_types

    async def test_minimal_config(self):
        """Minimal config still produces text and done."""
        event_types = set()
        async for event in stream_simulator_events(
            "demo",
            delay_ms=1,
            include_reasoning=False,
            include_progress=False,
            include_tool_calls=False,
            include_actions=False,
            include_metadata=False,
        ):
            event_types.add(type(event).__name__)

        # Only text and done should remain
        assert "TextDeltaEvent" in event_types
        assert "DoneEvent" in event_types
        assert len(event_types) == 2


@pytest.mark.asyncio
class TestMinimalDemo:
    """Test minimal simulator demo."""

    async def test_generates_text_and_done(self):
        """Minimal demo generates text deltas and done."""
        events = []
        async for event in stream_minimal_demo("Hello world!", delay_ms=1):
            events.append(event)

        # Check event types
        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        done_events = [e for e in events if isinstance(e, DoneEvent)]

        assert len(text_events) > 0
        assert len(done_events) == 1

    async def test_content_is_preserved(self):
        """Content is fully preserved across text deltas."""
        original = "Hello world this is a test!"
        text_parts = []

        async for event in stream_minimal_demo(original, delay_ms=1):
            if isinstance(event, TextDeltaEvent):
                text_parts.append(event.content)

        full_text = "".join(text_parts).strip()
        assert full_text == original


@pytest.mark.asyncio
class TestErrorDemo:
    """Test error simulator demo."""

    async def test_generates_error_event(self):
        """Error demo generates error event."""
        events = []
        async for event in stream_error_demo(error_after_words=5):
            events.append(event)

        error_events = [e for e in events if isinstance(e, ErrorEvent)]
        assert len(error_events) == 1

        error = error_events[0]
        assert error.code == "simulated_error"
        assert error.recoverable is True

    async def test_streams_text_before_error(self):
        """Some text is streamed before error."""
        events = []
        async for event in stream_error_demo(error_after_words=5):
            events.append(event)

        text_events = [e for e in events if isinstance(e, TextDeltaEvent)]
        assert len(text_events) > 0

    async def test_ends_with_error_done(self):
        """Error demo ends with done(reason=error)."""
        events = []
        async for event in stream_error_demo(error_after_words=5):
            events.append(event)

        assert isinstance(events[-1], DoneEvent)
        assert events[-1].reason == "error"
