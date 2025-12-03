"""
OpenAI-compatible streaming relay for Pydantic AI agents.

Design Pattern:
- Uses Pydantic AI's agent.iter() to capture full execution including tool calls
- Emits rich SSE events: reasoning, tool_call, progress, metadata, text_delta
- Proper OpenAI SSE format with data: prefix and [DONE] terminator
- Error handling with graceful degradation

Key Insight
- agent.run_stream() stops after first output, missing tool calls
- agent.iter() provides complete execution with tool call visibility
- Use PartStartEvent to detect tool calls and thinking parts
- Use PartDeltaEvent with TextPartDelta/ThinkingPartDelta for streaming
- Use PartEndEvent to detect tool completion
- Use FunctionToolResultEvent to get tool results

SSE Format (OpenAI-compatible):
    data: {"id": "chatcmpl-...", "choices": [{"delta": {"content": "..."}}]}\\n\\n
    data: [DONE]\\n\\n

Extended SSE Format (Custom Events):
    event: reasoning\\ndata: {"type": "reasoning", "content": "..."}\\n\\n
    event: tool_call\\ndata: {"type": "tool_call", "tool_name": "...", "status": "started"}\\n\\n
    event: progress\\ndata: {"type": "progress", "step": 1, "total_steps": 3}\\n\\n
    event: metadata\\ndata: {"type": "metadata", "confidence": 0.95}\\n\\n

See sse_events.py for the full event type definitions.
"""

import json
import time
import uuid
from typing import AsyncGenerator

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

from .otel_utils import get_current_trace_context, get_tracer
from .models import (
    ChatCompletionMessageDelta,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
)
from .sse_events import (
    DoneEvent,
    MetadataEvent,
    ProgressEvent,
    ReasoningEvent,
    ToolCallEvent,
    format_sse_event,
)


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
    if request_id is None:
        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    created_at = int(time.time())
    start_time = time.time()
    is_first_chunk = True
    reasoning_step = 0
    current_step = 0
    total_steps = 3  # Model request, tool execution (optional), final response
    token_count = 0

    # Track active tool calls for completion events
    # Maps index -> (tool_name, tool_id) for correlating start/end events
    active_tool_calls: dict[int, tuple[str, str]] = {}
    # Queue of tool calls awaiting completion (FIFO for matching)
    pending_tool_completions: list[tuple[str, str]] = []
    # Track if metadata was registered via register_metadata tool
    metadata_registered = False

    try:
        # Emit initial progress event
        current_step = 1
        yield format_sse_event(ProgressEvent(
            step=current_step,
            total_steps=total_steps,
            label="Processing request",
            status="in_progress"
        ))

        # Use agent.iter() to get complete execution with tool calls
        async with agent.iter(prompt) as agent_run:
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
                                reasoning_step += 1
                                if event.part.content:
                                    yield format_sse_event(ReasoningEvent(
                                        content=event.part.content,
                                        step=reasoning_step
                                    ))

                            # Reasoning delta (streaming thinking)
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, ThinkingPartDelta
                            ):
                                if event.delta.content_delta:
                                    yield format_sse_event(ReasoningEvent(
                                        content=event.delta.content_delta,
                                        step=reasoning_step
                                    ))

                            # ============================================
                            # TEXT CONTENT START (initial text chunk)
                            # ============================================
                            elif isinstance(event, PartStartEvent) and isinstance(
                                event.part, TextPart
                            ):
                                # TextPart may contain initial content that needs to be emitted
                                if event.part.content:
                                    content = event.part.content
                                    token_count += len(content.split())

                                    content_chunk = ChatCompletionStreamResponse(
                                        id=request_id,
                                        created=created_at,
                                        model=model,
                                        choices=[
                                            ChatCompletionStreamChoice(
                                                index=0,
                                                delta=ChatCompletionMessageDelta(
                                                    role="assistant" if is_first_chunk else None,
                                                    content=content,
                                                ),
                                                finish_reason=None,
                                            )
                                        ],
                                    )
                                    is_first_chunk = False
                                    yield f"data: {content_chunk.model_dump_json()}\n\n"

                            # ============================================
                            # TOOL CALL START EVENTS
                            # ============================================
                            elif isinstance(event, PartStartEvent) and isinstance(
                                event.part, ToolCallPart
                            ):
                                tool_name = event.part.tool_name

                                # Handle final_result specially - it's Pydantic AI's
                                # internal tool for structured output
                                if tool_name == "final_result":
                                    # Extract the structured result and emit as content
                                    args_dict = None
                                    if event.part.args is not None:
                                        if hasattr(event.part.args, 'args_dict'):
                                            args_dict = event.part.args.args_dict
                                        elif isinstance(event.part.args, dict):
                                            args_dict = event.part.args

                                    if args_dict:
                                        # Emit the structured result as JSON content
                                        result_json = json.dumps(args_dict, indent=2)
                                        content_chunk = ChatCompletionStreamResponse(
                                            id=request_id,
                                            created=created_at,
                                            model=model,
                                            choices=[
                                                ChatCompletionStreamChoice(
                                                    index=0,
                                                    delta=ChatCompletionMessageDelta(
                                                        role="assistant" if is_first_chunk else None,
                                                        content=result_json,
                                                    ),
                                                    finish_reason=None,
                                                )
                                            ],
                                        )
                                        is_first_chunk = False
                                        yield f"data: {content_chunk.model_dump_json()}\n\n"
                                    continue  # Skip regular tool call handling

                                tool_id = f"call_{uuid.uuid4().hex[:8]}"
                                active_tool_calls[event.index] = (tool_name, tool_id)
                                # Queue for completion matching (FIFO)
                                pending_tool_completions.append((tool_name, tool_id))

                                # Emit tool_call SSE event (started)
                                # Try to get arguments as dict
                                args_dict = None
                                if event.part.args is not None:
                                    if hasattr(event.part.args, 'args_dict'):
                                        args_dict = event.part.args.args_dict
                                    elif isinstance(event.part.args, dict):
                                        args_dict = event.part.args

                                # Log tool call with key parameters
                                if args_dict and tool_name == "search_rem":
                                    query_type = args_dict.get("query_type", "?")
                                    limit = args_dict.get("limit", 20)
                                    table = args_dict.get("table", "")
                                    query_text = args_dict.get("query_text", args_dict.get("entity_key", ""))
                                    if query_text and len(query_text) > 50:
                                        query_text = query_text[:50] + "..."
                                    logger.info(f"🔧 {tool_name} {query_type.upper()} '{query_text}' table={table} limit={limit}")
                                else:
                                    logger.info(f"🔧 {tool_name}")

                                yield format_sse_event(ToolCallEvent(
                                    tool_name=tool_name,
                                    tool_id=tool_id,
                                    status="started",
                                    arguments=args_dict
                                ))

                                # Update progress
                                current_step = 2
                                total_steps = 4  # Added tool execution step
                                yield format_sse_event(ProgressEvent(
                                    step=current_step,
                                    total_steps=total_steps,
                                    label=f"Calling {tool_name}",
                                    status="in_progress"
                                ))

                            # ============================================
                            # TOOL CALL COMPLETION (PartEndEvent)
                            # ============================================
                            elif isinstance(event, PartEndEvent) and isinstance(
                                event.part, ToolCallPart
                            ):
                                if event.index in active_tool_calls:
                                    tool_name, tool_id = active_tool_calls[event.index]
                                    # Note: result comes from FunctionToolResultEvent below
                                    # For now, mark as completed without result
                                    del active_tool_calls[event.index]

                            # ============================================
                            # TEXT CONTENT DELTA
                            # ============================================
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            ):
                                content = event.delta.content_delta
                                token_count += len(content.split())  # Rough token estimate

                                content_chunk = ChatCompletionStreamResponse(
                                    id=request_id,
                                    created=created_at,
                                    model=model,
                                    choices=[
                                        ChatCompletionStreamChoice(
                                            index=0,
                                            delta=ChatCompletionMessageDelta(
                                                role="assistant" if is_first_chunk else None,
                                                content=content,
                                            ),
                                            finish_reason=None,
                                        )
                                    ],
                                )
                                is_first_chunk = False
                                yield f"data: {content_chunk.model_dump_json()}\n\n"

                # ============================================
                # TOOL EXECUTION NODE
                # ============================================
                elif Agent.is_call_tools_node(node):
                    async with node.stream(agent_run.ctx) as tools_stream:
                        async for tool_event in tools_stream:
                            # Tool result event - emit completion
                            if isinstance(tool_event, FunctionToolResultEvent):
                                # Get the tool name/id from the pending queue (FIFO)
                                if pending_tool_completions:
                                    tool_name, tool_id = pending_tool_completions.pop(0)
                                else:
                                    # Fallback if queue is empty (shouldn't happen)
                                    tool_name = "tool"
                                    tool_id = f"call_{uuid.uuid4().hex[:8]}"

                                # Check if this is a register_metadata tool result
                                # It returns a dict with _metadata_event: True marker
                                result_content = tool_event.result.content if hasattr(tool_event.result, 'content') else tool_event.result
                                is_metadata_event = False

                                if isinstance(result_content, dict) and result_content.get("_metadata_event"):
                                    is_metadata_event = True
                                    metadata_registered = True  # Skip default metadata at end
                                    # Emit MetadataEvent with registered values
                                    registered_confidence = result_content.get("confidence")
                                    registered_sources = result_content.get("sources")
                                    registered_references = result_content.get("references")
                                    registered_flags = result_content.get("flags")
                                    # Session naming
                                    registered_session_name = result_content.get("session_name")
                                    # Risk assessment fields
                                    registered_risk_level = result_content.get("risk_level")
                                    registered_risk_score = result_content.get("risk_score")
                                    registered_risk_reasoning = result_content.get("risk_reasoning")
                                    registered_recommended_action = result_content.get("recommended_action")
                                    # Extra fields
                                    registered_extra = result_content.get("extra")

                                    logger.info(
                                        f"📊 Metadata registered: confidence={registered_confidence}, "
                                        f"session_name={registered_session_name}, "
                                        f"risk_level={registered_risk_level}, sources={registered_sources}"
                                    )

                                    # Build extra dict with risk fields and any custom extras
                                    extra_data = {}
                                    if registered_risk_level is not None:
                                        extra_data["risk_level"] = registered_risk_level
                                    if registered_risk_score is not None:
                                        extra_data["risk_score"] = registered_risk_score
                                    if registered_risk_reasoning is not None:
                                        extra_data["risk_reasoning"] = registered_risk_reasoning
                                    if registered_recommended_action is not None:
                                        extra_data["recommended_action"] = registered_recommended_action
                                    if registered_extra:
                                        extra_data.update(registered_extra)

                                    # Emit metadata event immediately
                                    yield format_sse_event(MetadataEvent(
                                        message_id=message_id,
                                        in_reply_to=in_reply_to,
                                        session_id=session_id,
                                        agent_schema=agent_schema,
                                        session_name=registered_session_name,
                                        confidence=registered_confidence,
                                        sources=registered_sources,
                                        model_version=model,
                                        flags=registered_flags,
                                        extra=extra_data if extra_data else None,
                                        hidden=False,
                                    ))

                                if not is_metadata_event:
                                    # Normal tool completion - emit ToolCallEvent
                                    result_str = str(result_content)
                                    result_summary = result_str[:200] + "..." if len(result_str) > 200 else result_str

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
                                        result=result_summary
                                    ))

                                # Update progress after tool completion
                                current_step = 3
                                yield format_sse_event(ProgressEvent(
                                    step=current_step,
                                    total_steps=total_steps,
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
                        token_count += len(result_json.split())

                        # Emit structured result as content
                        result_chunk = ChatCompletionStreamResponse(
                            id=request_id,
                            created=created_at,
                            model=model,
                            choices=[
                                ChatCompletionStreamChoice(
                                    index=0,
                                    delta=ChatCompletionMessageDelta(
                                        role="assistant" if is_first_chunk else None,
                                        content=result_json,
                                    ),
                                    finish_reason=None,
                                )
                            ],
                        )
                        is_first_chunk = False
                        yield f"data: {result_chunk.model_dump_json()}\n\n"
            except Exception as e:
                logger.debug(f"No structured result available: {e}")

        # Calculate latency
        latency_ms = int((time.time() - start_time) * 1000)

        # Final OpenAI chunk with finish_reason
        final_chunk = ChatCompletionStreamResponse(
            id=request_id,
            created=created_at,
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
        if not metadata_registered:
            yield format_sse_event(MetadataEvent(
                message_id=message_id,
                in_reply_to=in_reply_to,
                session_id=session_id,
                agent_schema=agent_schema,
                confidence=1.0,  # Default to 100% confidence
                model_version=model,
                latency_ms=latency_ms,
                token_count=token_count,
                # Include deterministic trace context captured from OTEL
                trace_id=captured_trace_id,
                span_id=captured_span_id,
            ))

        # Mark all progress complete
        for step in range(1, total_steps + 1):
            yield format_sse_event(ProgressEvent(
                step=step,
                total_steps=total_steps,
                label="Complete" if step == total_steps else f"Step {step}",
                status="completed"
            ))

        # Emit done event
        yield format_sse_event(DoneEvent(reason="stop"))

        # OpenAI termination marker (for compatibility)
        yield "data: [DONE]\n\n"

    except Exception as e:
        import traceback

        error_msg = str(e)
        logger.error(f"Streaming error: {error_msg}")
        logger.error(traceback.format_exc())

        # Send error as final chunk
        error_data = {
            "error": {
                "message": error_msg,
                "type": "internal_error",
                "code": "stream_error",
            }
        }
        yield f"data: {json.dumps(error_data)}\n\n"

        # Emit done event with error reason
        yield format_sse_event(DoneEvent(reason="error"))
        yield "data: [DONE]\n\n"


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


async def stream_openai_response_with_save(
    agent: Agent,
    prompt: str,
    model: str,
    request_id: str | None = None,
    agent_schema: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Wrapper around stream_openai_response that saves the assistant response after streaming.

    This accumulates all text content during streaming and saves it to the database
    after the stream completes.

    Args:
        agent: Pydantic AI agent instance
        prompt: User prompt
        model: Model name
        request_id: Optional request ID
        agent_schema: Agent schema name
        session_id: Session ID for message storage
        user_id: User ID for message storage

    Yields:
        SSE-formatted strings
    """
    from ....utils.date_utils import utc_now, to_iso
    from ....services.session import SessionMessageStore
    from ....settings import settings

    # Pre-generate message_id so it can be sent in metadata event
    # This allows frontend to use it for feedback before DB persistence
    message_id = str(uuid.uuid4())

    # Mutable container for capturing trace context from inside agent execution
    # This is deterministic - captured from OTEL instrumentation, not AI-generated
    trace_context: dict = {}

    # Accumulate content during streaming
    accumulated_content = []

    async for chunk in stream_openai_response(
        agent=agent,
        prompt=prompt,
        model=model,
        request_id=request_id,
        agent_schema=agent_schema,
        session_id=session_id,
        message_id=message_id,
        trace_context_out=trace_context,  # Pass container to capture trace IDs
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
                            accumulated_content.append(content)
            except (json.JSONDecodeError, KeyError, IndexError):
                pass  # Skip non-JSON or malformed chunks

    # After streaming completes, save the assistant response
    if settings.postgres.enabled and session_id and accumulated_content:
        full_content = "".join(accumulated_content)
        # Get captured trace context from container (deterministically captured inside agent execution)
        captured_trace_id = trace_context.get("trace_id")
        captured_span_id = trace_context.get("span_id")
        assistant_message = {
            "id": message_id,  # Use pre-generated ID for consistency with metadata event
            "role": "assistant",
            "content": full_content,
            "timestamp": to_iso(utc_now()),
            "trace_id": captured_trace_id,
            "span_id": captured_span_id,
        }
        try:
            store = SessionMessageStore(user_id=user_id or settings.test.effective_user_id)
            await store.store_session_messages(
                session_id=session_id,
                messages=[assistant_message],
                user_id=user_id,
                compress=True,  # Compress long assistant responses
            )
            logger.debug(f"Saved assistant response {message_id} to session {session_id} ({len(full_content)} chars)")
        except Exception as e:
            logger.error(f"Failed to save assistant response: {e}", exc_info=True)
