"""
Message - Communication content in REM.

Messages represent individual communication units (chat messages, emails, etc.)
that can be grouped into conversations or moments.

Messages are simpler than Resources but share the same graph connectivity
through CoreModel inheritance.

Trace Integration:
- trace_id: OTEL trace ID for linking to observability
- span_id: OTEL span ID for specific span reference
- These enable feedback to be attached to Phoenix annotations
"""

from pydantic import Field

from ..core import CoreModel


class Message(CoreModel):
    """
    Communication content unit.

    Represents individual messages in conversations, chats, or other
    communication contexts. Tenant isolation is provided via CoreModel.tenant_id field.

    Trace fields (trace_id, span_id) enable integration with OTEL/Phoenix
    for observability and feedback annotation.
    """

    content: str = Field(
        ...,
        description="Message content text",
    )
    message_type: str | None = Field(
        default=None,
        description="Message type e.g. role: 'user', 'assistant', 'system', 'tool'",
    )
    session_id: str | None = Field(
        default=None,
        description="Session identifier for tracking message context",
    )
    prompt: str | None = Field(
        default=None,
        description="Custom prompt used for this message (if overridden from default)",
    )
    model: str | None = Field(
        default=None,
        description="Model used for generating this message (provider:model format)",
    )
    token_count: int | None = Field(
        default=None,
        description="Token count for this message",
    )
    # OTEL/Phoenix trace integration
    trace_id: str | None = Field(
        default=None,
        description="OTEL trace ID for observability integration",
    )
    span_id: str | None = Field(
        default=None,
        description="OTEL span ID for specific span reference",
    )
