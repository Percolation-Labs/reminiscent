"""
OpenAI-compatible API models for chat completions.

Design Pattern 
- Full OpenAI compatibility for drop-in replacement
- Support for streaming (SSE) and non-streaming modes
- Response format control (text vs json_object)
- Headers map to AgentContext (X-User-Id, X-Tenant-Id, X-Agent-Schema, etc.)
"""

from typing import Literal

from pydantic import BaseModel, Field

from rem.settings import settings


# Request models
class ChatMessage(BaseModel):
    """OpenAI chat message format."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None


class ResponseFormat(BaseModel):
    """
    Response format specification (OpenAI-compatible).

    - text: Plain text response
    - json_object: Best-effort JSON extraction from agent output
    """

    type: Literal["text", "json_object"] = Field(
        default="text",
        description="Response format type. Use 'json_object' to enable JSON mode.",
    )


class ChatCompletionRequest(BaseModel):
    """
    OpenAI chat completion request format.

    Compatible with OpenAI's /v1/chat/completions endpoint.

    Headers Map to AgentContext:
    - X-User-Id → context.user_id
    - X-Tenant-Id → context.tenant_id
    - X-Session-Id → context.session_id
    - X-Agent-Schema → context.agent_schema_uri

    Note: Model is specified in body.model (standard OpenAI field), not headers.
    """

    # TODO: default should come from settings.llm.default_model at request time
    # Using None and resolving in endpoint to avoid import-time settings evaluation
    model: str | None = Field(
        default=None,
        description="Model to use. Defaults to LLM__DEFAULT_MODEL from settings.",
    )
    messages: list[ChatMessage] = Field(description="Chat conversation history")
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = Field(default=False, description="Enable SSE streaming")
    n: int | None = Field(default=1, ge=1, le=1, description="Number of completions (must be 1)")
    stop: str | list[str] | None = None
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    user: str | None = Field(default=None, description="Unique user identifier")
    response_format: ResponseFormat | None = Field(
        default=None,
        description="Response format. Set type='json_object' to enable JSON mode.",
    )


# Response models
class ChatCompletionUsage(BaseModel):
    """Token usage statistics."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionMessageDelta(BaseModel):
    """Streaming delta for chat completion."""

    role: Literal["system", "user", "assistant"] | None = None
    content: str | None = None


class ChatCompletionChoice(BaseModel):
    """Chat completion choice (non-streaming)."""

    index: int
    message: ChatMessage
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"] | None


class ChatCompletionStreamChoice(BaseModel):
    """Chat completion choice (streaming)."""

    index: int
    delta: ChatCompletionMessageDelta
    finish_reason: Literal["stop", "length", "content_filter"] | None = None


class ChatCompletionResponse(BaseModel):
    """OpenAI chat completion response (non-streaming)."""

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


class ChatCompletionStreamResponse(BaseModel):
    """OpenAI chat completion chunk (streaming)."""

    id: str
    object: Literal["chat.completion.chunk"] = "chat.completion.chunk"
    created: int
    model: str
    choices: list[ChatCompletionStreamChoice]
