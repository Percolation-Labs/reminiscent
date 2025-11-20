"""
Message - Communication content in REM.

Messages represent individual communication units (chat messages, emails, etc.)
that can be grouped into conversations or moments.

Messages are simpler than Resources but share the same graph connectivity
through CoreModel inheritance.
"""

from pydantic import Field

from ..core import CoreModel


class Message(CoreModel):
    """
    Communication content unit.

    Represents individual messages in conversations, chats, or other
    communication contexts. Tenant isolation is provided via CoreModel.tenant_id field.
    """

    content: str = Field(
        ...,
        description="Message content text",
    )
    message_type: str | None = Field(
        default=None,
        description="Message type e.g role",
    )
    session_id: str | None = Field(
        default=None,
        description="Session identifier for tracking message context",
    )
