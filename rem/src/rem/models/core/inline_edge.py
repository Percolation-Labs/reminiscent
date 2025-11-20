"""
InlineEdge - Knowledge graph edge representation.

REM uses human-readable entity labels instead of UUIDs for graph edges,
enabling natural language queries without schema knowledge.

Key Design Decision:
- dst field contains LABELS (e.g., "sarah-chen", "tidb-migration-spec")
- NOT UUIDs (e.g., "550e8400-e29b-41d4-a716-446655440000")
- This enables LOOKUP operations on labels directly
- LLMs can query "LOOKUP sarah-chen" without knowing internal IDs

Edge Weight Guidelines:
- 1.0: Primary/strong relationships (authored_by, owns, part_of)
- 0.8-0.9: Important relationships (depends_on, reviewed_by, implements)
- 0.5-0.7: Secondary relationships (references, related_to, inspired_by)
- 0.3-0.4: Weak relationships (mentions, cites)

Entity Type Convention (in properties.dst_entity_type):
- Format: <schema>[/<category>]
- Examples: person/employee, document/rfc, system/api, project/internal
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class InlineEdge(BaseModel):
    """
    Knowledge graph edge with human-readable destination labels.

    Stores relationships between entities using natural language labels
    instead of UUIDs, enabling conversational queries.
    """

    dst: str = Field(
        ...,
        description="Human-readable destination key (e.g., 'tidb-migration-spec', 'sarah-chen')",
    )
    rel_type: str = Field(
        ...,
        description="Relationship type (e.g., 'builds-on', 'authored_by', 'references')",
    )
    weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relationship strength (0.0-1.0)",
    )
    properties: dict = Field(
        default_factory=dict,
        description="Rich metadata (dst_name, dst_entity_type, confidence, context, etc.)",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Edge creation timestamp"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class InlineEdges(BaseModel):
    """
    Collection of InlineEdge objects.

    Used for structured edge operations and batch processing.
    """

    edges: list[InlineEdge] = Field(
        default_factory=list, description="List of graph edges"
    )

    def add_edge(
        self,
        dst: str,
        rel_type: str,
        weight: float = 0.5,
        properties: Optional[dict] = None,
    ) -> None:
        """Add a new edge to the collection."""
        edge = InlineEdge(
            dst=dst, rel_type=rel_type, weight=weight, properties=properties or {}
        )
        self.edges.append(edge)

    def filter_by_rel_type(self, rel_types: list[str]) -> list[InlineEdge]:
        """Filter edges by relationship types."""
        return [edge for edge in self.edges if edge.rel_type in rel_types]

    def filter_by_weight(self, min_weight: float = 0.0) -> list[InlineEdge]:
        """Filter edges by minimum weight threshold."""
        return [edge for edge in self.edges if edge.weight >= min_weight]
