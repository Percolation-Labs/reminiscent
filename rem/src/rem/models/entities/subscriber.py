"""
Subscriber - Email subscription management.

This model stores subscribers who sign up via websites/apps.
Subscribers can be collected before user registration for newsletters,
updates, and approval-based access control.

Key features:
- Deterministic UUID from email (same email = same ID)
- Approval workflow for access control
- Tags for segmentation
- Origin tracking for analytics
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import Field, EmailStr, model_validator

from ..core import CoreModel


class SubscriberStatus(str, Enum):
    """Subscription status."""

    ACTIVE = "active"           # Actively subscribed
    UNSUBSCRIBED = "unsubscribed"  # User unsubscribed
    BOUNCED = "bounced"         # Email bounced
    PENDING = "pending"         # Pending confirmation (if double opt-in)


class SubscriberOrigin(str, Enum):
    """Where the subscription originated from."""

    WEBSITE = "website"         # Main website subscribe form
    LANDING_PAGE = "landing_page"  # Campaign landing page
    APP = "app"                 # In-app subscription
    IMPORT = "import"           # Bulk import
    REFERRAL = "referral"       # Referred by another user
    OTHER = "other"


class Subscriber(CoreModel):
    """
    Email subscriber for newsletters and access control.

    This model captures subscribers who sign up via the website, landing pages,
    or in-app prompts. Uses deterministic UUID from email for natural upserts.

    Access control via `approved` field:
    - When email auth checks subscriber status, only approved subscribers
      can complete login (if approval is enabled in settings).
    - Subscribers can be pre-approved, or approved manually/automatically.

    Usage:
        from rem.services.postgres import Repository
        from rem.models.entities import Subscriber, SubscriberStatus

        repo = Repository(Subscriber, db=db)

        # Create subscriber (ID auto-generated from email)
        subscriber = Subscriber(
            email="user@example.com",
            name="John Doe",
            origin=SubscriberOrigin.WEBSITE,
        )
        await repo.upsert(subscriber)

        # Check if approved for login
        subscriber = await repo.get_by_id(subscriber.id, tenant_id="default")
        if subscriber and subscriber.approved:
            # Allow login
            pass
    """

    # Required field
    email: EmailStr = Field(
        description="Subscriber's email address (unique identifier)"
    )

    # Optional fields
    name: Optional[str] = Field(
        default=None,
        description="Subscriber's name (optional)"
    )

    comment: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional comment or message from subscriber"
    )

    status: SubscriberStatus = Field(
        default=SubscriberStatus.ACTIVE,
        description="Current subscription status"
    )

    # Access control
    approved: bool = Field(
        default=False,
        description="Whether subscriber is approved for login (for approval workflows)"
    )

    approved_at: Optional[datetime] = Field(
        default=None,
        description="When the subscriber was approved"
    )

    approved_by: Optional[str] = Field(
        default=None,
        description="Who approved the subscriber (user ID or 'system')"
    )

    # Origin tracking
    origin: SubscriberOrigin = Field(
        default=SubscriberOrigin.WEBSITE,
        description="Where the subscription originated"
    )

    origin_detail: Optional[str] = Field(
        default=None,
        description="Additional origin context (e.g., campaign name, page URL)"
    )

    # Timestamps
    subscribed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the subscription was created"
    )

    unsubscribed_at: Optional[datetime] = Field(
        default=None,
        description="When the user unsubscribed (if applicable)"
    )

    # Compliance
    ip_address: Optional[str] = Field(
        default=None,
        description="IP address at subscription time (for compliance)"
    )

    user_agent: Optional[str] = Field(
        default=None,
        description="Browser user agent at subscription time"
    )

    # Segmentation
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for segmentation (e.g., ['early-access', 'beta'])"
    )

    @staticmethod
    def email_to_uuid(email: str) -> uuid.UUID:
        """Generate a deterministic UUID from an email address.

        Uses UUID v5 with DNS namespace for consistency with
        EmailService.generate_user_id_from_email().

        Args:
            email: Email address

        Returns:
            Deterministic UUID
        """
        return uuid.uuid5(uuid.NAMESPACE_DNS, email.lower().strip())

    @model_validator(mode="after")
    def set_id_from_email(self) -> "Subscriber":
        """Auto-generate deterministic ID from email for natural upsert."""
        if self.email:
            self.id = self.email_to_uuid(self.email)
        return self
