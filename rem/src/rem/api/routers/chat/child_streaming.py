"""
Child Agent Event Handling.

Handles events from child agents during multi-agent orchestration.

Event Flow:
```
Parent Agent (Siggy)
      │
      ▼
  ask_agent tool
      │
      ├──────────────────────────────────┐
      ▼                                  │
  Child Agent (intake_diverge)           │
      │                                  │
      ├── child_tool_start ──────────────┼──► Event Sink (Queue)
      ├── child_content ─────────────────┤
      └── child_tool_result ─────────────┘
                                         │
                                         ▼
                            drain_child_events()
                                         │
                                         ├── SSE to client
                                         └── DB persistence
```

IMPORTANT: When child_content is streamed, parent text output should be SKIPPED
to prevent content duplication.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any, AsyncGenerator

from loguru import logger

from .streaming_utils import StreamingState, build_content_chunk
from .sse_events import MetadataEvent, ToolCallEvent, format_sse_event
from ....services.session import SessionMessageStore
from ....settings import settings
from ....utils.date_utils import to_iso, utc_now

if TYPE_CHECKING:
    from ....agentic.context import AgentContext


async def handle_child_tool_start(
    state: StreamingState,
    child_agent: str,
    tool_name: str,
    arguments: dict | None,
    session_id: str | None,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """
    Handle child_tool_start event.

    Actions:
    1. Log the tool call
    2. Emit SSE event
    3. Save to database
    """
    full_tool_name = f"{child_agent}:{tool_name}"
    tool_id = f"call_{uuid.uuid4().hex[:8]}"

    # Normalize arguments
    if not isinstance(arguments, dict):
        arguments = None

    # 1. LOG
    logger.info(f"🔧 {full_tool_name}")

    # 2. EMIT SSE
    yield format_sse_event(ToolCallEvent(
        tool_name=full_tool_name,
        tool_id=tool_id,
        status="started",
        arguments=arguments,
    ))

    # 3. SAVE TO DB
    if session_id and settings.postgres.enabled:
        try:
            store = SessionMessageStore(
                user_id=user_id or settings.test.effective_user_id
            )
            tool_msg = {
                "role": "tool",
                "tool_name": full_tool_name,
                "content": json.dumps(arguments) if arguments else "",
                "timestamp": to_iso(utc_now()),
            }
            await store.store_session_messages(
                session_id=session_id,
                messages=[tool_msg],
                user_id=user_id,
                compress=False,
            )
        except Exception as e:
            logger.warning(f"Failed to save child tool call: {e}")


def handle_child_content(
    state: StreamingState,
    child_agent: str,
    content: str,
) -> str | None:
    """
    Handle child_content event.

    CRITICAL: Sets state.child_content_streamed = True
    This flag is used to skip parent text output and prevent duplication.

    Returns:
        SSE chunk or None if content is empty
    """
    if not content:
        return None

    # Track that child content was streamed
    # Parent text output should be SKIPPED when this is True
    state.child_content_streamed = True
    state.responding_agent = child_agent

    return build_content_chunk(state, content)


async def handle_child_tool_result(
    state: StreamingState,
    child_agent: str,
    result: Any,
    message_id: str | None,
    session_id: str | None,
    agent_schema: str | None,
) -> AsyncGenerator[str, None]:
    """
    Handle child_tool_result event.

    Actions:
    1. Log metadata if present
    2. Emit metadata event if present
    3. Emit tool completion event
    """
    # Check for metadata registration
    if isinstance(result, dict) and result.get("_metadata_event"):
        risk = result.get("risk_level", "")
        conf = result.get("confidence", "")
        logger.info(f"📊 {child_agent} metadata: risk={risk}, confidence={conf}")

        # Update responding agent from child
        if result.get("agent_schema"):
            state.responding_agent = result.get("agent_schema")

        # Build extra dict with risk fields
        extra_data = {}
        if risk:
            extra_data["risk_level"] = risk

        yield format_sse_event(MetadataEvent(
            message_id=message_id,
            session_id=session_id,
            agent_schema=agent_schema,
            responding_agent=state.responding_agent,
            confidence=result.get("confidence"),
            extra=extra_data if extra_data else None,
        ))

    # Emit tool completion
    yield format_sse_event(ToolCallEvent(
        tool_name=f"{child_agent}:tool",
        tool_id=f"call_{uuid.uuid4().hex[:8]}",
        status="completed",
        result=str(result)[:200] if result else None,
    ))


async def drain_child_events(
    event_sink: asyncio.Queue,
    state: StreamingState,
    session_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
    agent_schema: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Drain all pending child events from the event sink.

    This is called during tool execution to process events
    pushed by child agents via ask_agent.

    IMPORTANT: When child_content events are processed, this sets
    state.child_content_streamed = True. Callers should check this
    flag and skip parent text output to prevent duplication.
    """
    while not event_sink.empty():
        try:
            child_event = event_sink.get_nowait()
            event_type = child_event.get("type", "")
            child_agent = child_event.get("agent_name", "child")

            if event_type == "child_tool_start":
                async for chunk in handle_child_tool_start(
                    state=state,
                    child_agent=child_agent,
                    tool_name=child_event.get("tool_name", "tool"),
                    arguments=child_event.get("arguments"),
                    session_id=session_id,
                    user_id=user_id,
                ):
                    yield chunk

            elif event_type == "child_content":
                chunk = handle_child_content(
                    state=state,
                    child_agent=child_agent,
                    content=child_event.get("content", ""),
                )
                if chunk:
                    yield chunk

            elif event_type == "child_tool_result":
                async for chunk in handle_child_tool_result(
                    state=state,
                    child_agent=child_agent,
                    result=child_event.get("result"),
                    message_id=message_id,
                    session_id=session_id,
                    agent_schema=agent_schema,
                ):
                    yield chunk

        except Exception as e:
            logger.warning(f"Error processing child event: {e}")
