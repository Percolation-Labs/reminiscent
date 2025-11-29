"""
Centralized datetime utilities for consistent UTC-naive datetime handling.

IMPORTANT: REM uses UTC-naive datetimes throughout the codebase.
PostgreSQL stores TIMESTAMP WITHOUT TIME ZONE, so all Python datetime
operations should use UTC-naive datetimes to avoid comparison errors.

Convention:
- All timestamps are implicitly UTC
- Use utc_now() instead of datetime.utcnow() or datetime.now(timezone.utc)
- Use parse_iso() to parse ISO format strings (handles "Z" suffix)
- Use to_iso() to format datetimes as ISO strings

See CLAUDE.md Section 1 (Datetime Convention) for details.
"""

from datetime import UTC, datetime, timedelta
from typing import Optional


def utc_now() -> datetime:
    """
    Get current UTC time as a naive datetime.

    Returns:
        UTC-naive datetime representing current time.

    Example:
        >>> now = utc_now()
        >>> now.tzinfo is None
        True
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_iso(dt: datetime) -> str:
    """
    Convert datetime to ISO 8601 format string.

    Args:
        dt: Datetime to format (should be UTC-naive)

    Returns:
        ISO format string (e.g., "2024-01-15T10:30:00")

    Example:
        >>> dt = datetime(2024, 1, 15, 10, 30, 0)
        >>> to_iso(dt)
        '2024-01-15T10:30:00'
    """
    return dt.isoformat()


def to_iso_with_z(dt: datetime) -> str:
    """
    Convert datetime to ISO 8601 format with Z suffix.

    Use this when interfacing with external APIs that expect
    the Z suffix to indicate UTC.

    Args:
        dt: Datetime to format (should be UTC-naive)

    Returns:
        ISO format string with Z suffix (e.g., "2024-01-15T10:30:00Z")
    """
    return dt.isoformat() + "Z"


def parse_iso(iso_string: str) -> datetime:
    """
    Parse ISO 8601 format string to UTC-naive datetime.

    Handles:
    - Standard ISO format: "2024-01-15T10:30:00"
    - Z suffix: "2024-01-15T10:30:00Z"
    - Timezone offset: "2024-01-15T10:30:00+00:00" (converts to naive)
    - Microseconds: "2024-01-15T10:30:00.123456"

    Args:
        iso_string: ISO format datetime string

    Returns:
        UTC-naive datetime

    Raises:
        ValueError: If string cannot be parsed

    Example:
        >>> parse_iso("2024-01-15T10:30:00Z")
        datetime.datetime(2024, 1, 15, 10, 30)
        >>> parse_iso("2024-01-15T10:30:00+00:00")
        datetime.datetime(2024, 1, 15, 10, 30)
    """
    # Handle Z suffix (replace with +00:00 for fromisoformat)
    if iso_string.endswith("Z"):
        iso_string = iso_string[:-1] + "+00:00"

    # Parse the ISO string
    dt = datetime.fromisoformat(iso_string)

    # Convert to naive UTC if timezone-aware
    if dt.tzinfo is not None:
        # Convert to UTC and strip timezone
        from datetime import timezone
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt


def parse_iso_safe(iso_string: Optional[str], default: Optional[datetime] = None) -> Optional[datetime]:
    """
    Safely parse ISO string, returning default on failure.

    Args:
        iso_string: ISO format string or None
        default: Default value if parsing fails

    Returns:
        Parsed datetime or default value
    """
    if not iso_string:
        return default
    try:
        return parse_iso(iso_string)
    except (ValueError, TypeError):
        return default


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """
    Format datetime for display/logging.

    Args:
        dt: Datetime to format (defaults to current UTC time)

    Returns:
        Formatted string like "2024-01-15 10:30:00 UTC"
    """
    if dt is None:
        dt = utc_now()
    return dt.strftime("%Y-%m-%d %H:%M:%S") + " UTC"


def format_timestamp_compact(dt: Optional[datetime] = None) -> str:
    """
    Format datetime as compact string for filenames/IDs.

    Args:
        dt: Datetime to format (defaults to current UTC time)

    Returns:
        Formatted string like "20240115_103000"
    """
    if dt is None:
        dt = utc_now()
    return dt.strftime("%Y%m%d_%H%M%S")


def format_timestamp_for_experiment(dt: Optional[datetime] = None) -> str:
    """
    Format datetime for experiment names.

    Args:
        dt: Datetime to format (defaults to current UTC time)

    Returns:
        Formatted string like "20240115-103000"
    """
    if dt is None:
        dt = utc_now()
    return dt.strftime("%Y%m%d-%H%M%S")


def days_ago(days: int) -> datetime:
    """
    Get datetime N days ago from now.

    Args:
        days: Number of days ago

    Returns:
        UTC-naive datetime
    """
    return utc_now() - timedelta(days=days)


def hours_ago(hours: int) -> datetime:
    """
    Get datetime N hours ago from now.

    Args:
        hours: Number of hours ago

    Returns:
        UTC-naive datetime
    """
    return utc_now() - timedelta(hours=hours)


def is_within_hours(dt: datetime, hours: int) -> bool:
    """
    Check if datetime is within N hours of now.

    Args:
        dt: Datetime to check (should be UTC-naive)
        hours: Number of hours

    Returns:
        True if dt is within the time window
    """
    cutoff = hours_ago(hours)
    return dt >= cutoff


def is_within_days(dt: datetime, days: int) -> bool:
    """
    Check if datetime is within N days of now.

    Args:
        dt: Datetime to check (should be UTC-naive)
        days: Number of days

    Returns:
        True if dt is within the time window
    """
    cutoff = days_ago(days)
    return dt >= cutoff
