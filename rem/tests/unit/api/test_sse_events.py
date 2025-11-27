"""
Unit tests for SSE event types and formatting.

Tests cover:
1. SSE event model validation
2. Action solicitation schema (Adaptive Cards-inspired)
3. SSE formatting helpers
4. Event serialization
"""

import pytest
from pydantic import ValidationError

from rem.api.routers.chat.sse_events import (
    # Event types
    SSEEventType,
    TextDeltaEvent,
    ReasoningEvent,
    ActionRequestEvent,
    MetadataEvent,
    ProgressEvent,
    ToolCallEvent,
    ErrorEvent,
    DoneEvent,
    # Action card components
    ActionRequestCard,
    ActionSubmit,
    ActionOpenUrl,
    ActionShowCard,
    ActionStyle,
    ActionDisplayStyle,
    InputText,
    InputChoiceSet,
    InputToggle,
    # Formatting helpers
    format_sse_event,
    format_openai_sse_chunk,
)


class TestSSEEventTypes:
    """Test SSE event type enum."""

    def test_event_type_values(self):
        """All event types have expected string values."""
        assert SSEEventType.TEXT_DELTA == "text_delta"
        assert SSEEventType.REASONING == "reasoning"
        assert SSEEventType.ACTION_REQUEST == "action_request"
        assert SSEEventType.METADATA == "metadata"
        assert SSEEventType.PROGRESS == "progress"
        assert SSEEventType.TOOL_CALL == "tool_call"
        assert SSEEventType.ERROR == "error"
        assert SSEEventType.DONE == "done"


class TestTextDeltaEvent:
    """Test text delta event model."""

    def test_basic_text_delta(self):
        """Create basic text delta event."""
        event = TextDeltaEvent(content="Hello ")
        assert event.type == "text_delta"
        assert event.content == "Hello "

    def test_empty_content(self):
        """Empty content is valid."""
        event = TextDeltaEvent(content="")
        assert event.content == ""

    def test_multiline_content(self):
        """Multiline content is preserved."""
        content = "Line 1\nLine 2\nLine 3"
        event = TextDeltaEvent(content=content)
        assert event.content == content


class TestReasoningEvent:
    """Test reasoning event model."""

    def test_basic_reasoning(self):
        """Create basic reasoning event."""
        event = ReasoningEvent(content="Thinking...")
        assert event.type == "reasoning"
        assert event.content == "Thinking..."
        assert event.step is None

    def test_reasoning_with_step(self):
        """Reasoning event with step number."""
        event = ReasoningEvent(content="Step 2 analysis", step=2)
        assert event.step == 2


class TestProgressEvent:
    """Test progress indicator event model."""

    def test_basic_progress(self):
        """Create basic progress event."""
        event = ProgressEvent(
            step=1, total_steps=3, label="Loading", status="in_progress"
        )
        assert event.type == "progress"
        assert event.step == 1
        assert event.total_steps == 3
        assert event.label == "Loading"
        assert event.status == "in_progress"

    def test_progress_statuses(self):
        """All progress statuses are valid."""
        for status in ["pending", "in_progress", "completed", "failed"]:
            event = ProgressEvent(
                step=1, total_steps=1, label="Test", status=status
            )
            assert event.status == status

    def test_invalid_status_rejected(self):
        """Invalid status raises validation error."""
        with pytest.raises(ValidationError):
            ProgressEvent(
                step=1, total_steps=1, label="Test", status="invalid"
            )


class TestToolCallEvent:
    """Test tool call event model."""

    def test_tool_started(self):
        """Tool call started event."""
        event = ToolCallEvent(
            tool_name="search_rem",
            tool_id="call_123",
            status="started",
            arguments={"query": "test"},
        )
        assert event.type == "tool_call"
        assert event.tool_name == "search_rem"
        assert event.status == "started"
        assert event.arguments == {"query": "test"}

    def test_tool_completed(self):
        """Tool call completed event."""
        event = ToolCallEvent(
            tool_name="search_rem",
            tool_id="call_123",
            status="completed",
            result="Found 5 results",
        )
        assert event.status == "completed"
        assert event.result == "Found 5 results"

    def test_tool_failed(self):
        """Tool call failed event."""
        event = ToolCallEvent(
            tool_name="search_rem",
            tool_id="call_123",
            status="failed",
            error="Connection timeout",
        )
        assert event.status == "failed"
        assert event.error == "Connection timeout"


class TestMetadataEvent:
    """Test metadata event model."""

    def test_basic_metadata(self):
        """Create basic metadata event."""
        event = MetadataEvent(confidence=0.95)
        assert event.type == "metadata"
        assert event.confidence == 0.95

    def test_full_metadata(self):
        """Metadata with all fields."""
        event = MetadataEvent(
            confidence=0.85,
            sources=["doc1.md", "doc2.md"],
            model_version="claude-3-sonnet",
            latency_ms=1500,
            token_count=250,
            flags=["uncertain"],
            hidden=False,
            extra={"custom": "data"},
        )
        assert event.sources == ["doc1.md", "doc2.md"]
        assert event.flags == ["uncertain"]
        assert event.extra == {"custom": "data"}

    def test_confidence_bounds(self):
        """Confidence must be between 0 and 1."""
        # Valid bounds
        MetadataEvent(confidence=0.0)
        MetadataEvent(confidence=1.0)

        # Invalid bounds
        with pytest.raises(ValidationError):
            MetadataEvent(confidence=-0.1)
        with pytest.raises(ValidationError):
            MetadataEvent(confidence=1.1)


class TestErrorEvent:
    """Test error event model."""

    def test_basic_error(self):
        """Create basic error event."""
        event = ErrorEvent(code="rate_limit", message="Too many requests")
        assert event.type == "error"
        assert event.code == "rate_limit"
        assert event.message == "Too many requests"
        assert event.recoverable is True  # Default

    def test_non_recoverable_error(self):
        """Non-recoverable error event."""
        event = ErrorEvent(
            code="internal_error",
            message="Something went wrong",
            details={"trace_id": "abc123"},
            recoverable=False,
        )
        assert event.recoverable is False
        assert event.details["trace_id"] == "abc123"


class TestDoneEvent:
    """Test done event model."""

    def test_basic_done(self):
        """Create basic done event."""
        event = DoneEvent()
        assert event.type == "done"
        assert event.reason == "stop"  # Default

    def test_done_reasons(self):
        """All done reasons are valid."""
        for reason in ["stop", "length", "error", "cancelled"]:
            event = DoneEvent(reason=reason)
            assert event.reason == reason


class TestActionSubmit:
    """Test Action.Submit model."""

    def test_basic_submit(self):
        """Create basic submit action."""
        action = ActionSubmit(id="btn-1", title="Click Me")
        assert action.type == "Action.Submit"
        assert action.id == "btn-1"
        assert action.title == "Click Me"
        assert action.style == ActionStyle.DEFAULT
        assert action.data == {}

    def test_submit_with_data(self):
        """Submit action with payload data."""
        action = ActionSubmit(
            id="confirm",
            title="Confirm",
            style=ActionStyle.PRIMARY,
            data={"action": "confirm", "item_id": 123},
            tooltip="Click to confirm",
        )
        assert action.style == ActionStyle.PRIMARY
        assert action.data["item_id"] == 123
        assert action.tooltip == "Click to confirm"


class TestActionOpenUrl:
    """Test Action.OpenUrl model."""

    def test_basic_open_url(self):
        """Create basic open URL action."""
        action = ActionOpenUrl(
            id="docs",
            title="View Docs",
            url="https://example.com/docs",
        )
        assert action.type == "Action.OpenUrl"
        assert action.url == "https://example.com/docs"


class TestInputTypes:
    """Test input field models."""

    def test_text_input(self):
        """Create text input."""
        input_field = InputText(
            id="name",
            label="Your Name",
            placeholder="Enter name...",
            is_required=True,
            max_length=100,
        )
        assert input_field.type == "Input.Text"
        assert input_field.is_required is True
        assert input_field.max_length == 100

    def test_multiline_text(self):
        """Multiline text input."""
        input_field = InputText(
            id="description",
            label="Description",
            is_multiline=True,
        )
        assert input_field.is_multiline is True

    def test_choice_set(self):
        """Choice set input."""
        input_field = InputChoiceSet(
            id="color",
            label="Pick a color",
            choices=[
                {"title": "Red", "value": "red"},
                {"title": "Blue", "value": "blue"},
                {"title": "Green", "value": "green"},
            ],
        )
        assert input_field.type == "Input.ChoiceSet"
        assert len(input_field.choices) == 3

    def test_multi_select_choice_set(self):
        """Multi-select choice set."""
        input_field = InputChoiceSet(
            id="tags",
            choices=[{"title": "A", "value": "a"}, {"title": "B", "value": "b"}],
            is_multi_select=True,
        )
        assert input_field.is_multi_select is True

    def test_toggle(self):
        """Toggle input."""
        input_field = InputToggle(id="agree", title="I agree to terms")
        assert input_field.type == "Input.Toggle"
        assert input_field.value == "false"
        assert input_field.value_on == "true"
        assert input_field.value_off == "false"


class TestActionRequestCard:
    """Test action request card model."""

    def test_basic_card(self):
        """Create basic action card."""
        card = ActionRequestCard(
            id="card-1",
            prompt="Choose an option",
            actions=[
                ActionSubmit(id="yes", title="Yes", style=ActionStyle.PRIMARY),
                ActionSubmit(id="no", title="No", style=ActionStyle.SECONDARY),
            ],
        )
        assert card.id == "card-1"
        assert card.prompt == "Choose an option"
        assert card.display_style == ActionDisplayStyle.INLINE  # Default
        assert len(card.actions) == 2

    def test_card_with_inputs(self):
        """Card with input fields."""
        card = ActionRequestCard(
            id="feedback",
            prompt="How was your experience?",
            display_style=ActionDisplayStyle.MODAL,
            actions=[ActionSubmit(id="submit", title="Submit")],
            inputs=[
                InputChoiceSet(
                    id="rating",
                    choices=[
                        {"title": "Great", "value": "5"},
                        {"title": "Good", "value": "4"},
                        {"title": "OK", "value": "3"},
                    ],
                ),
                InputText(id="comment", label="Comments", is_multiline=True),
            ],
            timeout_ms=30000,
        )
        assert card.display_style == ActionDisplayStyle.MODAL
        assert len(card.inputs) == 2
        assert card.timeout_ms == 30000

    def test_card_serialization(self):
        """Card serializes to valid JSON."""
        card = ActionRequestCard(
            id="test",
            prompt="Test",
            actions=[ActionSubmit(id="ok", title="OK")],
        )
        # Should not raise
        json_str = card.model_dump_json()
        assert "test" in json_str
        assert "Action.Submit" in json_str


class TestActionRequestEvent:
    """Test action request event model."""

    def test_action_request_event(self):
        """Create action request event."""
        card = ActionRequestCard(
            id="confirm-1",
            prompt="Confirm action?",
            actions=[ActionSubmit(id="yes", title="Yes")],
        )
        event = ActionRequestEvent(card=card)
        assert event.type == "action_request"
        assert event.card.id == "confirm-1"


class TestFormatSSEEvent:
    """Test SSE event formatting."""

    def test_format_text_delta(self):
        """Text delta uses data-only format."""
        event = TextDeltaEvent(content="Hello")
        formatted = format_sse_event(event)
        assert formatted.startswith("data: ")
        assert "text_delta" in formatted
        assert formatted.endswith("\n\n")
        # No "event:" prefix for OpenAI compatibility
        assert "event:" not in formatted

    def test_format_reasoning(self):
        """Reasoning uses named event format."""
        event = ReasoningEvent(content="Thinking...")
        formatted = format_sse_event(event)
        assert formatted.startswith("event: reasoning\n")
        assert "data: " in formatted

    def test_format_action_request(self):
        """Action request uses named event format."""
        card = ActionRequestCard(
            id="test",
            prompt="Test?",
            actions=[ActionSubmit(id="ok", title="OK")],
        )
        event = ActionRequestEvent(card=card)
        formatted = format_sse_event(event)
        assert "event: action_request" in formatted

    def test_format_done(self):
        """Done event format."""
        event = DoneEvent(reason="stop")
        formatted = format_sse_event(event)
        assert "event: done" in formatted

    def test_format_metadata(self):
        """Metadata event format."""
        event = MetadataEvent(confidence=0.9)
        formatted = format_sse_event(event)
        assert "event: metadata" in formatted

    def test_format_progress(self):
        """Progress event format."""
        event = ProgressEvent(
            step=1, total_steps=3, label="Loading", status="in_progress"
        )
        formatted = format_sse_event(event)
        assert "event: progress" in formatted


class TestFormatOpenAISSEChunk:
    """Test OpenAI-compatible SSE chunk formatting."""

    def test_basic_chunk(self):
        """Format basic content chunk."""
        formatted = format_openai_sse_chunk(
            request_id="req-123",
            created=1234567890,
            model="test-model",
            content="Hello",
        )
        assert formatted.startswith("data: ")
        assert "req-123" in formatted
        assert "Hello" in formatted
        assert formatted.endswith("\n\n")

    def test_chunk_with_role(self):
        """Chunk with role (first chunk)."""
        formatted = format_openai_sse_chunk(
            request_id="req-123",
            created=1234567890,
            model="test-model",
            role="assistant",
            content="",
        )
        assert "assistant" in formatted

    def test_final_chunk(self):
        """Final chunk with finish_reason."""
        formatted = format_openai_sse_chunk(
            request_id="req-123",
            created=1234567890,
            model="test-model",
            finish_reason="stop",
        )
        assert "stop" in formatted
