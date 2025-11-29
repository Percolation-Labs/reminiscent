"""
Unit tests for SSE simulator.

Tests cover:
1. Event sequence generation
2. Event type correctness
3. Configuration options
4. Minimal and error demos

Note: The simulator now yields SSE-formatted strings (not event objects).
These tests parse the SSE strings to validate event structure.
"""

import json
import pytest

from rem.agentic.agents.sse_simulator import (
    stream_simulator_events,
    stream_minimal_demo,
    stream_error_demo,
)


# =============================================================================
# SSE Parsing Helpers
# =============================================================================

def parse_sse_string(sse_string: str) -> dict:
    """
    Parse an SSE-formatted string into a dict with event_type and data.

    SSE formats:
    1. Named events: "event: reasoning\ndata: {...}\n\n"
    2. Data-only (OpenAI): "data: {...}\n\n"
    3. Done marker: "data: [DONE]\n\n"

    Returns:
        dict with keys:
        - event_type: "reasoning", "progress", "data", "done_marker", etc.
        - data: parsed JSON data (or None for [DONE])
        - raw: original string
    """
    result = {"raw": sse_string, "event_type": None, "data": None}

    lines = sse_string.strip().split("\n")

    # Check for [DONE] marker
    if sse_string.strip() == "data: [DONE]":
        result["event_type"] = "done_marker"
        return result

    event_type = None
    data_str = None

    for line in lines:
        if line.startswith("event: "):
            event_type = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:]

    if event_type:
        result["event_type"] = event_type
    elif data_str:
        # OpenAI-compatible format (no event: prefix)
        result["event_type"] = "data"

    if data_str and data_str != "[DONE]":
        try:
            result["data"] = json.loads(data_str)
        except json.JSONDecodeError:
            result["data"] = data_str

    return result


async def collect_events(async_gen) -> list[dict]:
    """Collect all events from an async generator and parse them."""
    events = []
    async for sse_string in async_gen:
        parsed = parse_sse_string(sse_string)
        events.append(parsed)
    return events


def get_events_by_type(events: list[dict], event_type: str) -> list[dict]:
    """Filter events by type."""
    return [e for e in events if e["event_type"] == event_type]


def get_text_content(events: list[dict]) -> str:
    """Extract full text content from data events."""
    text_parts = []
    for event in events:
        if event["event_type"] == "data" and event["data"]:
            # OpenAI format: {"choices": [{"delta": {"content": "..."}}]}
            choices = event["data"].get("choices", [])
            if choices and choices[0].get("delta", {}).get("content"):
                text_parts.append(choices[0]["delta"]["content"])
    return "".join(text_parts)


# =============================================================================
# Tests
# =============================================================================

@pytest.mark.asyncio
class TestStreamSimulatorEvents:
    """Test full simulator event stream."""

    async def test_generates_all_event_types(self):
        """Simulator generates all expected event types."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        event_types = {e["event_type"] for e in events}

        # Check all event types are present
        assert "reasoning" in event_types
        assert "progress" in event_types
        assert "tool_call" in event_types
        assert "data" in event_types  # OpenAI-compatible text chunks
        assert "metadata" in event_types
        assert "action_request" in event_types
        assert "done" in event_types

    async def test_ends_with_done_event(self):
        """Stream always ends with done event (before [DONE] marker)."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))

        assert len(events) > 0
        # Last event should be the [DONE] marker
        assert events[-1]["event_type"] == "done_marker"
        # Second to last should be the done event
        assert events[-2]["event_type"] == "done"
        assert events[-2]["data"]["reason"] == "stop"

    async def test_reasoning_events_have_content(self):
        """Reasoning events contain content."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        reasoning_events = get_events_by_type(events, "reasoning")

        assert len(reasoning_events) > 0
        for event in reasoning_events:
            assert event["data"]["content"]
            assert len(event["data"]["content"]) > 0

    async def test_progress_events_sequence(self):
        """Progress events have correct step sequence."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        progress_events = get_events_by_type(events, "progress")

        # Should have multiple progress events
        assert len(progress_events) > 0

        # Check all have valid structure
        for event in progress_events:
            data = event["data"]
            assert data["step"] >= 1
            assert data["total_steps"] >= data["step"]
            assert data["label"]
            assert data["status"] in ["pending", "in_progress", "completed", "failed"]

    async def test_tool_call_events_have_pairs(self):
        """Tool calls have started/completed pairs."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        tool_events = get_events_by_type(events, "tool_call")

        # Should have even number (pairs)
        assert len(tool_events) > 0
        assert len(tool_events) % 2 == 0

        # Check started/completed pairs
        started = [e for e in tool_events if e["data"]["status"] == "started"]
        completed = [e for e in tool_events if e["data"]["status"] == "completed"]
        assert len(started) == len(completed)

    async def test_text_delta_events_form_content(self):
        """Text delta events combine to form complete content."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        full_text = get_text_content(events)

        assert len(full_text) > 100  # Should have substantial content
        assert "SSE Streaming Demo" in full_text  # Title from demo content

    async def test_metadata_event_structure(self):
        """Metadata event has expected fields."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        metadata_events = get_events_by_type(events, "metadata")

        assert len(metadata_events) == 1
        metadata = metadata_events[0]["data"]

        assert metadata["confidence"] is not None
        assert 0 <= metadata["confidence"] <= 1
        assert metadata["sources"] is not None
        assert len(metadata["sources"]) > 0
        assert metadata["model_version"] == "simulator-v1.0.0"

    async def test_action_request_event_structure(self):
        """Action request has valid card structure."""
        events = await collect_events(stream_simulator_events("demo", delay_ms=1))
        action_events = get_events_by_type(events, "action_request")

        assert len(action_events) == 1
        action = action_events[0]["data"]

        card = action["card"]
        assert card["id"]
        assert card["prompt"]
        assert len(card["actions"]) > 0
        assert len(card["inputs"]) > 0

        # Check action structure
        for action_btn in card["actions"]:
            assert action_btn["id"]
            assert action_btn["title"]


@pytest.mark.asyncio
class TestSimulatorConfiguration:
    """Test simulator configuration options."""

    async def test_exclude_reasoning(self):
        """Can exclude reasoning events."""
        events = await collect_events(
            stream_simulator_events("demo", delay_ms=1, include_reasoning=False)
        )
        event_types = {e["event_type"] for e in events}

        assert "reasoning" not in event_types
        assert "done" in event_types  # Still ends properly

    async def test_exclude_progress(self):
        """Can exclude progress events."""
        events = await collect_events(
            stream_simulator_events("demo", delay_ms=1, include_progress=False)
        )
        event_types = {e["event_type"] for e in events}

        assert "progress" not in event_types

    async def test_exclude_tool_calls(self):
        """Can exclude tool call events."""
        events = await collect_events(
            stream_simulator_events("demo", delay_ms=1, include_tool_calls=False)
        )
        event_types = {e["event_type"] for e in events}

        assert "tool_call" not in event_types

    async def test_exclude_actions(self):
        """Can exclude action request events."""
        events = await collect_events(
            stream_simulator_events("demo", delay_ms=1, include_actions=False)
        )
        event_types = {e["event_type"] for e in events}

        assert "action_request" not in event_types

    async def test_exclude_metadata(self):
        """Can exclude metadata events."""
        events = await collect_events(
            stream_simulator_events("demo", delay_ms=1, include_metadata=False)
        )
        event_types = {e["event_type"] for e in events}

        assert "metadata" not in event_types

    async def test_minimal_config(self):
        """Minimal config still produces text and done."""
        events = await collect_events(
            stream_simulator_events(
                "demo",
                delay_ms=1,
                include_reasoning=False,
                include_progress=False,
                include_tool_calls=False,
                include_actions=False,
                include_metadata=False,
            )
        )
        event_types = {e["event_type"] for e in events}

        # Only text (data), done, and done_marker should remain
        assert "data" in event_types
        assert "done" in event_types
        assert "done_marker" in event_types
        # Should not have other event types
        assert "reasoning" not in event_types
        assert "progress" not in event_types
        assert "tool_call" not in event_types
        assert "action_request" not in event_types
        assert "metadata" not in event_types


@pytest.mark.asyncio
class TestMinimalDemo:
    """Test minimal simulator demo."""

    async def test_generates_text_and_done(self):
        """Minimal demo generates text deltas and done."""
        events = await collect_events(stream_minimal_demo("Hello world!", delay_ms=1))

        # Check event types
        data_events = get_events_by_type(events, "data")
        done_events = get_events_by_type(events, "done")

        assert len(data_events) > 0
        assert len(done_events) == 1

    async def test_content_is_preserved(self):
        """Content is fully preserved across text deltas."""
        original = "Hello world this is a test!"

        events = await collect_events(stream_minimal_demo(original, delay_ms=1))
        full_text = get_text_content(events).strip()

        assert full_text == original


@pytest.mark.asyncio
class TestErrorDemo:
    """Test error simulator demo."""

    async def test_generates_error_event(self):
        """Error demo generates error event."""
        events = await collect_events(stream_error_demo(error_after_words=5))

        error_events = get_events_by_type(events, "error")
        assert len(error_events) == 1

        error = error_events[0]["data"]
        assert error["code"] == "simulated_error"
        assert error["recoverable"] is True

    async def test_streams_text_before_error(self):
        """Some text is streamed before error."""
        events = await collect_events(stream_error_demo(error_after_words=5))

        data_events = get_events_by_type(events, "data")
        assert len(data_events) > 0

    async def test_ends_with_error_done(self):
        """Error demo ends with done(reason=error)."""
        events = await collect_events(stream_error_demo(error_after_words=5))

        # Find done event (not done_marker)
        done_events = get_events_by_type(events, "done")
        assert len(done_events) == 1
        assert done_events[0]["data"]["reason"] == "error"
