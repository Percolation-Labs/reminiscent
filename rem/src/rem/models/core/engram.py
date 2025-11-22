"""
Engram - Core memory model for REM.

Engrams are structured memory documents that represent captured experiences,
observations, or insights. They are fundamentally Resources with optional
attached Moments, following the unified schema from the engram specification.

Key Design Principles:
- Engrams ARE Resources (category="engram")
- Human-friendly labels in graph edges (not UUIDs)
- Upsert with JSON merge behavior (never overwrite)
- Dual indexing: SQL + vector embeddings handled by repository
- YAML-first for human readability

Data Flow:
1. Upload YAML/JSON engram (API or S3)
2. Parse into Resource model
3. Call repository.upsert() - automatically handles:
   - SQL persistence
   - Vector embedding generation
   - Entity key index population
4. Create attached Moments (if present)
5. Link moments to parent engram via graph edges

Example Engram Structure:
```yaml
kind: engram
name: "Daily Team Standup"
category: "meeting"
summary: "Daily standup discussing sprint progress"
timestamp: "2025-11-16T09:00:00Z"
uri: "s3://recordings/2025/11/16/standup.m4a"
content: |
  Daily standup meeting with engineering team...

graph_edges:
  - dst: "Q4 Roadmap Discussion"
    rel_type: "semantic_similar"
    weight: 0.75
    properties:
      dst_name: "Q4 Roadmap Discussion"
      dst_entity_type: "resource/meeting"
      confidence: 0.75

moments:
  - name: "Sprint Progress Review"
    content: "Sarah reviewed completed tickets"
    summary: "Sprint progress update from Sarah"
    starts_timestamp: "2025-11-16T09:00:00Z"
    ends_timestamp: "2025-11-16T09:05:00Z"
    moment_type: "meeting"
    emotion_tags: ["focused", "productive"]
    topic_tags: ["sprint-progress", "velocity"]
    present_persons:
      - id: "sarah-chen"
        name: "Sarah Chen"
        role: "VP Engineering"
```

Graph Edge Labels:
- Use natural, human-friendly labels: "Sarah Chen", "Q4 Roadmap"
- NOT kebab-case unless it's a file path: "docs/api-spec.md"
- NOT UUIDs: "550e8400-e29b-41d4-a716-446655440000"
- Enables conversational queries: "LOOKUP Sarah Chen"

JSON Merge Behavior:
- Graph edges are MERGED, not replaced
- Metadata is MERGED, not replaced
- Arrays (tags) are MERGED and deduplicated
- Content/summary updated if provided
- Timestamps preserved if not provided

Best Practices:
- Use natural, descriptive names
- Include device metadata when available
- Use standard categories: diary, meeting, note, observation, conversation, media
- Attach moments for temporal segments
- Use appropriate relationship types in graph edges
- Always include timestamps in ISO 8601 format
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .inline_edge import InlineEdge


class DeviceMetadata(BaseModel):
    """Device metadata for engram capture context."""

    imei: Optional[str] = Field(
        default=None,
        description="Device IMEI identifier",
    )
    model: Optional[str] = Field(
        default=None,
        description="Device model (e.g., 'iPhone 15 Pro', 'MacBook Pro')",
    )
    os: Optional[str] = Field(
        default=None,
        description="Operating system (e.g., 'iOS 18.1', 'macOS 14.2')",
    )
    app: Optional[str] = Field(
        default=None,
        description="Application name (e.g., 'Percolate Voice', 'Percolate Desktop')",
    )
    version: Optional[str] = Field(
        default=None,
        description="Application version",
    )
    location: Optional[dict] = Field(
        default=None,
        description="GPS location data (latitude, longitude, accuracy, altitude, etc.)",
    )
    network: Optional[dict] = Field(
        default=None,
        description="Network information (type, carrier, signal_strength)",
    )


class EngramMoment(BaseModel):
    """
    Moment attached to an engram.

    Represents a temporal segment within an engram with specific
    temporal boundaries, present persons, and contextual metadata.
    """

    name: str = Field(
        ...,
        description="Moment name (human-readable)",
    )
    content: str = Field(
        ...,
        description="Moment content/description",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Brief summary of the moment",
    )
    moment_type: Optional[str] = Field(
        default=None,
        description="Moment type (meeting, conversation, reflection, etc.)",
    )
    category: Optional[str] = Field(
        default=None,
        description="Moment category for grouping",
    )
    uri: Optional[str] = Field(
        default=None,
        description="Source URI (can include time fragment, e.g., 's3://file.m4a#t=0,300')",
    )
    starts_timestamp: Optional[datetime] = Field(
        default=None,
        description="Moment start time",
    )
    ends_timestamp: Optional[datetime] = Field(
        default=None,
        description="Moment end time",
    )
    emotion_tags: list[str] = Field(
        default_factory=list,
        description="Emotional context tags (focused, excited, concerned, etc.)",
    )
    topic_tags: list[str] = Field(
        default_factory=list,
        description="Topic tags in kebab-case (sprint-progress, api-design, etc.)",
    )
    present_persons: list[dict] = Field(
        default_factory=list,
        description="People present (Person objects with id, name, role)",
    )
    speakers: Optional[list[dict]] = Field(
        default=None,
        description="Speaker segments with text, speaker_identifier, timestamp, emotion",
    )
    location: Optional[str] = Field(
        default=None,
        description="GPS coordinates or descriptive location",
    )
    background_sounds: Optional[str] = Field(
        default=None,
        description="Ambient sounds description",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Additional moment metadata",
    )
    graph_edges: list[InlineEdge] = Field(
        default_factory=list,
        description="Knowledge graph edges for this moment",
    )


class Engram(BaseModel):
    """
    Structured memory document for REM.

    Engrams are Resources with category="engram", optionally containing
    attached Moments. They represent captured experiences, observations,
    or insights with rich contextual metadata.

    Processing:
    - Upsert as Resource via repository.upsert()
    - Create attached Moments as separate entities
    - Link moments to parent via graph edges (rel_type="part_of")

    Chunking:
    - Summary chunking (if summary exists)
    - Content chunking (semantic-text-splitter for long content)
    - Moment chunking (each moment is a separate chunk)

    Embeddings:
    - Generated for resource summary
    - Generated for resource content (chunked if needed)
    - Generated for each attached moment content
    """

    kind: str = Field(
        default="engram",
        description="Resource kind (always 'engram')",
    )
    name: str = Field(
        ...,
        description="Engram name (human-readable, used as graph label)",
    )
    category: str = Field(
        default="engram",
        description="Engram category (diary, meeting, note, observation, conversation, media)",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Brief summary for semantic search (1-3 sentences)",
    )
    content: str = Field(
        default="",
        description="Full engram content",
    )
    uri: Optional[str] = Field(
        default=None,
        description="Resource URI (s3://, seaweedfs://, etc.)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        description="Engram timestamp (content creation time)",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Engram metadata (device info, etc.)",
    )
    graph_edges: list[InlineEdge] = Field(
        default_factory=list,
        description="Knowledge graph edges",
    )
    moments: list[EngramMoment] = Field(
        default_factory=list,
        description="Attached moments (temporal segments)",
    )

    @property
    def device(self) -> Optional[DeviceMetadata]:
        """Get device metadata if present."""
        device_data = self.metadata.get("device")
        if device_data:
            return DeviceMetadata(**device_data)
        return None

    def add_moment(
        self,
        name: str,
        content: str,
        summary: Optional[str] = None,
        moment_type: Optional[str] = None,
        starts_timestamp: Optional[datetime] = None,
        ends_timestamp: Optional[datetime] = None,
        **kwargs,
    ) -> EngramMoment:
        """
        Add a moment to this engram.

        Args:
            name: Moment name
            content: Moment content
            summary: Brief summary
            moment_type: Moment type
            starts_timestamp: Start time
            ends_timestamp: End time
            **kwargs: Additional moment fields

        Returns:
            Created EngramMoment
        """
        moment = EngramMoment(
            name=name,
            content=content,
            summary=summary,
            moment_type=moment_type,
            starts_timestamp=starts_timestamp,
            ends_timestamp=ends_timestamp,
            **kwargs,
        )
        self.moments.append(moment)
        return moment

    def add_graph_edge(
        self,
        dst: str,
        rel_type: str,
        weight: float = 0.5,
        properties: Optional[dict] = None,
    ) -> InlineEdge:
        """
        Add a graph edge to this engram.

        Args:
            dst: Human-friendly destination label
            rel_type: Relationship type
            weight: Edge weight (0.0-1.0)
            properties: Edge properties

        Returns:
            Created InlineEdge
        """
        edge = InlineEdge(
            dst=dst,
            rel_type=rel_type,
            weight=weight,
            properties=properties or {},
        )
        self.graph_edges.append(edge)
        return edge
