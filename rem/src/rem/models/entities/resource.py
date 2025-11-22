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

from pydantic import Field, model_validator

from ..core import CoreModel


class Resource(CoreModel):
    """
    Base content unit in REM.

    Resources are content units that feed into dreaming workflows for moment
    extraction and affinity graph construction. Tenant isolation is provided
    via CoreModel.tenant_id field.
    """

    name: Optional[str] = Field(
        default=None,
        description="Human-readable resource name (used as graph label). Auto-generated from uri+ordinal if not provided.",
        json_schema_extra={"entity_key": True},  # Primary business key for KV lookups
    )
    uri: Optional[str] = Field(
        default=None,
        description="Content URI or identifier (file path, URL, etc.)",
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

    @model_validator(mode='after')
    def generate_name_if_missing(self) -> 'Resource':
        """Auto-generate name from uri+ordinal if not provided."""
        if not self.name:
            if self.uri:
                # Extract filename from URI if possible
                uri_parts = self.uri.rstrip('/').split('/')
                filename = uri_parts[-1]

                # Remove file extension for cleaner names
                if '.' in filename:
                    filename = filename.rsplit('.', 1)[0]

                # Generate name with ordinal
                if self.ordinal > 0:
                    self.name = f"{filename}-chunk-{self.ordinal}"
                else:
                    self.name = filename
            else:
                # Fallback: use ID or generic name
                if self.id:
                    self.name = f"resource-{str(self.id)[:8]}"
                else:
                    self.name = "unnamed-resource"

        return self
