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
- Column metadata (column dict for database schema information)
"""

from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field


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
    - Database schema metadata (column)

    Note: ID generation is handled per model type, not by CoreModel.
    Each entity model should generate IDs with appropriate prefixes or labels.
    """

    id: Union[UUID, str, None] = Field(
        default=None,
        description="Unique identifier (UUID or string, generated per model type). Generated automatically if not provided."
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="Entity creation timestamp"
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow, description="Last update timestamp"
    )
    deleted_at: Optional[datetime] = Field(
        default=None, description="Soft deletion timestamp"
    )
    tenant_id: Optional[str] = Field(
        default=None, description="Tenant identifier for multi-tenancy isolation"
    )
    user_id: Optional[str] = Field(
        default=None, description="Owner user identifier (tenant-scoped)"
    )
    graph_edges: list[dict] = Field(
        default_factory=list,
        description="Knowledge graph edges stored as InlineEdge dicts",
    )
    metadata: dict = Field(
        default_factory=dict, description="Flexible metadata storage"
    )
    tags: list[str] = Field(default_factory=list, description="Entity tags")
    column: dict = Field(
        default_factory=dict,
        description="Column metadata for database schema information",
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
