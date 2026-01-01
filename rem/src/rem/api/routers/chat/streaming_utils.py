"""
Streaming Utilities.

Pure functions and data structures for SSE streaming.
No I/O, no database calls - just data transformation.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from .models import (
    ChatCompletionMessageDelta,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
)
from .sse_events import (
    MetadataEvent,
    ProgressEvent,
    ReasoningEvent,
    ToolCallEvent,
    format_sse_event,
)


# =============================================================================
# STREAMING STATE
# =============================================================================

@dataclass
class StreamingState:
    """
    Tracks state during SSE streaming.

    This is a pure data container - no methods that do I/O.
    """
    request_id: str
    created_at: int
    model: str
    start_time: float = field(default_factory=time.time)

    # Content tracking
    is_first_chunk: bool = True
    token_count: int = 0

    # Child agent tracking - KEY FOR DUPLICATION FIX
    child_content_streamed: bool = False
    responding_agent: str | None = None

    # Tool tracking
    active_tool_calls: dict = field(default_factory=dict)  # index -> (name, id)
    pending_tool_completions: list = field(default_factory=list)  # FIFO queue
    pending_tool_data: dict = field(default_factory=dict)  # tool_id -> data

    # Reasoning tracking
    reasoning_step: int = 0

    # Progress tracking
    current_step: int = 0
    total_steps: int = 3

    # Metadata tracking
    metadata_registered: bool = False

    # Trace context (captured from OTEL)
    trace_id: str | None = None
    span_id: str | None = None

    @classmethod
    def create(cls, model: str, request_id: str | None = None) -> "StreamingState":
        """Create a new streaming state."""
        return cls(
            request_id=request_id or f"chatcmpl-{uuid.uuid4().hex[:24]}",
            created_at=int(time.time()),
            model=model,
        )

    def latency_ms(self) -> int:
        """Calculate latency since start."""
        return int((time.time() - self.start_time) * 1000)


# =============================================================================
# SSE CHUNK BUILDERS
# =============================================================================

def build_content_chunk(state: StreamingState, content: str) -> str:
    """
    Build an SSE content chunk in OpenAI format.

    Updates state.is_first_chunk and state.token_count.
    """
    state.token_count += len(content.split())

    chunk = ChatCompletionStreamResponse(
        id=state.request_id,
        created=state.created_at,
        model=state.model,
        choices=[
            ChatCompletionStreamChoice(
                index=0,
                delta=ChatCompletionMessageDelta(
                    role="assistant" if state.is_first_chunk else None,
                    content=content,
                ),
                finish_reason=None,
            )
        ],
    )
    state.is_first_chunk = False
    return f"data: {chunk.model_dump_json()}\n\n"


def build_final_chunk(state: StreamingState) -> str:
    """Build the final SSE chunk with finish_reason=stop."""
    chunk = ChatCompletionStreamResponse(
        id=state.request_id,
        created=state.created_at,
        model=state.model,
        choices=[
            ChatCompletionStreamChoice(
                index=0,
                delta=ChatCompletionMessageDelta(),
                finish_reason="stop",
            )
        ],
    )
    return f"data: {chunk.model_dump_json()}\n\n"


def build_reasoning_event(state: StreamingState, content: str) -> str:
    """Build a reasoning SSE event."""
    return format_sse_event(ReasoningEvent(
        content=content,
        step=state.reasoning_step,
    ))


def build_progress_event(
    step: int,
    total_steps: int,
    label: str,
    status: str = "in_progress",
) -> str:
    """Build a progress SSE event."""
    return format_sse_event(ProgressEvent(
        step=step,
        total_steps=total_steps,
        label=label,
        status=status,
    ))


def build_tool_start_event(
    tool_name: str,
    tool_id: str,
    arguments: dict | None = None,
) -> str:
    """Build a tool call started SSE event."""
    return format_sse_event(ToolCallEvent(
        tool_name=tool_name,
        tool_id=tool_id,
        status="started",
        arguments=arguments,
    ))


def build_tool_complete_event(
    tool_name: str,
    tool_id: str,
    arguments: dict | None = None,
    result: Any = None,
) -> str:
    """Build a tool call completed SSE event."""
    result_str = None
    if result is not None:
        result_str = str(result)
        if len(result_str) > 200:
            result_str = result_str[:200] + "..."

    return format_sse_event(ToolCallEvent(
        tool_name=tool_name,
        tool_id=tool_id,
        status="completed",
        arguments=arguments,
        result=result_str,
    ))


def build_metadata_event(
    message_id: str | None = None,
    in_reply_to: str | None = None,
    session_id: str | None = None,
    agent_schema: str | None = None,
    responding_agent: str | None = None,
    confidence: float | None = None,
    sources: list | None = None,
    model_version: str | None = None,
    latency_ms: int | None = None,
    token_count: int | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    extra: dict | None = None,
) -> str:
    """Build a metadata SSE event."""
    return format_sse_event(MetadataEvent(
        message_id=message_id,
        in_reply_to=in_reply_to,
        session_id=session_id,
        agent_schema=agent_schema,
        responding_agent=responding_agent,
        confidence=confidence,
        sources=sources,
        model_version=model_version,
        latency_ms=latency_ms,
        token_count=token_count,
        trace_id=trace_id,
        span_id=span_id,
        extra=extra,
    ))


# =============================================================================
# TOOL ARGUMENT EXTRACTION
# =============================================================================

def extract_tool_args(part) -> dict | None:
    """
    Extract arguments from a ToolCallPart.

    Handles various formats:
    - ArgsDict object with args_dict attribute
    - Plain dict
    - JSON string
    """
    if part.args is None:
        return None

    if hasattr(part.args, 'args_dict'):
        return part.args.args_dict

    if isinstance(part.args, dict):
        return part.args

    if isinstance(part.args, str) and part.args:
        try:
            return json.loads(part.args)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse tool args: {part.args[:100]}")

    return None


def log_tool_call(tool_name: str, args_dict: dict | None) -> None:
    """Log a tool call with key parameters."""
    if args_dict and tool_name == "search_rem":
        query_type = args_dict.get("query_type", "?")
        limit = args_dict.get("limit", 20)
        table = args_dict.get("table", "")
        query_text = args_dict.get("query_text", args_dict.get("entity_key", ""))
        if query_text and len(str(query_text)) > 50:
            query_text = str(query_text)[:50] + "..."
        logger.info(f"🔧 {tool_name} {query_type.upper()} '{query_text}' table={table} limit={limit}")
    else:
        logger.info(f"🔧 {tool_name}")


def log_tool_result(tool_name: str, result_content: Any) -> None:
    """Log a tool result with key metrics."""
    if tool_name == "search_rem" and isinstance(result_content, dict):
        results = result_content.get("results", {})
        if isinstance(results, dict):
            count = results.get("count", len(results.get("results", [])))
            query_type = results.get("query_type", "?")
            query_text = results.get("query_text", results.get("key", ""))
            table = results.get("table_name", "")
        elif isinstance(results, list):
            count = len(results)
            query_type = "?"
            query_text = ""
            table = ""
        else:
            count = "?"
            query_type = "?"
            query_text = ""
            table = ""

        if query_text and len(str(query_text)) > 40:
            query_text = str(query_text)[:40] + "..."
        logger.info(f"  ↳ {tool_name} {query_type} '{query_text}' table={table} → {count} results")


# =============================================================================
# METADATA EXTRACTION
# =============================================================================

def extract_metadata_from_result(result_content: Any) -> dict | None:
    """
    Extract metadata from a register_metadata tool result.

    Returns dict with extracted fields or None if not a metadata event.
    """
    if not isinstance(result_content, dict):
        return None

    if not result_content.get("_metadata_event"):
        return None

    return {
        "confidence": result_content.get("confidence"),
        "sources": result_content.get("sources"),
        "references": result_content.get("references"),
        "flags": result_content.get("flags"),
        "session_name": result_content.get("session_name"),
        "risk_level": result_content.get("risk_level"),
        "risk_score": result_content.get("risk_score"),
        "risk_reasoning": result_content.get("risk_reasoning"),
        "recommended_action": result_content.get("recommended_action"),
        "agent_schema": result_content.get("agent_schema"),
        "extra": result_content.get("extra"),
    }
