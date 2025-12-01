"""
OpenAI-compatible API models for chat completions.

Design Pattern:
- Full OpenAI compatibility for drop-in replacement
- Support for streaming (SSE) and non-streaming modes
- Response format control (text vs json_object)
- Headers map to AgentContext for session/context control
- Body fields for OpenAI-compatible parameters + metadata

Headers (context control):
    X-User-Id        → context.user_id (user identifier)
    X-Tenant-Id      → context.tenant_id (multi-tenancy, default: "default")
    X-Session-Id     → context.session_id (conversation continuity)
    X-Agent-Schema   → context.agent_schema_uri (which agent to use, default: "rem")
    X-Model-Name     → context.default_model (model override)
    X-Chat-Is-Audio  → triggers audio transcription ("true"/"false")
    X-Is-Eval        → context.is_eval (marks session as evaluation, sets mode=EVALUATION)

Body Fields (OpenAI-compatible + extensions):
    model            → LLM model (e.g., "openai:gpt-4.1", "anthropic:claude-sonnet-4-5-20250929")
    messages         → Chat conversation history
    temperature      → Sampling temperature (0-2)
    max_tokens       → Max tokens (deprecated, use max_completion_tokens)
    max_completion_tokens → Max tokens to generate
    stream           → Enable SSE streaming
    metadata         → Key-value pairs merged with session metadata (for evals/experiments)
    store            → Whether to store for distillation/evaluation
    seed             → Deterministic sampling seed
    top_p            → Nucleus sampling probability
    reasoning_effort → low/medium/high for o-series models
    service_tier     → auto/flex/priority/default
"""

from typing import Any, Literal

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
        X-User-Id        → context.user_id
        X-Tenant-Id      → context.tenant_id (default: "default")
        X-Session-Id     → context.session_id
        X-Agent-Schema   → context.agent_schema_uri (default: "rem")
        X-Model-Name     → context.default_model
        X-Chat-Is-Audio  → triggers audio transcription
        X-Is-Eval        → context.is_eval (sets session mode=EVALUATION)

    Body Fields for Metadata/Evals:
        metadata         → Key-value pairs merged with session metadata
        store            → Whether to store for distillation/evaluation

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
    # Additional OpenAI-compatible fields
    metadata: dict[str, str] | None = Field(
        default=None,
        description="Key-value pairs attached to the request (max 16 keys, 64/512 char limits). "
        "Merged with session metadata for persistence.",
    )
    store: bool | None = Field(
        default=None,
        description="Whether to store for distillation/evaluation purposes.",
    )
    max_completion_tokens: int | None = Field(
        default=None,
        ge=1,
        description="Max tokens to generate (replaces deprecated max_tokens).",
    )
    seed: int | None = Field(
        default=None,
        description="Seed for deterministic sampling (best effort).",
    )
    top_p: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Nucleus sampling probability. Use temperature OR top_p, not both.",
    )
    logprobs: bool | None = Field(
        default=None,
        description="Whether to return log probabilities for output tokens.",
    )
    top_logprobs: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Number of most likely tokens to return at each position (requires logprobs=true).",
    )
    reasoning_effort: Literal["low", "medium", "high"] | None = Field(
        default=None,
        description="Reasoning effort for o-series models (low/medium/high).",
    )
    service_tier: Literal["auto", "flex", "priority", "default"] | None = Field(
        default=None,
        description="Service tier for processing (flex is 50% cheaper but slower).",
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
