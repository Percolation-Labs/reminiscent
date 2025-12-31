"""
Admin API Router.

Protected endpoints requiring admin role for system management tasks.

Endpoints:
    GET  /api/admin/users          - List all users (admin only)
    GET  /api/admin/sessions       - List all sessions across users (admin only)
    GET  /api/admin/messages       - List all messages across users (admin only)
    GET  /api/admin/stats          - System statistics (admin only)

Internal Endpoints (hidden from Swagger, secret-protected):
    POST /api/admin/internal/rebuild-kv  - Trigger kv_store rebuild (called by pg_net)

All endpoints require:
1. Authentication (valid session)
2. Admin role in user's roles list

Design Pattern:
- Uses require_admin dependency for role enforcement
- Cross-tenant queries (no user_id filtering)
- Audit logging for admin actions
- Internal endpoints use X-Internal-Secret header for authentication
"""

import asyncio
import threading
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, BackgroundTasks
from loguru import logger
from pydantic import BaseModel

from .common import ErrorResponse

from ..deps import require_admin
from ...models.entities import Message, Session, SessionMode
from ...services.postgres import Repository
from ...settings import settings

router = APIRouter(prefix="/api/admin", tags=["admin"])

# =============================================================================
# Internal Router (hidden from Swagger)
# =============================================================================

internal_router = APIRouter(prefix="/internal", include_in_schema=False)


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


@router.get(
    "/users",
    response_model=UserListResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
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


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
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


@router.get(
    "/messages",
    response_model=MessageListResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
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


@router.get(
    "/stats",
    response_model=SystemStats,
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
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


# =============================================================================
# Internal Endpoints (hidden from Swagger, secret-protected)
# =============================================================================


class RebuildKVRequest(BaseModel):
    """Request body for kv_store rebuild trigger."""

    user_id: str | None = None
    triggered_by: str = "api"
    timestamp: str | None = None


class RebuildKVResponse(BaseModel):
    """Response from kv_store rebuild trigger."""

    status: Literal["submitted", "started", "skipped"]
    message: str
    job_method: str | None = None  # "sqs" or "thread"


async def _get_internal_secret() -> str | None:
    """
    Get the internal API secret from cache_system_state table.

    Returns None if the table doesn't exist or secret not found.
    """
    from ...services.postgres import get_postgres_service

    db = get_postgres_service()
    if not db:
        return None

    try:
        await db.connect()
        secret = await db.fetchval("SELECT rem_get_cache_api_secret()")
        return secret
    except Exception as e:
        logger.warning(f"Could not get internal API secret: {e}")
        return None
    finally:
        await db.disconnect()


async def _validate_internal_secret(x_internal_secret: str | None = Header(None)):
    """
    Dependency to validate the X-Internal-Secret header.

    Raises 401 if secret is missing or invalid.
    """
    if not x_internal_secret:
        logger.warning("Internal endpoint called without X-Internal-Secret header")
        raise HTTPException(status_code=401, detail="Missing X-Internal-Secret header")

    expected_secret = await _get_internal_secret()
    if not expected_secret:
        logger.error("Could not retrieve internal secret from database")
        raise HTTPException(status_code=503, detail="Internal secret not configured")

    if x_internal_secret != expected_secret:
        logger.warning("Internal endpoint called with invalid secret")
        raise HTTPException(status_code=401, detail="Invalid X-Internal-Secret")

    return True


def _run_rebuild_in_thread():
    """
    Run the kv_store rebuild in a background thread.

    This is the fallback when SQS is not available.
    """

    def rebuild_task():
        """Thread target function."""
        import asyncio
        from ...workers.unlogged_maintainer import UnloggedMaintainer

        async def _run():
            maintainer = UnloggedMaintainer()
            if not maintainer.db:
                logger.error("Database not configured, cannot rebuild")
                return
            try:
                await maintainer.db.connect()
                await maintainer.rebuild_with_lock()
            except Exception as e:
                logger.error(f"Background rebuild failed: {e}")
            finally:
                await maintainer.db.disconnect()

        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    thread = threading.Thread(target=rebuild_task, name="kv-rebuild-worker")
    thread.daemon = True
    thread.start()
    logger.info(f"Started background rebuild thread: {thread.name}")


def _submit_sqs_rebuild_job_sync(request: RebuildKVRequest) -> bool:
    """
    Submit rebuild job to SQS queue (synchronous).

    Returns True if job was submitted, False if SQS unavailable.
    """
    import json

    import boto3
    from botocore.exceptions import ClientError

    if not settings.sqs.queue_url:
        logger.debug("SQS queue URL not configured, cannot submit SQS job")
        return False

    try:
        sqs = boto3.client("sqs", region_name=settings.sqs.region)

        message_body = {
            "action": "rebuild_kv_store",
            "user_id": request.user_id,
            "triggered_by": request.triggered_by,
            "timestamp": request.timestamp,
        }

        response = sqs.send_message(
            QueueUrl=settings.sqs.queue_url,
            MessageBody=json.dumps(message_body),
            MessageAttributes={
                "action": {"DataType": "String", "StringValue": "rebuild_kv_store"},
            },
        )

        message_id = response.get("MessageId")
        logger.info(f"Submitted rebuild job to SQS: {message_id}")
        return True

    except ClientError as e:
        logger.warning(f"Failed to submit SQS job: {e}")
        return False
    except Exception as e:
        logger.warning(f"SQS submission error: {e}")
        return False


async def _submit_sqs_rebuild_job(request: RebuildKVRequest) -> bool:
    """
    Submit rebuild job to SQS queue (async wrapper).

    Runs boto3 call in thread pool to avoid blocking event loop.
    """
    import asyncio

    return await asyncio.to_thread(_submit_sqs_rebuild_job_sync, request)


@internal_router.post("/rebuild-kv", response_model=RebuildKVResponse)
async def trigger_kv_rebuild(
    request: RebuildKVRequest,
    _: bool = Depends(_validate_internal_secret),
) -> RebuildKVResponse:
    """
    Trigger kv_store rebuild (internal endpoint, not shown in Swagger).

    Called by pg_net from PostgreSQL when self-healing detects empty cache.
    Authentication: X-Internal-Secret header must match secret in cache_system_state.

    Priority:
    1. Submit job to SQS (if configured) - scales with KEDA
    2. Fallback to background thread - runs in same process

    Note: This endpoint returns immediately. Rebuild happens asynchronously.
    """
    logger.info(
        f"Rebuild kv_store requested by {request.triggered_by} "
        f"(user_id={request.user_id})"
    )

    # Try SQS first
    if await _submit_sqs_rebuild_job(request):
        return RebuildKVResponse(
            status="submitted",
            message="Rebuild job submitted to SQS queue",
            job_method="sqs",
        )

    # Fallback to background thread
    _run_rebuild_in_thread()

    return RebuildKVResponse(
        status="started",
        message="Rebuild started in background thread (SQS unavailable)",
        job_method="thread",
    )


# Include internal router in main router
router.include_router(internal_router)
