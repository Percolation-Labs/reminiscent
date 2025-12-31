"""
SSE Event Types for Rich Streaming Responses.

This module defines custom Server-Sent Events (SSE) event types that extend
beyond simple text streaming.

## SSE Protocol

Text content uses **OpenAI-compatible format** (plain `data:` prefix):
```
data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"Hello"}}]}
```

Custom events use **named event format** (`event:` prefix):
```
event: reasoning
data: {"type": "reasoning", "content": "Analyzing...", "step": 1}
```

## Event Types

| Event | Format | Purpose |
|-------|--------|---------|
| (text) | `data:` (OpenAI) | Content chunks - main response |
| reasoning | `event:` | Model thinking/chain-of-thought |
| progress | `event:` | Step indicators |
| tool_call | `event:` | Tool invocation start/complete |
| metadata | `event:` | System metadata (confidence, sources) |
| action_request | `event:` | UI solicitation (buttons, forms) |
| error | `event:` | Error notifications |
| done | `event:` | Stream completion marker |

## Action Schema Design

- Inspired by Microsoft Adaptive Cards (https://adaptivecards.io/)
- JSON Schema-based UI element definitions
- Cross-platform compatibility for React, mobile, etc.

## References

- MDN SSE: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
- Adaptive Cards: https://adaptivecards.io/explorer/
- Model Context Protocol: https://modelcontextprotocol.io/specification/2025-06-18
"""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class SSEEventType(str, Enum):
    """SSE event types for streaming responses."""

    TEXT_DELTA = "text_delta"       # Standard text chunk
    REASONING = "reasoning"          # Model thinking/reasoning
    ACTION_REQUEST = "action_request"  # UI action solicitation
    METADATA = "metadata"            # System metadata
    PROGRESS = "progress"            # Progress indicator
    TOOL_CALL = "tool_call"         # Tool invocation
    ERROR = "error"                 # Error notification
    DONE = "done"                   # Stream complete


# =============================================================================
# Action Solicitation Schema (Adaptive Cards-inspired)
# =============================================================================

class ActionStyle(str, Enum):
    """Visual style for action buttons."""

    DEFAULT = "default"
    PRIMARY = "primary"
    SECONDARY = "secondary"
    DESTRUCTIVE = "destructive"
    POSITIVE = "positive"


class ActionSubmit(BaseModel):
    """
    Submit action - triggers callback to server with payload.

    Inspired by Adaptive Cards Action.Submit:
    https://adaptivecards.io/explorer/Action.Submit.html
    """

    type: Literal["Action.Submit"] = "Action.Submit"
    id: str = Field(description="Unique action identifier")
    title: str = Field(description="Button label text")
    style: ActionStyle = Field(
        default=ActionStyle.DEFAULT,
        description="Visual style"
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Payload sent to server when action is triggered"
    )
    tooltip: str | None = Field(
        default=None,
        description="Tooltip text on hover"
    )
    icon_url: str | None = Field(
        default=None,
        description="Optional icon URL"
    )


class ActionOpenUrl(BaseModel):
    """
    Open URL action - navigates to external URL.

    Inspired by Adaptive Cards Action.OpenUrl:
    https://adaptivecards.io/explorer/Action.OpenUrl.html
    """

    type: Literal["Action.OpenUrl"] = "Action.OpenUrl"
    id: str = Field(description="Unique action identifier")
    title: str = Field(description="Button label text")
    url: str = Field(description="URL to open")
    style: ActionStyle = Field(default=ActionStyle.DEFAULT)
    tooltip: str | None = None


class ActionShowCard(BaseModel):
    """
    Show card action - reveals nested content inline.

    Inspired by Adaptive Cards Action.ShowCard:
    https://adaptivecards.io/explorer/Action.ShowCard.html
    """

    type: Literal["Action.ShowCard"] = "Action.ShowCard"
    id: str = Field(description="Unique action identifier")
    title: str = Field(description="Button label text")
    card: dict[str, Any] = Field(
        description="Nested card content to reveal (Adaptive Card JSON)"
    )
    style: ActionStyle = Field(default=ActionStyle.DEFAULT)


# Union type for all action types
ActionType = ActionSubmit | ActionOpenUrl | ActionShowCard


class InputText(BaseModel):
    """Text input field for action cards."""

    type: Literal["Input.Text"] = "Input.Text"
    id: str = Field(description="Input field identifier (used in submit payload)")
    label: str | None = Field(default=None, description="Input label")
    placeholder: str | None = Field(default=None, description="Placeholder text")
    is_required: bool = Field(default=False, description="Whether input is required")
    is_multiline: bool = Field(default=False, description="Multi-line text area")
    max_length: int | None = Field(default=None, description="Maximum character length")
    value: str | None = Field(default=None, description="Default value")


class InputChoiceSet(BaseModel):
    """Choice/select input for action cards."""

    type: Literal["Input.ChoiceSet"] = "Input.ChoiceSet"
    id: str = Field(description="Input field identifier")
    label: str | None = None
    choices: list[dict[str, str]] = Field(
        description="List of {title, value} choice objects"
    )
    is_required: bool = False
    is_multi_select: bool = Field(default=False, description="Allow multiple selections")
    value: str | None = Field(default=None, description="Default selected value")


class InputToggle(BaseModel):
    """Toggle/checkbox input for action cards."""

    type: Literal["Input.Toggle"] = "Input.Toggle"
    id: str = Field(description="Input field identifier")
    title: str = Field(description="Toggle label text")
    value: str = Field(default="false", description="Current value ('true'/'false')")
    value_on: str = Field(default="true", description="Value when toggled on")
    value_off: str = Field(default="false", description="Value when toggled off")


# Union type for all input types
InputType = InputText | InputChoiceSet | InputToggle


class ActionDisplayStyle(str, Enum):
    """How to display the action request in the UI."""

    INLINE = "inline"       # Rendered inline after message content
    FLOATING = "floating"   # Floating panel/overlay
    MODAL = "modal"         # Modal dialog


class ActionRequestCard(BaseModel):
    """
    Action solicitation card - requests user input or action.

    This is the main payload for action_request SSE events.
    Uses Adaptive Cards-inspired schema for cross-platform UI compatibility.

    Example use cases:
    - Confirm/cancel dialogs
    - Form inputs (name, email, etc.)
    - Multi-choice selections
    - Quick reply buttons
    - Feedback collection (thumbs up/down)

    Example:
        ```json
        {
            "id": "confirm-delete-123",
            "prompt": "Are you sure you want to delete this item?",
            "display_style": "modal",
            "actions": [
                {
                    "type": "Action.Submit",
                    "id": "confirm",
                    "title": "Delete",
                    "style": "destructive",
                    "data": {"action": "delete", "item_id": "123"}
                },
                {
                    "type": "Action.Submit",
                    "id": "cancel",
                    "title": "Cancel",
                    "style": "secondary",
                    "data": {"action": "cancel"}
                }
            ],
            "timeout_ms": 30000
        }
        ```
    """

    id: str = Field(description="Unique card identifier for response correlation")
    prompt: str = Field(description="Prompt text explaining what action is requested")
    display_style: ActionDisplayStyle = Field(
        default=ActionDisplayStyle.INLINE,
        description="How to display in the UI"
    )
    actions: list[ActionType] = Field(
        default_factory=list,
        description="Available actions (buttons)"
    )
    inputs: list[InputType] = Field(
        default_factory=list,
        description="Input fields for data collection"
    )
    timeout_ms: int | None = Field(
        default=None,
        description="Auto-dismiss timeout in milliseconds"
    )
    fallback_text: str | None = Field(
        default=None,
        description="Text to show if card rendering fails"
    )


# =============================================================================
# SSE Event Payloads
# =============================================================================

class TextDeltaEvent(BaseModel):
    """Text content delta event (OpenAI-compatible)."""

    type: Literal["text_delta"] = "text_delta"
    content: str = Field(description="Text content chunk")


class ReasoningEvent(BaseModel):
    """
    Reasoning/thinking event.

    Used to stream model's chain-of-thought reasoning separate from
    the main response content. UI can display this in a collapsible
    "thinking" section.
    """

    type: Literal["reasoning"] = "reasoning"
    content: str = Field(description="Reasoning text chunk")
    step: int | None = Field(
        default=None,
        description="Reasoning step number (for multi-step reasoning)"
    )


class ActionRequestEvent(BaseModel):
    """
    Action request event - solicits user action.

    Sent when the agent needs user input or confirmation.
    """

    type: Literal["action_request"] = "action_request"
    card: ActionRequestCard = Field(description="Action card definition")


class MetadataEvent(BaseModel):
    """
    Metadata event - system information (often hidden from user).

    Used for confidence scores, sources, model info, message IDs, etc.
    """

    type: Literal["metadata"] = "metadata"

    # Message correlation IDs
    message_id: str | None = Field(
        default=None,
        description="Database ID of the assistant message being streamed"
    )
    in_reply_to: str | None = Field(
        default=None,
        description="Database ID of the user message this is responding to"
    )
    session_id: str | None = Field(
        default=None,
        description="Session ID for this conversation"
    )

    # Agent info
    agent_schema: str | None = Field(
        default=None,
        description="Name of the top-level agent schema (e.g., 'siggy', 'rem')"
    )
    responding_agent: str | None = Field(
        default=None,
        description="Name of the agent that produced this response (may differ from agent_schema if delegated via ask_agent)"
    )

    # Session info
    session_name: str | None = Field(
        default=None,
        description="Short 1-3 phrase name for the session topic (e.g., 'Prescription Drug Questions', 'AWS Setup Help')"
    )

    # Quality indicators
    confidence: float | None = Field(
        default=None, ge=0, le=1,
        description="Confidence score (0-1)"
    )
    sources: list[str] | None = Field(
        default=None,
        description="Referenced sources/citations"
    )

    # Model info
    model_version: str | None = Field(
        default=None,
        description="Model version used"
    )

    # Performance metrics
    latency_ms: int | None = Field(
        default=None,
        description="Response latency in milliseconds"
    )
    token_count: int | None = Field(
        default=None,
        description="Token count for this response"
    )

    # Trace context for observability (deterministic, captured from OTEL)
    trace_id: str | None = Field(
        default=None,
        description="OTEL trace ID for correlating with Phoenix/observability systems"
    )
    span_id: str | None = Field(
        default=None,
        description="OTEL span ID for correlating with Phoenix/observability systems"
    )

    # System flags
    flags: list[str] | None = Field(
        default=None,
        description="System flags (e.g., 'uncertain', 'needs_review')"
    )
    hidden: bool = Field(
        default=False,
        description="If true, should not be displayed to user"
    )
    extra: dict[str, Any] | None = Field(
        default=None,
        description="Additional metadata"
    )


class ProgressEvent(BaseModel):
    """Progress indicator event."""

    type: Literal["progress"] = "progress"
    step: int = Field(description="Current step number")
    total_steps: int = Field(description="Total number of steps")
    label: str = Field(description="Step description")
    status: Literal["pending", "in_progress", "completed", "failed"] = Field(
        description="Step status"
    )


class ToolCallEvent(BaseModel):
    """Tool invocation event."""

    type: Literal["tool_call"] = "tool_call"
    tool_name: str = Field(description="Name of tool being called")
    tool_id: str | None = Field(
        default=None,
        description="Unique call identifier"
    )
    status: Literal["started", "completed", "failed"] = Field(
        description="Tool call status"
    )
    arguments: dict[str, Any] | None = Field(
        default=None,
        description="Tool arguments (for 'started' status)"
    )
    result: str | dict[str, Any] | None = Field(
        default=None,
        description="Tool result - full dict for finalize_intake, summary string for others"
    )
    error: str | None = Field(
        default=None,
        description="Error message (for 'failed' status)"
    )


class ErrorEvent(BaseModel):
    """Error notification event."""

    type: Literal["error"] = "error"
    code: str = Field(description="Error code")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] | None = Field(
        default=None,
        description="Additional error details"
    )
    recoverable: bool = Field(
        default=True,
        description="Whether error is recoverable"
    )


class DoneEvent(BaseModel):
    """Stream completion event."""

    type: Literal["done"] = "done"
    reason: Literal["stop", "length", "error", "cancelled"] = Field(
        default="stop",
        description="Completion reason"
    )


# Union type for all SSE events
SSEEvent = (
    TextDeltaEvent
    | ReasoningEvent
    | ActionRequestEvent
    | MetadataEvent
    | ProgressEvent
    | ToolCallEvent
    | ErrorEvent
    | DoneEvent
)


# =============================================================================
# SSE Formatting Helpers
# =============================================================================

def format_sse_event(event: SSEEvent) -> str:
    """
    Format an SSE event for transmission.

    Standard data: format for text_delta (OpenAI compatibility).
    Named event: format for other event types.

    Args:
        event: SSE event to format

    Returns:
        Formatted SSE string ready for transmission

    Example:
        >>> event = ReasoningEvent(content="Analyzing...")
        >>> format_sse_event(event)
        'event: reasoning\\ndata: {"type": "reasoning", "content": "Analyzing..."}\\n\\n'
    """
    import json

    event_json = event.model_dump_json()

    # TextDeltaEvent uses standard data: format for OpenAI compatibility
    if isinstance(event, TextDeltaEvent):
        return f"data: {event_json}\n\n"

    # DoneEvent uses special marker
    if isinstance(event, DoneEvent):
        return f"event: done\ndata: {event_json}\n\n"

    # All other events use named event format
    event_type = event.type
    return f"event: {event_type}\ndata: {event_json}\n\n"


def format_openai_sse_chunk(
    request_id: str,
    created: int,
    model: str,
    content: str | None = None,
    role: str | None = None,
    finish_reason: str | None = None,
) -> str:
    """
    Format OpenAI-compatible SSE chunk.

    Args:
        request_id: Request/response ID
        created: Unix timestamp
        model: Model name
        content: Delta content
        role: Message role (usually 'assistant')
        finish_reason: Finish reason (e.g., 'stop')

    Returns:
        Formatted SSE data line
    """
    import json

    delta = {}
    if role:
        delta["role"] = role
    if content is not None:
        delta["content"] = content

    chunk = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": delta,
            "finish_reason": finish_reason
        }]
    }

    return f"data: {json.dumps(chunk)}\n\n"
