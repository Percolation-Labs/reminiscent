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
    arguments: dict | str | None,
    session_id: str | None,
    user_id: str | None,
) -> AsyncGenerator[str, None]:
    """
    Handle child_tool_start event.

    Actions:
    1. Log the tool call
    2. Emit SSE event
    3. Save to database (with tool_arguments in metadata for consistency with parent)
    """
    full_tool_name = f"{child_agent}:{tool_name}"
    tool_id = f"call_{uuid.uuid4().hex[:8]}"

    # Normalize arguments - may come as JSON string from ToolCallPart.args
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = None
    elif not isinstance(arguments, dict):
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

    # 3. SAVE TO DB (match parent format with tool_arguments for reconstruction)
    if session_id and settings.postgres.enabled:
        try:
            store = SessionMessageStore(
                user_id=user_id or settings.test.effective_user_id
            )
            tool_msg = {
                "role": "tool",
                "content": "",  # Content populated on completion
                "timestamp": to_iso(utc_now()),
                # Store tool call details for reconstruction (matches parent format)
                "tool_call_id": tool_id,
                "tool_name": full_tool_name,
                "tool_arguments": arguments,
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
    # Preserve full result dict if it contains an artifact (e.g. finalize_intake)
    # This is needed for frontend to extract artifact URLs for download
    if isinstance(result, dict) and result.get("artifact"):
        result_for_sse = result  # Full dict with artifact
    else:
        result_for_sse = str(result)[:200] if result else None

    yield format_sse_event(ToolCallEvent(
        tool_name=f"{child_agent}:tool",
        tool_id=f"call_{uuid.uuid4().hex[:8]}",
        status="completed",
        result=result_for_sse,
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
            async for chunk in process_child_event(
                child_event, state, session_id, user_id, message_id, agent_schema
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"Error processing child event: {e}")


async def process_child_event(
    child_event: dict,
    state: StreamingState,
    session_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
    agent_schema: str | None = None,
) -> AsyncGenerator[str, None]:
    """Process a single child event and yield SSE chunks."""
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


async def stream_with_child_events(
    tools_stream,
    child_event_sink: asyncio.Queue,
    state: StreamingState,
    session_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
    agent_schema: str | None = None,
) -> AsyncGenerator[tuple[str, Any], None]:
    """
    Multiplex tool events with child events using asyncio.wait().

    This is the key fix for child agent streaming - instead of draining
    the queue synchronously during tool event iteration, we concurrently
    listen to both sources and yield events as they arrive.

    Yields:
        Tuples of (event_type, event_data) where event_type is either
        "tool" or "child", allowing the caller to handle each appropriately.
    """
    tool_iter = tools_stream.__aiter__()

    # Create initial tasks
    pending_tool: asyncio.Task | None = None
    pending_child: asyncio.Task | None = None

    try:
        pending_tool = asyncio.create_task(tool_iter.__anext__())
    except StopAsyncIteration:
        # No tool events, just drain any remaining child events
        while not child_event_sink.empty():
            try:
                child_event = child_event_sink.get_nowait()
                yield ("child", child_event)
            except asyncio.QueueEmpty:
                break
        return

    # Start listening for child events with a short timeout
    pending_child = asyncio.create_task(
        _get_child_event_with_timeout(child_event_sink, timeout=0.05)
    )

    try:
        while True:
            # Wait for either source to produce an event
            tasks = {t for t in [pending_tool, pending_child] if t is not None}
            if not tasks:
                break

            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                try:
                    result = task.result()
                except asyncio.TimeoutError:
                    # Child queue timeout - restart listener
                    if task is pending_child:
                        pending_child = asyncio.create_task(
                            _get_child_event_with_timeout(child_event_sink, timeout=0.05)
                        )
                    continue
                except StopAsyncIteration:
                    # Tool stream exhausted
                    if task is pending_tool:
                        pending_tool = None
                        # Final drain of any remaining child events
                        if pending_child:
                            pending_child.cancel()
                            try:
                                await pending_child
                            except asyncio.CancelledError:
                                pass
                        while not child_event_sink.empty():
                            try:
                                child_event = child_event_sink.get_nowait()
                                yield ("child", child_event)
                            except asyncio.QueueEmpty:
                                break
                        return
                    continue

                if task is pending_child and result is not None:
                    # Got a child event
                    yield ("child", result)
                    # Restart child listener
                    pending_child = asyncio.create_task(
                        _get_child_event_with_timeout(child_event_sink, timeout=0.05)
                    )
                elif task is pending_tool:
                    # Got a tool event
                    yield ("tool", result)
                    # Get next tool event
                    try:
                        pending_tool = asyncio.create_task(tool_iter.__anext__())
                    except StopAsyncIteration:
                        pending_tool = None
                elif task is pending_child and result is None:
                    # Timeout with no event - restart listener
                    pending_child = asyncio.create_task(
                        _get_child_event_with_timeout(child_event_sink, timeout=0.05)
                    )
    finally:
        # Cleanup any pending tasks
        for task in [pending_tool, pending_child]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


async def _get_child_event_with_timeout(
    queue: asyncio.Queue, timeout: float = 0.05
) -> dict | None:
    """
    Get an event from the queue with a timeout.

    Returns None on timeout (no event available).
    This allows the multiplexer to check for tool events regularly.
    """
    try:
        return await asyncio.wait_for(queue.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None
