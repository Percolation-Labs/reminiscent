"""
Admin API Router.

Protected endpoints requiring admin role for system management tasks.

Endpoints:
    GET  /api/admin/users          - List all users (admin only)
    GET  /api/admin/sessions       - List all sessions across users (admin only)
    GET  /api/admin/messages       - List all messages across users (admin only)
    GET  /api/admin/stats          - System statistics (admin only)

All endpoints require:
1. Authentication (valid session)
2. Admin role in user's roles list

Design Pattern:
- Uses require_admin dependency for role enforcement
- Cross-tenant queries (no user_id filtering)
- Audit logging for admin actions
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from ..deps import require_admin
from ...models.entities import Message, Session, SessionMode
from ...services.postgres import Repository
from ...settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])


# =============================================================================
# Response Models
# =============================================================================


class UserSummary(BaseModel):
    """User summary for admin listing."""

    id: str
    email: str | None
    name: str | None
    tier: str
    role: str | None
    created_at: str | None


class UserListResponse(BaseModel):
    """Response for user list endpoint."""

    object: Literal["list"] = "list"
    data: list[UserSummary]
    total: int
    has_more: bool


class SessionListResponse(BaseModel):
    """Response for session list endpoint."""

    object: Literal["list"] = "list"
    data: list[Session]
    total: int
    has_more: bool


class MessageListResponse(BaseModel):
    """Response for message list endpoint."""

    object: Literal["list"] = "list"
    data: list[Message]
    total: int
    has_more: bool


class SystemStats(BaseModel):
    """System statistics for admin dashboard."""

    total_users: int
    total_sessions: int
    total_messages: int
    active_sessions_24h: int
    messages_24h: int


# =============================================================================
# Admin Endpoints
# =============================================================================


@router.get("/users", response_model=UserListResponse)
async def list_all_users(
    user: dict = Depends(require_admin),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> UserListResponse:
    """
    List all users in the system.

    Admin-only endpoint for user management.
    Returns users across all tenants.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    logger.info(f"Admin {user.get('email')} listing all users")

    # Import User model dynamically to avoid circular imports
    from ...models.entities import User

    repo = Repository(User, table_name="users")

    # No tenant filter - admin sees all
    users = await repo.find(
        filters={},
        order_by="created_at DESC",
        limit=limit + 1,
        offset=offset,
    )

    has_more = len(users) > limit
    if has_more:
        users = users[:limit]

    total = await repo.count({})

    # Convert to summary format
    summaries = [
        UserSummary(
            id=str(u.id),
            email=u.email,
            name=u.name,
            tier=u.tier.value if u.tier else "free",
            role=u.role,
            created_at=u.created_at.isoformat() if u.created_at else None,
        )
        for u in users
    ]

    return UserListResponse(data=summaries, total=total, has_more=has_more)


@router.get("/sessions", response_model=SessionListResponse)
async def list_all_sessions(
    user: dict = Depends(require_admin),
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    mode: SessionMode | None = Query(default=None, description="Filter by mode"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> SessionListResponse:
    """
    List all sessions across all users.

    Admin-only endpoint for session monitoring.
    Can optionally filter by user_id or mode.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    logger.info(
        f"Admin {user.get('email')} listing sessions "
        f"(user_id={user_id}, mode={mode})"
    )

    repo = Repository(Session, table_name="sessions")

    # Build optional filters
    filters: dict = {}
    if user_id:
        filters["user_id"] = user_id
    if mode:
        filters["mode"] = mode.value

    sessions = await repo.find(
        filters=filters,
        order_by="created_at DESC",
        limit=limit + 1,
        offset=offset,
    )

    has_more = len(sessions) > limit
    if has_more:
        sessions = sessions[:limit]

    total = await repo.count(filters)

    return SessionListResponse(data=sessions, total=total, has_more=has_more)


@router.get("/messages", response_model=MessageListResponse)
async def list_all_messages(
    user: dict = Depends(require_admin),
    user_id: str | None = Query(default=None, description="Filter by user ID"),
    session_id: str | None = Query(default=None, description="Filter by session ID"),
    message_type: str | None = Query(default=None, description="Filter by type"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    """
    List all messages across all users.

    Admin-only endpoint for message auditing.
    Can filter by user_id, session_id, or message_type.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    logger.info(
        f"Admin {user.get('email')} listing messages "
        f"(user_id={user_id}, session_id={session_id})"
    )

    repo = Repository(Message, table_name="messages")

    # Build optional filters
    filters: dict = {}
    if user_id:
        filters["user_id"] = user_id
    if session_id:
        filters["session_id"] = session_id
    if message_type:
        filters["message_type"] = message_type

    messages = await repo.find(
        filters=filters,
        order_by="created_at DESC",
        limit=limit + 1,
        offset=offset,
    )

    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    total = await repo.count(filters)

    return MessageListResponse(data=messages, total=total, has_more=has_more)


@router.get("/stats", response_model=SystemStats)
async def get_system_stats(
    user: dict = Depends(require_admin),
) -> SystemStats:
    """
    Get system-wide statistics.

    Admin-only endpoint for monitoring dashboard.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    logger.info(f"Admin {user.get('email')} fetching system stats")

    from ...models.entities import User
    from ...utils.date_utils import days_ago

    user_repo = Repository(User, table_name="users")
    session_repo = Repository(Session, table_name="sessions")
    message_repo = Repository(Message, table_name="messages")

    # Get totals
    total_users = await user_repo.count({})
    total_sessions = await session_repo.count({})
    total_messages = await message_repo.count({})

    # For 24h stats, we'd need date filtering in Repository
    # For now, return totals (TODO: add date range support)
    return SystemStats(
        total_users=total_users,
        total_sessions=total_sessions,
        total_messages=total_messages,
        active_sessions_24h=0,  # TODO: implement
        messages_24h=0,  # TODO: implement
    )
