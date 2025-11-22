"""
Moment - Temporal narrative in REM.

Moments are extracted from Resources through first-order dreaming workflows.
They represent temporal narratives like meetings, coding sessions, conversations,
or any classified time period when users were focused on specific activities.

Moments provide temporal structure to the REM graph:
- Temporal boundaries (starts_timestamp, ends_timestamp)
- Present persons (who was involved)
- Emotion tags (team sentiment)
- Topic tags (what was discussed)
- Natural language summaries

Moments enable temporal queries:
- "What happened between milestone A and B?"
- "When did Sarah and Mike meet?"
- "What was discussed in Q4 retrospective?"

Data Model:
- Inherits from CoreModel (id, tenant_id, timestamps, graph_edges, etc.)
- name: Human-readable moment name
- moment_type: Classification (meeting, coding-session, conversation, etc.)
- starts_timestamp: Start time
- ends_timestamp: End time
- present_persons: List of Person objects with id, name, role
- emotion_tags: Sentiment tags (happy, frustrated, focused)
- topic_tags: Topic/concept tags (project names, technologies)
- summary: Natural language description
- source_resource_ids: Resources used to construct this moment
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from ..core import CoreModel


class Person(BaseModel):
    """Person reference in a moment."""

    id: str = Field(..., description="Person entity label")
    name: str = Field(..., description="Person name")
    role: Optional[str] = Field(default=None, description="Person role in moment")



class Moment(CoreModel):
    """
    Temporal narrative extracted from resources.

    Moments provide temporal structure and context for the REM graph,
    enabling time-based queries and understanding of when events occurred.
    Tenant isolation is provided via CoreModel.tenant_id field.
    """

    name: Optional[str] = Field(
        default=None,
        description="Human-readable moment name (used as graph label). Auto-generated from starts_timestamp+moment_type if not provided.",
        json_schema_extra={"entity_key": True},  # Primary business key for KV lookups
    )
    moment_type: Optional[str] = Field(
        default=None,
        description="Moment classification (meeting, coding-session, conversation, etc.)",
    )
    category: Optional[str] = Field(
        default=None,
        description="Moment category for grouping and filtering",
    )
    starts_timestamp: datetime = Field(
        ...,
        description="Moment start time",
    )
    ends_timestamp: Optional[datetime] = Field(
        default=None,
        description="Moment end time",
    )
    present_persons: list[Person] = Field(
        default_factory=list,
        description="People present in the moment",
    )

    emotion_tags: list[str] = Field(
        default_factory=list,
        description="Emotion/sentiment tags (happy, frustrated, focused, etc.)",
    )
    topic_tags: list[str] = Field(
        default_factory=list,
        description="Topic/concept tags (project names, technologies, etc.)",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Natural language summary of the moment",
    )
    source_resource_ids: list[str] = Field(
        default_factory=list,
        description="Resource IDs used to construct this moment",
    )

    @model_validator(mode='after')
    def generate_name_if_missing(self) -> 'Moment':
        """Auto-generate name from starts_timestamp+moment_type if not provided."""
        if not self.name:
            # Format: "Meeting on 2024-12-20" or "Coding Session on 2024-12-20 14:30"
            if self.starts_timestamp:
                date_str = self.starts_timestamp.strftime("%Y-%m-%d")
                time_str = self.starts_timestamp.strftime("%H:%M")

                if self.moment_type:
                    moment_label = self.moment_type.replace('-', ' ').replace('_', ' ').title()
                    self.name = f"{moment_label} on {date_str}"
                else:
                    self.name = f"Moment on {date_str} {time_str}"
            else:
                # Fallback: use ID or generic name
                if self.id:
                    self.name = f"moment-{str(self.id)[:8]}"
                else:
                    self.name = "unnamed-moment"

        return self
