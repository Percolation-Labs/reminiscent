"""
Filesystem path naming conventions for REM.

Standardized path structure:
- rem/v1/uploads/{system|user_id}/{yyyy}/{mm}/{dd}/{optional_hh_mm}/
- Local: $REM_HOME/fs/...
- S3: s3://{bucket}/...

Design principles:
- Consistent hierarchical structure
- Date-based partitioning for scalability
- User vs system separation
- Environment-aware (local vs cloud)
"""

import os
from datetime import datetime, date
from pathlib import Path
from typing import Literal

from rem.settings import settings


def get_rem_home() -> str:
    """
    Get REM_HOME directory for local filesystem.

    Returns REM_HOME environment variable or defaults to ~/.rem

    Returns:
        Absolute path to REM home directory
    """
    rem_home = os.getenv("REM_HOME", str(Path.home() / ".rem"))
    return str(Path(rem_home).expanduser().absolute())


def get_base_uri(use_s3: bool | None = None) -> str:
    """
    Get base URI for file storage.

    Args:
        use_s3: Force S3 (True) or local (False). If None, uses S3 in production.

    Returns:
        Base URI: s3://{bucket} or $REM_HOME/fs
    """
    if use_s3 is None:
        # Auto-detect: use S3 in production, local in development
        use_s3 = settings.environment == "production"

    if use_s3:
        bucket = settings.s3.bucket_name
        return f"s3://{bucket}"
    else:
        rem_home = get_rem_home()
        return str(Path(rem_home) / "fs")


def get_uploads_path(
    user_id: str | None = None,
    dt: datetime | date | None = None,
    include_time: bool = False,
    use_s3: bool | None = None,
) -> str:
    """
    Get standardized uploads directory path for a given date.

    Path structure:
        rem/v1/uploads/{system|user_id}/{yyyy}/{mm}/{dd}/{hh_mm}/

    Args:
        user_id: User ID for user-specific uploads. If None, uses "system"
        dt: Date/datetime for path. If None, uses current time
        include_time: Include hour/minute in path (default: False)
        use_s3: Force S3 or local. If None, auto-detects based on environment

    Returns:
        Full path: base_uri/rem/v1/uploads/{system|user_id}/yyyy/mm/dd[/hh_mm]

    Examples:
        >>> get_uploads_path()
        '/Users/user/.rem/fs/rem/v1/uploads/system/2025/01/19'

        >>> get_uploads_path(user_id="user-123", include_time=True)
        '/Users/user/.rem/fs/rem/v1/uploads/user-123/2025/01/19/14_30'

        >>> get_uploads_path(use_s3=True)
        's3://rem-bucket/rem/v1/uploads/system/2025/01/19'
    """
    # Get base URI
    base_uri = get_base_uri(use_s3=use_s3)

    # Use current time if not provided
    if dt is None:
        dt = datetime.now()

    # Convert date to datetime for consistent handling
    if isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())

    # Build path components
    scope = user_id if user_id else "system"
    year = dt.strftime("%Y")
    month = dt.strftime("%m")
    day = dt.strftime("%d")

    # Base path
    parts = [base_uri, "rem", "v1", "uploads", scope, year, month, day]

    # Add time if requested
    if include_time:
        hour_min = dt.strftime("%H_%M")
        parts.append(hour_min)

    # Join path (handles both S3 and local)
    if base_uri.startswith("s3://"):
        return "/".join(parts)
    else:
        return str(Path(*parts))


def get_versioned_path(
    resource_type: Literal["schemas", "agents", "tools", "datasets"],
    name: str,
    version: str = "v1",
    use_s3: bool | None = None,
) -> str:
    """
    Get path for versioned resources.

    Path structure:
        rem/{version}/{resource_type}/{name}/

    Args:
        resource_type: Type of resource (schemas, agents, tools, datasets)
        name: Resource name
        version: Version string (default: v1)
        use_s3: Force S3 or local. If None, auto-detects

    Returns:
        Full path: base_uri/rem/{version}/{resource_type}/{name}

    Examples:
        >>> get_versioned_path("schemas", "user-schema")
        '/Users/user/.rem/fs/rem/v1/schemas/user-schema'

        >>> get_versioned_path("agents", "query-agent", version="v2")
        '/Users/user/.rem/fs/rem/v2/agents/query-agent'
    """
    base_uri = get_base_uri(use_s3=use_s3)
    parts = [base_uri, "rem", version, resource_type, name]

    if base_uri.startswith("s3://"):
        return "/".join(parts)
    else:
        return str(Path(*parts))


def get_user_path(
    user_id: str,
    subpath: str | None = None,
    use_s3: bool | None = None,
) -> str:
    """
    Get user-scoped storage path.

    Path structure:
        rem/v1/users/{user_id}/{subpath}/

    Args:
        user_id: User ID
        subpath: Optional subpath (e.g., "documents", "images")
        use_s3: Force S3 or local. If None, auto-detects

    Returns:
        Full path: base_uri/rem/v1/users/{user_id}[/{subpath}]

    Examples:
        >>> get_user_path("user-123")
        '/Users/user/.rem/fs/rem/v1/users/user-123'

        >>> get_user_path("user-123", "documents")
        '/Users/user/.rem/fs/rem/v1/users/user-123/documents'
    """
    base_uri = get_base_uri(use_s3=use_s3)
    parts = [base_uri, "rem", "v1", "users", user_id]

    if subpath:
        parts.append(subpath)

    if base_uri.startswith("s3://"):
        return "/".join(parts)
    else:
        return str(Path(*parts))


def get_temp_path(
    prefix: str = "tmp",
    use_s3: bool | None = None,
) -> str:
    """
    Get temporary file storage path.

    Path structure:
        rem/v1/temp/{prefix}/{timestamp}/

    Args:
        prefix: Prefix for temp directory (default: "tmp")
        use_s3: Force S3 or local. If None, auto-detects

    Returns:
        Full path: base_uri/rem/v1/temp/{prefix}/{timestamp}

    Examples:
        >>> get_temp_path()
        '/Users/user/.rem/fs/rem/v1/temp/tmp/20250119_143045'

        >>> get_temp_path("processing")
        '/Users/user/.rem/fs/rem/v1/temp/processing/20250119_143045'
    """
    base_uri = get_base_uri(use_s3=use_s3)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [base_uri, "rem", "v1", "temp", prefix, timestamp]

    if base_uri.startswith("s3://"):
        return "/".join(parts)
    else:
        return str(Path(*parts))


def ensure_dir_exists(path: str) -> str:
    """
    Ensure directory exists for local paths (no-op for S3).

    Args:
        path: Directory path

    Returns:
        The same path (for chaining)
    """
    if not path.startswith("s3://"):
        Path(path).mkdir(parents=True, exist_ok=True)
    return path


def join_path(*parts: str, is_s3: bool | None = None) -> str:
    """
    Join path parts, handling S3 vs local paths correctly.

    Args:
        *parts: Path components to join
        is_s3: Force S3 (/) or local (os-specific). Auto-detects if None.

    Returns:
        Joined path

    Examples:
        >>> join_path("s3://bucket", "rem", "v1", "uploads")
        's3://bucket/rem/v1/uploads'

        >>> join_path("/home/user", "rem", "data")
        '/home/user/rem/data'
    """
    if not parts:
        return ""

    # Auto-detect S3 from first part
    if is_s3 is None:
        is_s3 = parts[0].startswith("s3://")

    if is_s3:
        # S3: always use forward slash
        return "/".join(str(p) for p in parts)
    else:
        # Local: use Path for OS-specific separators
        return str(Path(*[str(p) for p in parts]))
