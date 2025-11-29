"""
CoreModel - Base model for all REM entities.

All REM entities (Resources, Messages, Users, Files, Moments) inherit from CoreModel,
which provides:
- Identity (id - UUID or string, generated per model type)
- Temporal tracking (created_at, updated_at, deleted_at)
- Multi-tenancy (tenant_id)
- Ownership (user_id)
- Graph connectivity (graph_edges)
- Flexible metadata (metadata dict)
- Tagging (tags list)
"""

from datetime import datetime, timezone
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CoreModel(BaseModel):
    """
    Base model for all REM entities.

    Provides system-level fields for:
    - Identity management (id)
    - Temporal tracking (created_at, updated_at, deleted_at)
    - Multi-tenancy isolation (tenant_id)
    - Ownership tracking (user_id)
    - Graph connectivity (graph_edges)
    - Flexible metadata storage (metadata, tags)

    Note: ID generation is handled per model type, not by CoreModel.
    Each entity model should generate IDs with appropriate prefixes or labels.
    """

    id: Union[UUID, str, None] = Field(
        default=None,
        description="Unique identifier (UUID or string, generated per model type). Generated automatically if not provided."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), description="Entity creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None), description="Last update timestamp"
    )
    deleted_at: Optional[datetime] = Field(
        default=None, description="Soft deletion timestamp"
    )
    tenant_id: Optional[str] = Field(
        default=None, description="Tenant identifier for multi-tenancy isolation"
    )
    user_id: Optional[str] = Field(
        default=None,
        description=(
            "Owner user identifier (tenant-scoped). This is a VARCHAR(256), not a UUID, "
            "to allow flexibility for external identity providers. Typically generated as "
            "a hash of the user's email address. In future, other strong unique claims "
            "(e.g., OAuth sub, verified phone) could also be used for generation."
        ),
    )
    graph_edges: list[dict] = Field(
        default_factory=list,
        description="Knowledge graph edges stored as InlineEdge dicts",
    )
    metadata: dict = Field(
        default_factory=dict, description="Flexible metadata storage"
    )
    tags: list[str] = Field(default_factory=list, description="Entity tags")
