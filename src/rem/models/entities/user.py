"""
User - User entity in REM.

Users represent people in the system, either as content creators,
participants in moments, or entities referenced in resources.

Users can be discovered through:
- Entity extraction from resources
- Moment present_persons lists
- Direct user registration
"""

from typing import Optional

from pydantic import Field

from ..core import CoreModel


class User(CoreModel):
    """
    User entity.

    Represents people in the REM system, either as active users
    or entities extracted from content. Tenant isolation is provided
    via CoreModel.tenant_id field.
    """

    name: str = Field(
        ...,
        description="User name (human-readable, used as graph label)",
    )
    email: Optional[str] = Field(
        default=None,
        description="User email address",
    )
    role: Optional[str] = Field(
        default=None,
        description="User role (employee, contractor, external, etc.)",
    )
