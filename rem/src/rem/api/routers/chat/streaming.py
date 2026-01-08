"""
OpenAI-compatible streaming relay for Pydantic AI agents.

Architecture:
```
User Request → stream_openai_response → agent.iter() → SSE Events → Client
                     │
                     ├── Parent agent events (text, tool calls)
                     │
                     └── Child agent events (via ask_agent tool)
                              │
                              ▼
                         Event Sink (asyncio.Queue)
                              │
                              ▼
                         drain_child_events() → SSE + DB
```

Modules:
- streaming.py: Main workflow orchestrator (this file)
- streaming_utils.py: Pure utility functions, StreamingState dataclass
- child_streaming.py: Child agent event handling

Key Design Decision (DUPLICATION FIX):
When child_content is streamed, state.child_content_streamed is set True.
Parent TextPartDelta events are SKIPPED when this flag is True,
preventing content from being emitted twice.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, AsyncGenerator

from loguru import logger
from pydantic_ai.agent import Agent
from pydantic_ai.messages import (
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
)

from .child_streaming import drain_child_events, stream_with_child_events, process_child_event
from .streaming_utils import (
    StreamingState,
    build_content_chunk,
    build_progress_event,
    build_tool_start_event,
    extract_metadata_from_result,
    extract_tool_args,
    log_tool_call,
)
from .otel_utils import get_current_trace_context
from .models import (
    ChatCompletionMessageDelta,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
)
from .sse_events import (
    DoneEvent,
    ErrorEvent,
    MetadataEvent,
    ProgressEvent,
    ReasoningEvent,
    ToolCallEvent,
    format_sse_event,
)
from ....services.session import SessionMessageStore
from ....settings import settings
from ....utils.date_utils import to_iso, utc_now

if TYPE_CHECKING:
    from ....agentic.context import AgentContext


async def stream_openai_response(
    agent: Agent,
    prompt: str,
    model: str,
    request_id: str | None = None,
    # Message correlation IDs for metadata
    message_id: str | None = None,
    in_reply_to: str | None = None,
    session_id: str | None = None,
    # Agent info for metadata
    agent_schema: str | None = None,
    # Mutable container to capture trace context (deterministic, not AI-dependent)
    trace_context_out: dict | None = None,
    # Mutable container to capture tool calls for persistence
    # Format: list of {"tool_name": str, "tool_id": str, "arguments": dict, "result": any}
    tool_calls_out: list | None = None,
    # Agent context for multi-agent propagation
    # When set, enables child agents to access parent context via get_current_context()
    agent_context: "AgentContext | None" = None,
    # Pydantic-ai native message history for proper tool call/return pairing
    message_history: list | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream Pydantic AI agent responses with rich SSE events.

    Emits all SSE event types matching the simulator:
    - reasoning: Model thinking/chain-of-thought (from ThinkingPart)
    - tool_call: Tool invocation start/complete (from ToolCallPart, FunctionToolResultEvent)
    - progress: Step indicators for multi-step execution
    - text_delta: Streamed content (OpenAI-compatible format)
    - metadata: Message IDs, model info, performance metrics
    - done: Stream completion

    Design Pattern:
    1. Use agent.iter() for complete execution (not run_stream())
    2. Iterate over nodes to capture model requests and tool executions
    3. Emit rich SSE events for reasoning, tools, progress
    4. Stream text content in OpenAI-compatible format
    5. Send metadata and done events at completion

    Args:
        agent: Pydantic AI agent instance
        prompt: User prompt to run
        model: Model name for response metadata
        request_id: Optional request ID (generates UUID if not provided)
        message_id: Database ID of the assistant message being streamed
        in_reply_to: Database ID of the user message this responds to
        session_id: Session ID for conversation correlation

    Yields:
        SSE-formatted strings

    Example Stream:
        event: progress
        data: {"type": "progress", "step": 1, "total_steps": 3, "label": "Processing", "status": "in_progress"}

        event: reasoning
        data: {"type": "reasoning", "content": "Analyzing the request..."}

        event: tool_call
        data: {"type": "tool_call", "tool_name": "search", "status": "started", "arguments": {...}}

        event: tool_call
        data: {"type": "tool_call", "tool_name": "search", "status": "completed", "result": "..."}

        data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "Found 3 results..."}}]}

        event: metadata
        data: {"type": "metadata", "message_id": "...", "latency_ms": 1234}

        event: done
        data: {"type": "done", "reason": "stop"}
    """
    # Initialize streaming state
    state = StreamingState.create(model=model, request_id=request_id)

    # Get effective user_id for database operations
    effective_user_id = agent_context.user_id if agent_context else None

    # Import context functions for multi-agent support
    from ....agentic.context import set_current_context, set_event_sink

    # Set up context for multi-agent propagation
    previous_context = None
    if agent_context is not None:
        from ....agentic.context import get_current_context
        previous_context = get_current_context()
        set_current_context(agent_context)

    # Set up event sink for child agent event proxying
    child_event_sink: asyncio.Queue = asyncio.Queue()
    set_event_sink(child_event_sink)

    try:
        # Emit initial progress event
        state.current_step = 1
        yield build_progress_event(
            step=state.current_step,
            total_steps=state.total_steps,
            label="Processing request",
        )

        # Use agent.iter() to get complete execution with tool calls
        # Pass message_history if available for proper tool call/return pairing
        iter_kwargs = {"message_history": message_history} if message_history else {}
        async with agent.iter(prompt, **iter_kwargs) as agent_run:
            # Capture trace context IMMEDIATELY inside agent execution
            # This is deterministic - it's the OTEL context from Pydantic AI instrumentation
            # NOT dependent on any AI-generated content
            captured_trace_id, captured_span_id = get_current_trace_context()
            if trace_context_out is not None:
                trace_context_out["trace_id"] = captured_trace_id
                trace_context_out["span_id"] = captured_span_id

            async for node in agent_run:
                # Check if this is a model request node (includes tool calls)
                if Agent.is_model_request_node(node):
                    # Stream events from model request
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            # ============================================
                            # REASONING EVENTS (ThinkingPart)
                            # ============================================
                            if isinstance(event, PartStartEvent) and isinstance(
                                event.part, ThinkingPart
                            ):
                                state.reasoning_step += 1
                                if event.part.content:
                                    yield format_sse_event(ReasoningEvent(
                                        content=event.part.content,
                                        step=state.reasoning_step
                                    ))

                            # Reasoning delta (streaming thinking)
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, ThinkingPartDelta
                            ):
                                if event.delta.content_delta:
                                    yield format_sse_event(ReasoningEvent(
                                        content=event.delta.content_delta,
                                        step=state.reasoning_step
                                    ))

                            # ============================================
                            # TEXT CONTENT START (initial text chunk)
                            # ============================================
                            elif isinstance(event, PartStartEvent) and isinstance(
                                event.part, TextPart
                            ):
                                # Skip if child already streamed content
                                if state.child_content_streamed:
                                    continue
                                if event.part.content:
                                    yield build_content_chunk(state, event.part.content)

                            # ============================================
                            # TOOL CALL START EVENTS
                            # ============================================
                            elif isinstance(event, PartStartEvent) and isinstance(
                                event.part, ToolCallPart
                            ):
                                tool_name = event.part.tool_name

                                # Handle final_result (Pydantic AI's internal tool)
                                if tool_name == "final_result":
                                    args_dict = extract_tool_args(event.part)
                                    if args_dict:
                                        result_json = json.dumps(args_dict, indent=2)
                                        yield build_content_chunk(state, result_json)
                                    continue

                                tool_id = f"call_{uuid.uuid4().hex[:8]}"
                                state.active_tool_calls[event.index] = (tool_name, tool_id)
                                state.pending_tool_completions.append((tool_name, tool_id))

                                # Extract and log arguments
                                args_dict = extract_tool_args(event.part)
                                log_tool_call(tool_name, args_dict)

                                yield build_tool_start_event(tool_name, tool_id, args_dict)

                                # Track for persistence
                                state.pending_tool_data[tool_id] = {
                                    "tool_name": tool_name,
                                    "tool_id": tool_id,
                                    "arguments": args_dict,
                                }

                                # Update progress
                                state.current_step = 2
                                state.total_steps = 4
                                yield build_progress_event(
                                    step=state.current_step,
                                    total_steps=state.total_steps,
                                    label=f"Calling {tool_name}",
                                )

                            # ============================================
                            # TOOL CALL COMPLETION (PartEndEvent)
                            # ============================================
                            elif isinstance(event, PartEndEvent) and isinstance(
                                event.part, ToolCallPart
                            ):
                                if event.index in state.active_tool_calls:
                                    tool_name, tool_id = state.active_tool_calls[event.index]
                                    args_dict = extract_tool_args(event.part)

                                    if tool_id in state.pending_tool_data:
                                        state.pending_tool_data[tool_id]["arguments"] = args_dict

                                    del state.active_tool_calls[event.index]

                            # ============================================
                            # TEXT CONTENT DELTA
                            # ============================================
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            ):
                                # DUPLICATION FIX: Skip parent text if child already streamed content
                                # Child agents stream via child_content events in ask_agent tool.
                                # If parent tries to echo that content, skip it.
                                if state.child_content_streamed:
                                    logger.debug("Skipping parent TextPartDelta - child content already streamed")
                                    continue

                                content = event.delta.content_delta
                                yield build_content_chunk(state, content)

                # ============================================
                # TOOL EXECUTION NODE
                # ============================================
                elif Agent.is_call_tools_node(node):
                    async with node.stream(agent_run.ctx) as tools_stream:
                        # Use concurrent multiplexer to handle both tool events
                        # and child agent events as they arrive (fixes streaming lag)
                        async for event_type, event_data in stream_with_child_events(
                            tools_stream=tools_stream,
                            child_event_sink=child_event_sink,
                            state=state,
                            session_id=session_id,
                            user_id=effective_user_id,
                            message_id=message_id,
                            agent_schema=agent_schema,
                        ):
                            # Handle child events (streamed from ask_agent)
                            if event_type == "child":
                                async for chunk in process_child_event(
                                    child_event=event_data,
                                    state=state,
                                    session_id=session_id,
                                    user_id=effective_user_id,
                                    message_id=message_id,
                                    agent_schema=agent_schema,
                                ):
                                    yield chunk
                                continue

                            # Handle tool events
                            tool_event = event_data

                            # Tool result event - emit completion
                            if isinstance(tool_event, FunctionToolResultEvent):
                                # Get the tool name/id from the pending queue (FIFO)
                                if state.pending_tool_completions:
                                    tool_name, tool_id = state.pending_tool_completions.pop(0)
                                else:
                                    tool_name = "tool"
                                    tool_id = f"call_{uuid.uuid4().hex[:8]}"

                                result_content = tool_event.result.content if hasattr(tool_event.result, 'content') else tool_event.result
                                is_metadata_event = False

                                # Handle register_metadata tool results
                                metadata = extract_metadata_from_result(result_content)
                                if metadata:
                                    is_metadata_event = True
                                    state.metadata_registered = True

                                    # Only set responding_agent if not already set by child
                                    if not state.responding_agent and metadata.get("agent_schema"):
                                        state.responding_agent = metadata["agent_schema"]

                                    logger.info(
                                        f"📊 Metadata: confidence={metadata.get('confidence')}, "
                                        f"risk_level={metadata.get('risk_level')}"
                                    )

                                    # Build extra dict with risk fields
                                    extra_data = {}
                                    for field in ["risk_level", "risk_score", "risk_reasoning", "recommended_action"]:
                                        if metadata.get(field) is not None:
                                            extra_data[field] = metadata[field]
                                    if metadata.get("extra"):
                                        extra_data.update(metadata["extra"])

                                    yield format_sse_event(MetadataEvent(
                                        message_id=message_id,
                                        in_reply_to=in_reply_to,
                                        session_id=session_id,
                                        agent_schema=agent_schema,
                                        responding_agent=state.responding_agent,
                                        session_name=metadata.get("session_name"),
                                        confidence=metadata.get("confidence"),
                                        sources=metadata.get("sources"),
                                        model_version=model,
                                        flags=metadata.get("flags"),
                                        extra=extra_data if extra_data else None,
                                        hidden=False,
                                    ))

                                # Get complete args from pending_tool_data
                                completed_args = None
                                if tool_id in state.pending_tool_data:
                                    completed_args = state.pending_tool_data[tool_id].get("arguments")

                                # Capture tool call for persistence
                                if tool_calls_out is not None and tool_id in state.pending_tool_data:
                                    tool_data = state.pending_tool_data[tool_id]
                                    tool_data["result"] = result_content
                                    tool_data["is_metadata"] = is_metadata_event
                                    tool_calls_out.append(tool_data)
                                    del state.pending_tool_data[tool_id]

                                if not is_metadata_event:
                                    # NOTE: text_response fallback is DISABLED
                                    # Child agents now stream content via child_content events (above)
                                    # which provides real-time streaming. The text_response in tool
                                    # result would duplicate that content, so we skip it entirely.

                                    # Normal tool completion - emit ToolCallEvent
                                    # For finalize_intake, send full result dict for frontend
                                    if tool_name == "finalize_intake" and isinstance(result_content, dict):
                                        result_for_sse = result_content
                                    else:
                                        result_str = str(result_content)
                                        result_for_sse = result_str[:200] + "..." if len(result_str) > 200 else result_str

                                    # Log result count for search_rem
                                    if tool_name == "search_rem" and isinstance(result_content, dict):
                                        results = result_content.get("results", {})
                                        # Handle nested result structure: results may be a dict with 'results' list and 'count'
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
                                        status = result_content.get("status", "unknown")
                                        # Truncate query text for logging
                                        if query_text and len(str(query_text)) > 40:
                                            query_text = str(query_text)[:40] + "..."
                                        logger.info(f"  ↳ {tool_name} {query_type} '{query_text}' table={table} → {count} results")

                                    yield format_sse_event(ToolCallEvent(
                                        tool_name=tool_name,
                                        tool_id=tool_id,
                                        status="completed",
                                        arguments=completed_args,
                                        result=result_for_sse
                                    ))

                                # Update progress after tool completion
                                state.current_step = 3
                                yield format_sse_event(ProgressEvent(
                                    step=state.current_step,
                                    total_steps=state.total_steps,
                                    label="Generating response",
                                    status="in_progress"
                                ))

            # After iteration completes, check for structured result
            # This handles agents with result_type (structured output)
            # Skip for plain text output - already streamed via TextPartDelta
            try:
                result = agent_run.result
                if result is not None and hasattr(result, 'output'):
                    output = result.output

                    # Skip plain string output - already streamed via TextPartDelta
                    # Non-structured output agents (structured_output: false) return strings
                    if isinstance(output, str):
                        logger.debug("Plain text output already streamed via TextPartDelta, skipping final emission")
                    else:
                        # Serialize the structured output (Pydantic models)
                        if hasattr(output, 'model_dump'):
                            # Pydantic model
                            result_dict = output.model_dump()
                        elif hasattr(output, '__dict__'):
                            result_dict = output.__dict__
                        else:
                            # Fallback for unknown types
                            result_dict = {"result": str(output)}

                        result_json = json.dumps(result_dict, indent=2, default=str)
                        state.token_count += len(result_json.split())

                        # Emit structured result as content
                        result_chunk = ChatCompletionStreamResponse(
                            id=state.request_id,
                            created=state.created_at,
                            model=model,
                            choices=[
                                ChatCompletionStreamChoice(
                                    index=0,
                                    delta=ChatCompletionMessageDelta(
                                        role="assistant" if state.is_first_chunk else None,
                                        content=result_json,
                                    ),
                                    finish_reason=None,
                                )
                            ],
                        )
                        state.is_first_chunk = False
                        yield f"data: {result_chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.debug(f"No structured result available: {e}")

        # Calculate latency
        latency_ms = state.latency_ms()

        # Final OpenAI chunk with finish_reason
        final_chunk = ChatCompletionStreamResponse(
            id=state.request_id,
            created=state.created_at,
            model=model,
            choices=[
                ChatCompletionStreamChoice(
                    index=0,
                    delta=ChatCompletionMessageDelta(),
                    finish_reason="stop",
                )
            ],
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"

        # Emit metadata event only if not already registered via register_metadata tool
        if not state.metadata_registered:
            yield format_sse_event(MetadataEvent(
                message_id=message_id,
                in_reply_to=in_reply_to,
                session_id=session_id,
                agent_schema=agent_schema,
                responding_agent=state.responding_agent,
                confidence=1.0,  # Default to 100% confidence
                model_version=model,
                latency_ms=latency_ms,
                token_count=state.token_count,
                # Include deterministic trace context captured from OTEL
                trace_id=captured_trace_id,
                span_id=captured_span_id,
            ))

        # Mark all progress complete
        for step in range(1, state.total_steps + 1):
            yield format_sse_event(ProgressEvent(
                step=step,
                total_steps=state.total_steps,
                label="Complete" if step == state.total_steps else f"Step {step}",
                status="completed"
            ))

        # Emit done event
        yield format_sse_event(DoneEvent(reason="stop"))

        # OpenAI termination marker (for compatibility)
        yield "data: [DONE]\n\n"

    except Exception as e:
        import traceback
        import re

        error_msg = str(e)

        # Parse error details for better client handling
        error_code = "stream_error"
        error_details: dict = {}
        recoverable = True

        # Check for rate limit errors (OpenAI 429)
        if "429" in error_msg or "rate_limit" in error_msg.lower() or "RateLimitError" in type(e).__name__:
            error_code = "rate_limit_exceeded"
            recoverable = True

            # Extract retry-after time from error message
            # Pattern: "Please try again in X.XXs" or "Please try again in Xs"
            retry_match = re.search(r"try again in (\d+(?:\.\d+)?)\s*s", error_msg)
            if retry_match:
                retry_seconds = float(retry_match.group(1))
                error_details["retry_after_seconds"] = retry_seconds
                error_details["retry_after_ms"] = int(retry_seconds * 1000)

            # Extract token usage info if available
            used_match = re.search(r"Used (\d+)", error_msg)
            limit_match = re.search(r"Limit (\d+)", error_msg)
            requested_match = re.search(r"Requested (\d+)", error_msg)
            if used_match:
                error_details["tokens_used"] = int(used_match.group(1))
            if limit_match:
                error_details["tokens_limit"] = int(limit_match.group(1))
            if requested_match:
                error_details["tokens_requested"] = int(requested_match.group(1))

            logger.error(f"🔴 Streaming error: status_code: 429, model_name: {model}, body: {error_msg[:200]}")

        # Check for authentication errors
        elif "401" in error_msg or "AuthenticationError" in type(e).__name__:
            error_code = "authentication_error"
            recoverable = False
            logger.error(f"🔴 Streaming error: Authentication failed")

        # Check for model not found / invalid model
        elif "404" in error_msg or "model" in error_msg.lower() and "not found" in error_msg.lower():
            error_code = "model_not_found"
            recoverable = False
            logger.error(f"🔴 Streaming error: Model not found")

        # Generic error
        else:
            logger.error(f"🔴 Streaming error: {error_msg}")

        logger.error(f"🔴 {traceback.format_exc()}")

        # Emit proper ErrorEvent via SSE (with event: prefix for client parsing)
        yield format_sse_event(ErrorEvent(
            code=error_code,
            message=error_msg,
            details=error_details if error_details else None,
            recoverable=recoverable,
        ))

        # Emit done event with error reason
        yield format_sse_event(DoneEvent(reason="error"))
        yield "data: [DONE]\n\n"

    finally:
        # Clean up event sink for multi-agent streaming
        set_event_sink(None)
        # Restore previous context for multi-agent support
        # This ensures nested agent calls don't pollute the parent's context
        if agent_context is not None:
            set_current_context(previous_context)


async def stream_simulator_response(
    prompt: str,
    model: str = "simulator-v1.0.0",
    request_id: str | None = None,
    delay_ms: int = 50,
    include_reasoning: bool = True,
    include_progress: bool = True,
    include_tool_calls: bool = True,
    include_actions: bool = True,
    include_metadata: bool = True,
    # Message correlation IDs
    message_id: str | None = None,
    in_reply_to: str | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream SSE simulator events for testing and demonstration.

    This function wraps the SSE simulator to produce formatted SSE strings
    ready for HTTP streaming. No LLM calls are made.

    The simulator produces a rich sequence of events:
    1. Reasoning events (model thinking)
    2. Progress events (step indicators)
    3. Tool call events (simulated tool usage)
    4. Text delta events (streamed content)
    5. Metadata events (confidence, sources, message IDs)
    6. Action request events (user interaction)
    7. Done event

    Args:
        prompt: User prompt (passed to simulator)
        model: Model name for metadata
        request_id: Optional request ID
        delay_ms: Delay between events in milliseconds
        include_reasoning: Whether to emit reasoning events
        include_progress: Whether to emit progress events
        include_tool_calls: Whether to emit tool call events
        include_actions: Whether to emit action request at end
        include_metadata: Whether to emit metadata event
        message_id: Database ID of the assistant message being streamed
        in_reply_to: Database ID of the user message this responds to
        session_id: Session ID for conversation correlation

    Yields:
        SSE-formatted strings ready for HTTP response

    Example:
        ```python
        from starlette.responses import StreamingResponse

        async def simulator_endpoint():
            return StreamingResponse(
                stream_simulator_response("demo"),
                media_type="text/event-stream"
            )
        ```
    """
    from rem.agentic.agents.sse_simulator import stream_simulator_events

    # Simulator now yields SSE-formatted strings directly (OpenAI-compatible)
    async for sse_string in stream_simulator_events(
        prompt=prompt,
        delay_ms=delay_ms,
        include_reasoning=include_reasoning,
        include_progress=include_progress,
        include_tool_calls=include_tool_calls,
        include_actions=include_actions,
        include_metadata=include_metadata,
        # Pass message correlation IDs
        message_id=message_id,
        in_reply_to=in_reply_to,
        session_id=session_id,
        model=model,
    ):
        yield sse_string


async def stream_minimal_simulator(
    content: str = "Hello from the simulator!",
    delay_ms: int = 30,
) -> AsyncGenerator[str, None]:
    """
    Stream minimal simulator output (text + done only).

    Useful for simple testing without the full event sequence.

    Args:
        content: Text content to stream
        delay_ms: Delay between chunks

    Yields:
        SSE-formatted strings
    """
    from rem.agentic.agents.sse_simulator import stream_minimal_demo

    # Simulator now yields SSE-formatted strings directly (OpenAI-compatible)
    async for sse_string in stream_minimal_demo(content=content, delay_ms=delay_ms):
        yield sse_string


async def save_user_message(
    session_id: str,
    user_id: str | None,
    content: str,
) -> None:
    """
    Save user message to database before streaming.

    Shared utility used by both API and CLI for consistent user message storage.
    """
    if not settings.postgres.enabled or not session_id:
        return

    user_msg = {
        "role": "user",
        "content": content,
        "timestamp": to_iso(utc_now()),
    }
    try:
        store = SessionMessageStore(user_id=user_id or settings.test.effective_user_id)
        await store.store_session_messages(
            session_id=session_id,
            messages=[user_msg],
            user_id=user_id,
            compress=False,
        )
        logger.debug(f"Saved user message to session {session_id}")
    except Exception as e:
        logger.error(f"Failed to save user message: {e}", exc_info=True)


async def stream_openai_response_with_save(
    agent: Agent,
    prompt: str,
    model: str,
    request_id: str | None = None,
    agent_schema: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    # Agent context for multi-agent propagation
    agent_context: "AgentContext | None" = None,
    # Pydantic-ai native message history for proper tool call/return pairing
    message_history: list | None = None,
) -> AsyncGenerator[str, None]:
    """
    Wrapper around stream_openai_response that saves the assistant response after streaming.

    This accumulates all text content during streaming and saves it to the database
    after the stream completes.

    NOTE: Call save_user_message() BEFORE this function to save the user's message.
    This function only saves tool calls and assistant responses.

    Args:
        agent: Pydantic AI agent instance
        prompt: User prompt
        model: Model name
        request_id: Optional request ID
        agent_schema: Agent schema name
        session_id: Session ID for message storage
        user_id: User ID for message storage
        agent_context: Agent context for multi-agent propagation (enables child agents)

    Yields:
        SSE-formatted strings
    """
    # Pre-generate message_id so it can be sent in metadata event
    # This allows frontend to use it for feedback before DB persistence
    message_id = str(uuid.uuid4())

    # Mutable container for capturing trace context from inside agent execution
    # This is deterministic - captured from OTEL instrumentation, not AI-generated
    trace_context: dict = {}

    # Accumulate content during streaming
    accumulated_content = []

    # Capture tool calls for persistence (especially register_metadata)
    tool_calls: list = []

    async for chunk in stream_openai_response(
        agent=agent,
        prompt=prompt,
        model=model,
        request_id=request_id,
        agent_schema=agent_schema,
        session_id=session_id,
        message_id=message_id,
        trace_context_out=trace_context,  # Pass container to capture trace IDs
        tool_calls_out=tool_calls,  # Capture tool calls for persistence
        agent_context=agent_context,  # Pass context for multi-agent support
        message_history=message_history,  # Native pydantic-ai message history
    ):
        yield chunk

        # Extract text content from OpenAI-format chunks
        # Format: data: {"choices": [{"delta": {"content": "..."}}]}
        if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
            try:
                data_str = chunk[6:].strip()  # Remove "data: " prefix
                if data_str:
                    data = json.loads(data_str)
                    if "choices" in data and data["choices"]:
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content")
                        if content:
                            # DEBUG: Check for [Calling markers in content
                            if "[Calling" in content:
                                logger.warning(f"DEBUG: Found [Calling in content chunk: {repr(content[:100])}")
                            accumulated_content.append(content)
            except (json.JSONDecodeError, KeyError, IndexError):
                pass  # Skip non-JSON or malformed chunks

    # After streaming completes, save tool calls and assistant response
    # Note: All messages stored UNCOMPRESSED. Compression happens on reload.
    if settings.postgres.enabled and session_id:
        # Get captured trace context from container (deterministically captured inside agent execution)
        captured_trace_id = trace_context.get("trace_id")
        captured_span_id = trace_context.get("span_id")
        timestamp = to_iso(utc_now())

        messages_to_store = []

        # First, store tool call messages (message_type: "tool")
        for tool_call in tool_calls:
            if not tool_call:
                continue
            tool_message = {
                "role": "tool",
                "content": json.dumps(tool_call.get("result", {}), default=str),
                "timestamp": timestamp,
                "trace_id": captured_trace_id,
                "span_id": captured_span_id,
                # Store tool call details in a way that can be reconstructed
                "tool_call_id": tool_call.get("tool_id"),
                "tool_name": tool_call.get("tool_name"),
                "tool_arguments": tool_call.get("arguments"),
            }
            messages_to_store.append(tool_message)

        # Then store assistant text response (if any)
        # Priority: direct TextPartDelta content > tool call text_response
        # When an agent delegates via ask_agent, the child's text_response becomes
        # the parent's assistant response (the parent is just orchestrating)
        full_content = None

        if accumulated_content:
            full_content = "".join(accumulated_content)
            logger.warning(f"DEBUG: Using accumulated_content ({len(accumulated_content)} chunks, {len(full_content)} chars)")
            logger.warning(f"DEBUG: First 200 chars: {repr(full_content[:200])}")
        else:
            logger.warning("DEBUG: accumulated_content is empty, checking text_response fallback")
            # No direct text from TextPartDelta - check tool results for text_response
            # This handles multi-agent delegation where child agent output is the response
            for tool_call in tool_calls:
                if not tool_call:
                    continue
                result = tool_call.get("result")
                if isinstance(result, dict) and result.get("text_response"):
                    text_response = result["text_response"]
                    if text_response and str(text_response).strip():
                        full_content = str(text_response)
                        logger.debug(
                            f"Using text_response from {tool_call.get('tool_name', 'tool')} "
                            f"({len(full_content)} chars) as assistant message"
                        )
                        break

        if full_content:
            assistant_message = {
                "id": message_id,  # Use pre-generated ID for consistency with metadata event
                "role": "assistant",
                "content": full_content,
                "timestamp": timestamp,
                "trace_id": captured_trace_id,
                "span_id": captured_span_id,
            }
            messages_to_store.append(assistant_message)

        if messages_to_store:
            try:
                store = SessionMessageStore(user_id=user_id or settings.test.effective_user_id)
                await store.store_session_messages(
                    session_id=session_id,
                    messages=messages_to_store,
                    user_id=user_id,
                    compress=False,  # Store uncompressed; compression happens on reload
                )
                logger.debug(
                    f"Saved {len(tool_calls)} tool calls and "
                    f"{'assistant response' if full_content else 'no text'} "
                    f"to session {session_id}"
                )
            except Exception as e:
                logger.error(f"Failed to save session messages: {e}", exc_info=True)

        # Update session description with session_name (non-blocking, after all yields)
        for tool_call in tool_calls:
            if tool_call and tool_call.get("tool_name") == "register_metadata" and tool_call.get("is_metadata"):
                arguments = tool_call.get("arguments") or {}
                session_name = arguments.get("session_name")
                if session_name:
                    try:
                        from ....models.entities import Session
                        from ....services.postgres import Repository
                        repo = Repository(Session, table_name="sessions")
                        session = await repo.get_by_id(session_id)
                        if session and session.description != session_name:
                            session.description = session_name
                            await repo.update(session)
                            logger.debug(f"Updated session {session_id} description to '{session_name}'")
                    except Exception as e:
                        logger.warning(f"Failed to update session description: {e}")
                    break
