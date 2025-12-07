"""
Shared FastAPI dependencies for authentication and authorization.

Provides dependency injection utilities for:
- Extracting current user from session
- Requiring authentication
- Requiring specific roles (admin, user)
- User-scoped data filtering with admin override

Design Pattern:
- Use as FastAPI dependencies via Depends()
- Middleware sets request.state.user and request.state.is_anonymous
- Dependencies extract and validate from request.state
- Admin users can access any user's data via filters

Roles:
- "admin": Full access to all data across all users
- "user": Default role, access limited to own data
- Anonymous: Rate-limited access, no persistent data

Usage:
    from rem.api.deps import require_auth, require_admin, get_user_filter

    @router.get("/items")
    async def list_items(user: dict = Depends(require_auth)):
        # user is guaranteed to be authenticated
        ...

    @router.post("/admin/action")
    async def admin_action(user: dict = Depends(require_admin)):
        # user is guaranteed to have admin role
        ...

    @router.get("/sessions/{session_id}")
    async def get_session(
        session_id: str,
        filters: dict = Depends(get_user_filter),
    ):
        # filters includes user_id constraint (unless admin)
        ...
"""

from typing import Any

from fastapi import Depends, HTTPException, Request
from loguru import logger


class AuthError(HTTPException):
    """Authentication/Authorization error."""

    def __init__(self, detail: str, status_code: int = 401):
        super().__init__(status_code=status_code, detail=detail)


def get_current_user(request: Request) -> dict | None:
    """
    Get current user from request state (set by AuthMiddleware).

    Returns None if no user authenticated.
    Use require_auth() if authentication is mandatory.

    Args:
        request: FastAPI request

    Returns:
        User dict from session or None
    """
    return getattr(request.state, "user", None)


def get_is_anonymous(request: Request) -> bool:
    """
    Check if current request is anonymous.

    Args:
        request: FastAPI request

    Returns:
        True if anonymous, False if authenticated
    """
    return getattr(request.state, "is_anonymous", True)


def require_auth(request: Request) -> dict:
    """
    Require authenticated user.

    Use as FastAPI dependency to enforce authentication.

    Args:
        request: FastAPI request

    Returns:
        User dict from session

    Raises:
        HTTPException 401 if not authenticated
    """
    user = get_current_user(request)
    if not user:
        raise AuthError("Authentication required", status_code=401)
    return user


def require_admin(request: Request) -> dict:
    """
    Require authenticated user with admin role.

    Use as FastAPI dependency to protect admin-only endpoints.

    Args:
        request: FastAPI request

    Returns:
        User dict from session

    Raises:
        HTTPException 401 if not authenticated
        HTTPException 403 if not admin
    """
    user = require_auth(request)
    roles = user.get("roles", [])

    if "admin" not in roles:
        logger.warning(f"Admin access denied for user {user.get('email')}")
        raise AuthError("Admin access required", status_code=403)

    return user


def is_admin(user: dict | None) -> bool:
    """
    Check if user has admin role.

    Args:
        user: User dict or None

    Returns:
        True if user is admin
    """
    if not user:
        return False
    return "admin" in user.get("roles", [])


async def get_user_filter(
    request: Request,
    x_user_id: str | None = None,
) -> dict[str, Any]:
    """
    Get user-scoped filter dict for database queries.

    For regular users: Always filters by their own user_id.
    For admin users: Can filter by any user_id (or no filter for all users).

    Args:
        request: FastAPI request
        x_user_id: Optional user_id filter (admin only for cross-user)

    Returns:
        Filter dict with appropriate user_id constraint

    Usage:
        @router.get("/items")
        async def list_items(filters: dict = Depends(get_user_filter)):
            return await repo.find(filters)
    """
    user = get_current_user(request)
    filters: dict[str, Any] = {}

    if is_admin(user):
        # Admin can filter by any user or see all
        if x_user_id:
            filters["user_id"] = x_user_id
        # If no user_id specified, admin sees all (no user_id filter)
        logger.debug(f"Admin access: filters={filters}")
    elif user:
        # Regular authenticated user: always filter by own user_id
        filters["user_id"] = user.get("id")
        if x_user_id and x_user_id != user.get("id"):
            logger.warning(
                f"User {user.get('email')} attempted to filter by user_id={x_user_id}"
            )
    else:
        # Anonymous: use anonymous tracking ID
        # Note: user_id should come from JWT, not from parameters
        anon_id = getattr(request.state, "anon_id", None)
        if anon_id:
            filters["user_id"] = f"anon:{anon_id}"
        else:
            filters["user_id"] = "anonymous"

    return filters


async def require_owner_or_admin(
    request: Request,
    resource_user_id: str,
) -> dict:
    """
    Require that current user owns the resource or is admin.

    Use for parametric endpoints (GET /resource/{id}) where
    only the owner or admin should access.

    Args:
        request: FastAPI request
        resource_user_id: The user_id of the resource being accessed

    Returns:
        User dict from session

    Raises:
        HTTPException 401 if not authenticated
        HTTPException 403 if not owner and not admin
    """
    user = require_auth(request)

    if is_admin(user):
        return user

    if user.get("id") != resource_user_id:
        logger.warning(
            f"Access denied: user {user.get('email')} tried to access "
            f"resource owned by {resource_user_id}"
        )
        raise AuthError("Access denied: not owner", status_code=403)

    return user


def get_user_id_from_request(request: Request) -> str:
    """
    Get effective user_id for creating resources.

    Returns authenticated user's ID or anonymous tracking ID.

    Args:
        request: FastAPI request

    Returns:
        User ID string
    """
    user = get_current_user(request)
    if user:
        return user.get("id", "unknown")

    anon_id = getattr(request.state, "anon_id", None)
    if anon_id:
        return f"anon:{anon_id}"

    return "anonymous"
