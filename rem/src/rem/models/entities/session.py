"""
Session - Conversation sessions in REM.

Sessions group related messages together and can have different modes:
- normal: Standard conversation session
- evaluation: For LLM evaluation, stores original trace and overridden settings

Sessions allow overriding settings like model, temperature, and custom prompts
for evaluation and experimentation purposes.
"""

from enum import Enum

from pydantic import Field

from ..core import CoreModel


class SessionMode(str, Enum):
    """Session mode types."""

    NORMAL = "normal"
    EVALUATION = "evaluation"
    CLONE = "clone"


class Session(CoreModel):
    """
    Conversation session container.

    Groups messages together and supports different modes for normal conversations
    and evaluation/experimentation scenarios.

    For evaluation sessions, stores:
    - original_trace_id: Reference to the original session being evaluated
    - settings_overrides: Model, temperature, prompt overrides
    - prompt: Custom prompt being tested

    Default sessions are lightweight - just a session_id on messages.
    Special sessions store additional metadata for experiments.
    """

    name: str = Field(
        ...,
        description="Session name/identifier",
        json_schema_extra={"entity_key": True},
    )
    mode: SessionMode = Field(
        default=SessionMode.NORMAL,
        description="Session mode: 'normal' or 'evaluation'",
    )
    description: str | None = Field(
        default=None,
        description="Optional session description",
    )
    # Evaluation-specific fields
    original_trace_id: str | None = Field(
        default=None,
        description="For evaluation mode: ID of the original session/trace being evaluated",
    )
    settings_overrides: dict | None = Field(
        default=None,
        description="Settings overrides (model, temperature, max_tokens, system_prompt)",
    )
    prompt: str | None = Field(
        default=None,
        description="Custom prompt for this session (can override agent prompt)",
    )
    # Agent context
    agent_schema_uri: str | None = Field(
        default=None,
        description="Agent schema used for this session",
    )
    # Summary stats (updated as session progresses)
    message_count: int = Field(
        default=0,
        description="Number of messages in this session",
    )
    total_tokens: int | None = Field(
        default=None,
        description="Total tokens used in this session",
    )

    model_config = {"use_enum_values": True}
