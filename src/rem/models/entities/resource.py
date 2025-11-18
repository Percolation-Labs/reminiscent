"""
Resource - Base content unit in REM.

Resources represent documents, conversations, artifacts, and any other
content units that form the foundation of the REM memory system.

Resources are the primary input to dreaming workflows:
- First-order dreaming extracts Moments from Resources
- Second-order dreaming creates affinity edges between Resources
- Entity extraction populates related_entities field
- Graph edges stored in graph_edges (inherited from CoreModel)

Key Fields:
- name: Human-readable resource identifier (used in graph labels)
- uri: Content location or identifier
- content: Actual content text
- timestamp: Content creation/publication time
- category: Resource classification (document, conversation, artifact, etc.)
- related_entities: Extracted entities (people, projects, concepts)
"""

from datetime import datetime
from typing import Optional

from pydantic import Field

from ..core import CoreModel


class Resource(CoreModel):
    """
    Base content unit in REM.

    Resources are content units that feed into dreaming workflows for moment
    extraction and affinity graph construction. Tenant isolation is provided
    via CoreModel.tenant_id field.
    """

    name: str = Field(
        ...,
        description="Human-readable resource name (used as graph label)",
    )
    uri: Optional[str] = Field(
        default=None,
        description="Content URI or identifier (file path, URL, etc.)",
        json_schema_extra={"entity_key": True},  # Primary business key
    )
    ordinal: int = Field(
        default=0,
        description="Chunk ordinal for splitting large documents (0 for single-chunk resources)",
        json_schema_extra={"composite_key": True},  # Part of composite unique constraint
    )
    content: str = Field(
        default="",
        description="Resource content text",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Resource timestamp (content creation/publication time)",
    )
    category: Optional[str] = Field(
        default=None,
        description="Resource category (document, conversation, artifact, etc.)",
    )
    related_entities: list[dict] = Field(
        default_factory=list,
        description="Extracted entities (people, projects, concepts) with metadata",
    )
