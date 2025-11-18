"""
OpenAI-compatible streaming relay for Pydantic AI agents.

Design Pattern:
- Uses Pydantic AI's agent.iter() to capture full execution including tool calls
- Streams tool call events with [Calling: tool_name] markers
- Streams text content deltas as they arrive
- Proper OpenAI SSE format with data: prefix and [DONE] terminator
- Error handling with graceful degradation

Key Insight 
- agent.run_stream() stops after first output, missing tool calls
- agent.iter() provides complete execution with tool call visibility
- Use PartStartEvent to detect tool calls
- Use PartDeltaEvent with TextPartDelta for content streaming

SSE Format:
    data: {"id": "chatcmpl-...", "choices": [{"delta": {"content": "..."}}]}\\n\\n
    data: [DONE]\\n\\n
"""

import json
import time
import uuid
from typing import AsyncGenerator

from loguru import logger
from pydantic_ai.agent import Agent
from pydantic_ai.messages import (
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ToolCallPart,
)

from .models import (
    ChatCompletionMessageDelta,
    ChatCompletionStreamChoice,
    ChatCompletionStreamResponse,
)


async def stream_openai_response(
    agent: Agent,
    prompt: str,
    model: str,
    request_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream Pydantic AI agent responses in OpenAI SSE format with tool call events.

    Design Pattern:
    1. Use agent.iter() for complete execution (not run_stream())
    2. Iterate over nodes to capture model requests and tool executions
    3. Stream tool call start events as [Calling: tool_name]
    4. Stream text content deltas as they arrive
    5. Send final chunk with finish_reason="stop"
    6. Send OpenAI termination marker [DONE]

    Args:
        agent: Pydantic AI agent instance
        prompt: User prompt to run
        model: Model name for response metadata
        request_id: Optional request ID (generates UUID if not provided)

    Yields:
        SSE-formatted strings: "data: {json}\\n\\n"

    Example Stream:
        data: {"id": "chatcmpl-123", "choices": [{"delta": {"role": "assistant", "content": ""}}]}

        data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "[Calling: search]"}}]}

        data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "Found 3 results..."}}]}

        data: {"id": "chatcmpl-123", "choices": [{"delta": {}, "finish_reason": "stop"}]}

        data: [DONE]
    """
    if request_id is None:
        request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    created_at = int(time.time())
    is_first_chunk = True

    try:
        # Use agent.iter() to get complete execution with tool calls
        # run_stream() stops after first output, missing tool calls
        async with agent.iter(prompt) as agent_run:
            async for node in agent_run:
                # Check if this is a model request node (includes tool calls)
                if Agent.is_model_request_node(node):
                    # Stream events from model request
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            # Tool call start event
                            if isinstance(event, PartStartEvent) and isinstance(
                                event.part, ToolCallPart
                            ):
                                logger.info(f"🔧 {event.part.tool_name}")

                                tool_call_chunk = ChatCompletionStreamResponse(
                                    id=request_id,
                                    created=created_at,
                                    model=model,
                                    choices=[
                                        ChatCompletionStreamChoice(
                                            index=0,
                                            delta=ChatCompletionMessageDelta(
                                                role="assistant" if is_first_chunk else None,
                                                content=f"[Calling: {event.part.tool_name}]",
                                            ),
                                            finish_reason=None,
                                        )
                                    ],
                                )
                                is_first_chunk = False
                                yield f"data: {tool_call_chunk.model_dump_json()}\n\n"

                            # Text content delta
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            ):
                                content_chunk = ChatCompletionStreamResponse(
                                    id=request_id,
                                    created=created_at,
                                    model=model,
                                    choices=[
                                        ChatCompletionStreamChoice(
                                            index=0,
                                            delta=ChatCompletionMessageDelta(
                                                role="assistant" if is_first_chunk else None,
                                                content=event.delta.content_delta,
                                            ),
                                            finish_reason=None,
                                        )
                                    ],
                                )
                                is_first_chunk = False
                                yield f"data: {content_chunk.model_dump_json()}\n\n"

                # Check if this is a tool execution node
                elif Agent.is_call_tools_node(node):
                    # Stream tool execution - tools complete here
                    async with node.stream(agent_run.ctx) as tools_stream:
                        async for event in tools_stream:
                            # We can log tool completion here if needed
                            # For now, we already logged the call start above
                            pass

        # Final chunk with finish_reason
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

        # OpenAI termination marker
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
        yield "data: [DONE]\n\n"
