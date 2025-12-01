"""
SSE Event Simulator Agent.

A programmatic simulator that generates rich SSE events for testing and
demonstrating the streaming protocol. NOT an LLM-based agent - this is
pure Python that emits scripted SSE events.

Usage:
    from rem.agentic.agents.simulator import stream_simulator_events

    async for event in stream_simulator_events("demo"):
        yield format_sse_event(event)

The simulator demonstrates:
1. Reasoning events (thinking process)
2. Text deltas (streamed content)
3. Progress indicators
4. Tool call events
5. Action solicitations (user interaction)
6. Metadata events
7. Done event

This is useful for:
- Frontend development without LLM costs
- Testing SSE parsing and rendering
- Demonstrating the full event protocol
- Load testing streaming infrastructure
"""

import asyncio
import time
import uuid
from typing import AsyncGenerator

from rem.api.routers.chat.sse_events import (
    ReasoningEvent,
    ActionRequestEvent,
    MetadataEvent,
    ProgressEvent,
    ToolCallEvent,
    DoneEvent,
    ActionRequestCard,
    ActionSubmit,
    ActionStyle,
    InputText,
    InputChoiceSet,
    ActionDisplayStyle,
    format_sse_event,
)
from rem.api.routers.chat.models import (
    ChatCompletionStreamResponse,
    ChatCompletionStreamChoice,
    ChatCompletionMessageDelta,
)


# =============================================================================
# Demo Content
# =============================================================================

DEMO_REASONING_STEPS = [
    "Analyzing the user's request...",
    "Considering the best approach to demonstrate SSE events...",
    "Planning a response that showcases all event types...",
    "Preparing rich markdown content with examples...",
]

DEMO_MARKDOWN_CONTENT = """# SSE Streaming Demo

This response demonstrates the **rich SSE event protocol** with multiple event types streamed in real-time.

## What You're Seeing

1. **Reasoning Events** - The "thinking" process shown in a collapsible section
2. **Text Streaming** - This markdown content, streamed word by word
3. **Progress Events** - Step indicators during processing
4. **Tool Calls** - Simulated tool invocations
5. **Action Requests** - Interactive UI elements for user input

## Code Example

```python
from rem.agentic.agents.simulator import stream_simulator_events

async def demo():
    async for event in stream_simulator_events("demo"):
        print(event.type, event)
```

## Features Table

| Event Type | Purpose | UI Display |
|------------|---------|------------|
| `reasoning` | Model thinking | Collapsible section |
| `text_delta` | Content chunks | Main response area |
| `progress` | Step indicators | Progress bar |
| `tool_call` | Tool invocations | Tool status panel |
| `action_request` | User input | Buttons/forms |
| `metadata` | System info | Hidden or badge |

## Summary

The SSE protocol enables rich, interactive AI experiences beyond simple text streaming. Each event type serves a specific purpose in the UI.

"""

DEMO_TOOL_CALLS = [
    ("search_knowledge", {"query": "SSE streaming best practices"}),
    ("format_response", {"style": "markdown", "include_examples": True}),
]

DEMO_PROGRESS_STEPS = [
    "Initializing response",
    "Generating content",
    "Formatting output",
    "Preparing actions",
]


# =============================================================================
# Simulator Functions
# =============================================================================

async def stream_simulator_events(
    prompt: str,
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
    # Model info
    model: str = "simulator-v1.0.0",
) -> AsyncGenerator[str, None]:
    """
    Generate a sequence of SSE events simulating an AI response.

    This is a programmatic simulator - no LLM calls are made.
    Events are yielded in a realistic order with configurable delays.

    Text content uses OpenAI-compatible format for consistency with real agents.
    Other events (reasoning, progress, tool_call, metadata) use named SSE events.

    Args:
        prompt: User prompt (used to vary output slightly)
        delay_ms: Delay between events in milliseconds
        include_reasoning: Whether to emit reasoning events
        include_progress: Whether to emit progress events
        include_tool_calls: Whether to emit tool call events
        include_actions: Whether to emit action request at end
        include_metadata: Whether to emit metadata event
        message_id: Database ID of the assistant message being streamed
        in_reply_to: Database ID of the user message this responds to
        session_id: Session ID for conversation correlation
        model: Model name for response metadata

    Yields:
        SSE-formatted strings ready for HTTP streaming

    Example:
        ```python
        async for sse_string in stream_simulator_events("demo"):
            print(sse_string)
        ```
    """
    delay = delay_ms / 1000.0
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created_at = int(time.time())
    is_first_chunk = True

    # Phase 1: Reasoning events
    if include_reasoning:
        for i, step in enumerate(DEMO_REASONING_STEPS):
            await asyncio.sleep(delay)
            yield format_sse_event(ReasoningEvent(content=step + "\n", step=i + 1))

    # Phase 2: Progress - Starting
    if include_progress:
        await asyncio.sleep(delay)
        yield format_sse_event(ProgressEvent(
            step=1,
            total_steps=len(DEMO_PROGRESS_STEPS),
            label=DEMO_PROGRESS_STEPS[0],
            status="in_progress"
        ))

    # Phase 3: Tool calls
    if include_tool_calls:
        for tool_name, args in DEMO_TOOL_CALLS:
            tool_id = f"call_{uuid.uuid4().hex[:8]}"

            await asyncio.sleep(delay)
            yield format_sse_event(ToolCallEvent(
                tool_name=tool_name,
                tool_id=tool_id,
                status="started",
                arguments=args
            ))

            await asyncio.sleep(delay * 3)  # Simulate tool execution
            yield format_sse_event(ToolCallEvent(
                tool_name=tool_name,
                tool_id=tool_id,
                status="completed",
                result=f"Retrieved data for {tool_name}"
            ))

    # Phase 4: Progress - Generating
    if include_progress:
        await asyncio.sleep(delay)
        yield format_sse_event(ProgressEvent(
            step=2,
            total_steps=len(DEMO_PROGRESS_STEPS),
            label=DEMO_PROGRESS_STEPS[1],
            status="in_progress"
        ))

    # Phase 5: Stream text content in OpenAI format
    words = DEMO_MARKDOWN_CONTENT.split(" ")
    buffer = ""
    for i, word in enumerate(words):
        buffer += word + " "
        # Emit every few words to simulate realistic streaming
        if len(buffer) > 20 or i == len(words) - 1:
            await asyncio.sleep(delay)
            # OpenAI-compatible format
            chunk = ChatCompletionStreamResponse(
                id=request_id,
                created=created_at,
                model=model,
                choices=[
                    ChatCompletionStreamChoice(
                        index=0,
                        delta=ChatCompletionMessageDelta(
                            role="assistant" if is_first_chunk else None,
                            content=buffer,
                        ),
                        finish_reason=None,
                    )
                ],
            )
            is_first_chunk = False
            yield f"data: {chunk.model_dump_json()}\n\n"
            buffer = ""

    # Phase 6: Progress - Formatting
    if include_progress:
        await asyncio.sleep(delay)
        yield format_sse_event(ProgressEvent(
            step=3,
            total_steps=len(DEMO_PROGRESS_STEPS),
            label=DEMO_PROGRESS_STEPS[2],
            status="in_progress"
        ))

    # Phase 7: Metadata (includes message correlation IDs)
    if include_metadata:
        await asyncio.sleep(delay)
        yield format_sse_event(MetadataEvent(
            # Message correlation IDs
            message_id=message_id,
            in_reply_to=in_reply_to,
            session_id=session_id,
            # Session info
            session_name="SSE Demo Session",
            # Quality indicators
            confidence=0.95,
            sources=["rem/api/routers/chat/sse_events.py", "rem/agentic/agents/sse_simulator.py"],
            # Model info
            model_version=model,
            # Performance metrics
            latency_ms=int(len(words) * delay_ms),
            token_count=len(words),
            # System flags
            flags=["demo_mode"],
            hidden=False,
            extra={"prompt_length": len(prompt)}
        ))

    # Phase 8: Progress - Preparing actions
    if include_progress:
        await asyncio.sleep(delay)
        yield format_sse_event(ProgressEvent(
            step=4,
            total_steps=len(DEMO_PROGRESS_STEPS),
            label=DEMO_PROGRESS_STEPS[3],
            status="in_progress"
        ))

    # Phase 9: Action solicitation
    if include_actions:
        await asyncio.sleep(delay)
        yield format_sse_event(ActionRequestEvent(
            card=ActionRequestCard(
                id=f"feedback-{uuid.uuid4().hex[:8]}",
                prompt="Was this SSE demonstration helpful?",
                display_style=ActionDisplayStyle.INLINE,
                actions=[
                    ActionSubmit(
                        id="helpful-yes",
                        title="Yes, very helpful!",
                        style=ActionStyle.POSITIVE,
                        data={"rating": 5, "feedback": "positive"}
                    ),
                    ActionSubmit(
                        id="helpful-somewhat",
                        title="Somewhat",
                        style=ActionStyle.DEFAULT,
                        data={"rating": 3, "feedback": "neutral"}
                    ),
                    ActionSubmit(
                        id="helpful-no",
                        title="Not really",
                        style=ActionStyle.SECONDARY,
                        data={"rating": 1, "feedback": "negative"}
                    ),
                ],
                inputs=[
                    InputText(
                        id="comments",
                        label="Any comments?",
                        placeholder="Optional feedback...",
                        is_multiline=True,
                        max_length=500
                    ),
                    InputChoiceSet(
                        id="use_case",
                        label="What's your use case?",
                        choices=[
                            {"title": "Frontend development", "value": "frontend"},
                            {"title": "Testing", "value": "testing"},
                            {"title": "Learning", "value": "learning"},
                            {"title": "Other", "value": "other"},
                        ],
                        is_required=False
                    ),
                ],
                timeout_ms=60000,
                fallback_text="Please provide feedback on this demo."
            )
        ))

    # Phase 10: Mark all progress complete
    if include_progress:
        for i, label in enumerate(DEMO_PROGRESS_STEPS):
            await asyncio.sleep(delay / 2)
            yield format_sse_event(ProgressEvent(
                step=i + 1,
                total_steps=len(DEMO_PROGRESS_STEPS),
                label=label,
                status="completed"
            ))

    # Phase 11: Final chunk with finish_reason
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

    # Phase 12: Done event
    await asyncio.sleep(delay)
    yield format_sse_event(DoneEvent(reason="stop"))

    # Phase 13: OpenAI termination marker
    yield "data: [DONE]\n\n"


async def stream_minimal_demo(
    content: str = "Hello from the simulator!",
    delay_ms: int = 30,
    model: str = "simulator-v1.0.0",
) -> AsyncGenerator[str, None]:
    """
    Generate a minimal SSE sequence with just text and done.

    Useful for simple testing without all event types.
    Uses OpenAI-compatible format for text content.

    Args:
        content: Text content to stream
        delay_ms: Delay between chunks
        model: Model name for response metadata

    Yields:
        SSE-formatted strings
    """
    delay = delay_ms / 1000.0
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created_at = int(time.time())
    is_first_chunk = True

    # Stream content word by word in OpenAI format
    words = content.split(" ")
    for word in words:
        await asyncio.sleep(delay)
        chunk = ChatCompletionStreamResponse(
            id=request_id,
            created=created_at,
            model=model,
            choices=[
                ChatCompletionStreamChoice(
                    index=0,
                    delta=ChatCompletionMessageDelta(
                        role="assistant" if is_first_chunk else None,
                        content=word + " ",
                    ),
                    finish_reason=None,
                )
            ],
        )
        is_first_chunk = False
        yield f"data: {chunk.model_dump_json()}\n\n"

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

    await asyncio.sleep(delay)
    yield format_sse_event(DoneEvent(reason="stop"))
    yield "data: [DONE]\n\n"


async def stream_error_demo(
    error_after_words: int = 10,
    model: str = "simulator-v1.0.0",
) -> AsyncGenerator[str, None]:
    """
    Generate an SSE sequence that ends with an error.

    Useful for testing error handling in the frontend.
    Uses OpenAI-compatible format for text content.

    Args:
        error_after_words: Number of words before error
        model: Model name for response metadata

    Yields:
        SSE-formatted strings including an error event
    """
    from rem.api.routers.chat.sse_events import ErrorEvent

    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created_at = int(time.time())
    is_first_chunk = True

    content = "This is a demo that will encounter an error during streaming. Watch what happens when things go wrong..."
    words = content.split(" ")

    for i, word in enumerate(words[:error_after_words]):
        await asyncio.sleep(0.03)
        chunk = ChatCompletionStreamResponse(
            id=request_id,
            created=created_at,
            model=model,
            choices=[
                ChatCompletionStreamChoice(
                    index=0,
                    delta=ChatCompletionMessageDelta(
                        role="assistant" if is_first_chunk else None,
                        content=word + " ",
                    ),
                    finish_reason=None,
                )
            ],
        )
        is_first_chunk = False
        yield f"data: {chunk.model_dump_json()}\n\n"

    await asyncio.sleep(0.1)
    yield format_sse_event(ErrorEvent(
        code="simulated_error",
        message="This is a simulated error for testing purposes",
        details={"words_sent": error_after_words, "demo": True},
        recoverable=True
    ))

    yield format_sse_event(DoneEvent(reason="error"))
    yield "data: [DONE]\n\n"
