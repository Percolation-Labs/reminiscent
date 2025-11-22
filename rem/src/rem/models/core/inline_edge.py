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

Destination Entity Type Convention (CRITICAL - properties.dst_entity_type):

Format: <table_schema>:<category>/<key>

Where:
- table_schema: Database table (resources, moments, users, etc.)
- category: Optional entity category within that table
- key: The actual entity key (must match dst field)

Examples:
- "resources:managers/bob" → Look up bob in resources table with category="managers"
- "users:engineers/sarah-chen" → Look up sarah-chen in users table with category="engineers"
- "moments:meetings/standup-2024-01" → Look up in moments table with category="meetings"
- "resources/api-design-v2" → Look up api-design-v2 in resources table (no category)
- "bob" → Defaults to resources table, no category (use sparingly)

IMPORTANT - Upsert Rules:
1. When upserting referenced entities, parse dst_entity_type to determine:
   - table_schema → which table to upsert into
   - category → set the 'category' field in that table
   - key → match against entity_key_field (usually 'name' or 'id')

2. If dst_entity_type is missing or just a type like "managers":
   - Default table_schema to "resources"
   - Set category to the type (e.g., "managers")
   - Use dst as the key

3. Agents should NEVER guess entity types
   - If type is unknown, omit dst_entity_type or set to null
   - Better to have no category than wrong category
   - System will handle entities without categories

4. Category is optional and can be null - this is perfectly fine
   - Categories enable filtering but are not required for graph traversal
   - Use categories when they add semantic value (roles, types, domains)

Edge Type Format Guidelines (rel_type):
- Use snake_case: "authored_by", "depends_on", "references"
- Be specific but consistent: "reviewed_by" not "reviewed"
- Use passive voice for bidirectional clarity: "authored_by" (reverse: "authors")
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class InlineEdge(BaseModel):
    """
    Knowledge graph edge with human-readable destination labels.

    Stores relationships between entities using natural language labels
    instead of UUIDs, enabling conversational queries.
    """

    dst: str = Field(
        ...,
        description="Human-readable destination key matching the entity's name/id field (e.g., 'tidb-migration-spec', 'sarah-chen', 'bob')",
    )
    rel_type: str = Field(
        ...,
        description="Relationship type in snake_case (e.g., 'authored_by', 'depends_on', 'references')",
    )
    weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relationship strength: 1.0=primary, 0.8-0.9=important, 0.5-0.7=secondary, 0.3-0.4=weak",
    )
    properties: dict = Field(
        default_factory=dict,
        description=(
            "Rich metadata. CRITICAL field: dst_entity_type with format 'table_schema:category/key' "
            "(e.g., 'resources:managers/bob', 'users:engineers/sarah-chen'). "
            "Used to determine upsert target table and category. Can be null/omitted if unknown."
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), description="Edge creation timestamp"
    )


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
