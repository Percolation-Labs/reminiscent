"""
Feedback - User feedback on chat messages and sessions.

Feedback allows users to rate and categorize responses, providing
data for evaluation and model improvement. Feedback can be attached
to specific messages or entire sessions.

Trace Integration:
- Feedback references trace_id/span_id for OTEL/Phoenix integration
- Can attach annotations to Phoenix spans for unified observability

Predefined Categories (system-defined, extensible):
- INCOMPLETE: Response lacks expected information
- INACCURATE: Response contains factual errors
- POOR_TONE: Inappropriate or unprofessional tone
- OFF_TOPIC: Response doesn't address the question
- TOO_VERBOSE: Unnecessarily long response
- TOO_BRIEF: Insufficiently detailed response
- HELPFUL: Positive feedback marker
- EXCELLENT: Exceptionally good response
"""

from enum import Enum
from typing import Any

from pydantic import Field

from ..core import CoreModel


class FeedbackCategory(str, Enum):
    """Predefined feedback categories (system-defined)."""

    # Negative categories
    INCOMPLETE = "incomplete"
    INACCURATE = "inaccurate"
    POOR_TONE = "poor_tone"
    OFF_TOPIC = "off_topic"
    TOO_VERBOSE = "too_verbose"
    TOO_BRIEF = "too_brief"
    CONFUSING = "confusing"
    UNSAFE = "unsafe"

    # Positive categories
    HELPFUL = "helpful"
    EXCELLENT = "excellent"
    ACCURATE = "accurate"
    WELL_WRITTEN = "well_written"

    # Neutral/Other
    OTHER = "other"


class Feedback(CoreModel):
    """
    User feedback on a message or session.

    Captures structured feedback including:
    - Rating (1-5 scale or thumbs up/down)
    - Categories (predefined or custom)
    - Free-text comment
    - Trace reference for OTEL/Phoenix integration

    The feedback can be attached to:
    - A specific message (message_id set)
    - An entire session (session_id set, message_id null)
    """

    # Target reference (at least one required)
    session_id: str = Field(
        ...,
        description="Session ID this feedback relates to",
    )
    message_id: str | None = Field(
        default=None,
        description="Specific message ID (null for session-level feedback)",
    )

    # Rating (flexible: 1-5, or -1/1 for thumbs)
    rating: int | None = Field(
        default=None,
        ge=-1,
        le=5,
        description="Rating: -1 (thumbs down), 1 (thumbs up), or 1-5 scale",
    )

    # Categories (can select multiple)
    categories: list[str] = Field(
        default_factory=list,
        description="Selected feedback categories (from FeedbackCategory or custom)",
    )

    # Free-text comment
    comment: str | None = Field(
        default=None,
        description="Optional free-text feedback comment",
    )

    # Trace reference for OTEL/Phoenix integration
    trace_id: str | None = Field(
        default=None,
        description="OTEL trace ID for linking to observability",
    )
    span_id: str | None = Field(
        default=None,
        description="OTEL span ID for specific span feedback",
    )

    # Phoenix annotation status
    phoenix_synced: bool = Field(
        default=False,
        description="Whether feedback has been synced to Phoenix as annotation",
    )
    phoenix_annotation_id: str | None = Field(
        default=None,
        description="Phoenix annotation ID after sync",
    )

    # Annotator info
    annotator_kind: str = Field(
        default="HUMAN",
        description="Annotator type: HUMAN, LLM, CODE",
    )
