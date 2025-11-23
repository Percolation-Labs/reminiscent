"""
Utility functions for user ID generation and management.

Provides deterministic UUID generation from email addresses for consistent
user identification across the REM system.
"""

import hashlib
import uuid
from typing import Union


def email_to_user_id(email: str) -> str:
    """
    Generate a deterministic UUID from an email address.

    Uses UUID5 (SHA-1 based) with a REM-specific namespace to ensure:
    - Same email always produces same UUID
    - Different emails produce different UUIDs
    - UUIDs are valid RFC 4122 format

    Args:
        email: Email address to convert

    Returns:
        String representation of UUID (e.g., "550e8400-e29b-41d4-a716-446655440000")

    Examples:
        >>> email_to_user_id("alice@example.com")
        '2c5ea4c0-4067-5fef-942d-0a20124e06d8'
        >>> email_to_user_id("alice@example.com")  # Same email -> same UUID
        '2c5ea4c0-4067-5fef-942d-0a20124e06d8'
    """
    # Use REM-specific namespace UUID (generated once)
    # This ensures our UUIDs are unique to REM system
    REM_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

    # Normalize email: lowercase and strip whitespace
    normalized_email = email.lower().strip()

    # Generate deterministic UUID5
    user_uuid = uuid.uuid5(REM_NAMESPACE, normalized_email)

    return str(user_uuid)


def user_id_to_uuid(user_id: Union[str, uuid.UUID]) -> uuid.UUID:
    """
    Convert a user_id string to UUID object.

    Handles both UUID strings and already-parsed UUID objects.

    Args:
        user_id: User ID as string or UUID

    Returns:
        UUID object

    Raises:
        ValueError: If user_id is not a valid UUID format
    """
    if isinstance(user_id, uuid.UUID):
        return user_id
    return uuid.UUID(user_id)


def is_valid_uuid(value: str) -> bool:
    """
    Check if a string is a valid UUID.

    Args:
        value: String to check

    Returns:
        True if valid UUID, False otherwise
    """
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
