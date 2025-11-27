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
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
)

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
                                        import json
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

                                logger.info(f"🔧 {tool_name}")

                                # Emit tool_call SSE event (started)
                                # Try to get arguments as dict
                                args_dict = None
                                if event.part.args is not None:
                                    if hasattr(event.part.args, 'args_dict'):
                                        args_dict = event.part.args.args_dict
                                    elif isinstance(event.part.args, dict):
                                        args_dict = event.part.args

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

                                    logger.info(
                                        f"📊 Metadata registered: confidence={registered_confidence}, "
                                        f"sources={registered_sources}"
                                    )

                                    # Emit metadata event immediately
                                    yield format_sse_event(MetadataEvent(
                                        message_id=message_id,
                                        in_reply_to=in_reply_to,
                                        session_id=session_id,
                                        confidence=registered_confidence,
                                        sources=registered_sources,
                                        model_version=model,
                                        flags=registered_flags,
                                        hidden=False,
                                    ))

                                if not is_metadata_event:
                                    # Normal tool completion - emit ToolCallEvent
                                    result_str = str(result_content)
                                    result_summary = result_str[:200] + "..." if len(result_str) > 200 else result_str

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
            try:
                result = agent_run.result
                if result is not None and hasattr(result, 'output'):
                    output = result.output
                    # Serialize the structured output
                    if hasattr(output, 'model_dump'):
                        # Pydantic model
                        result_dict = output.model_dump()
                    elif hasattr(output, '__dict__'):
                        result_dict = output.__dict__
                    else:
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
                confidence=1.0,  # Default to 100% confidence
                model_version=model,
                latency_ms=latency_ms,
                token_count=token_count,
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
    from .sse_events import format_sse_event
    from rem.agentic.agents.sse_simulator import stream_simulator_events

    if request_id is None:
        request_id = f"sim-{uuid.uuid4().hex[:24]}"

    async for event in stream_simulator_events(
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
    ):
        yield format_sse_event(event)


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
    from .sse_events import format_sse_event
    from rem.agentic.agents.sse_simulator import stream_minimal_demo

    async for event in stream_minimal_demo(content=content, delay_ms=delay_ms):
        yield format_sse_event(event)
