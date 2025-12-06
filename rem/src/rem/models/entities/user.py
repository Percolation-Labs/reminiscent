"""
User - User entity in REM.

Users represent people in the system, either as content creators,
participants in moments, or entities referenced in resources.

Users can be discovered through:
- Entity extraction from resources
- Moment present_persons lists
- Direct user registration
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import Field

from ..core import CoreModel


class UserTier(str, Enum):
    """User subscription tier for feature gating."""

    BLOCKED = "blocked"  # User is blocked from logging in
    ANONYMOUS = "anonymous"
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"
    SILVER = "silver"  # Deprecated? Keeping for backward compatibility if needed
    GOLD = "gold"      # Deprecated? Keeping for backward compatibility if needed


class User(CoreModel):
    """
    User entity.

    Represents people in the REM system, either as active users
    or entities extracted from content. Tenant isolation is provided
    via CoreModel.tenant_id field.

    Enhanced by dreaming worker:
    - summary: Generated from activity analysis
    - interests: Extracted from resources and sessions
    - activity_level: Computed from recent engagement
    - preferred_topics: Extracted from moment/resource topics
    """

    name: str = Field(
        ...,
        description="User name (human-readable, used as graph label)",
        json_schema_extra={"entity_key": True},  # Primary business key for KV lookups
    )
    email: Optional[str] = Field(
        default=None,
        description="User email address",
    )
    role: Optional[str] = Field(
        default=None,
        description="User role (employee, contractor, external, etc.)",
    )
    tier: UserTier = Field(
        default=UserTier.FREE,
        description="User subscription tier (free, basic, pro) for feature gating",
    )
    anonymous_ids: list[str] = Field(
        default_factory=list,
        description="Linked anonymous session IDs used for merging history",
    )
    sec_policy: dict = Field(
        default_factory=dict,
        description="Security policy configuration (JSON, extensible for custom policies)",
    )
    summary: Optional[str] = Field(
        default=None,
        description="LLM-generated user profile summary (updated by dreaming worker)",
    )
    interests: list[str] = Field(
        default_factory=list,
        description="User interests extracted from activity",
    )
    preferred_topics: list[str] = Field(
        default_factory=list,
        description="Frequently discussed topics in kebab-case",
    )
    activity_level: Optional[str] = Field(
        default=None,
        description="Activity level: active, moderate, inactive",
    )
    last_active_at: Optional[datetime] = Field(
        default=None,
        description="Last activity timestamp",
    )
