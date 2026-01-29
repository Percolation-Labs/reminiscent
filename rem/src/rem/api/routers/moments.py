"""
Moments API endpoints for session compression.

Provides endpoints for:
- POST /api/v1/moments/build - Trigger async moment building for a session
- GET /api/v1/moments/{page} - List paginated moment keys (user-scoped)
- GET /api/v1/moments/key/{key} - Get specific moment detail (user-scoped)

Moments are created by the MomentBuilder agent which:
1. Compacts user/assistant/tool messages into discrete moments
2. Models the user's journey through conversations
3. Inserts partition events as checkpoints
4. Updates user summary with evolving interests

See rem/docs/moments.md for full design documentation.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from ..deps import get_user_id_from_request
from ...models.entities import Moment
from ...services.postgres import Repository
from ...settings import settings
from ...utils.date_utils import utc_now

router = APIRouter(prefix="/api/v1/moments", tags=["moments"])


# =============================================================================
# Request/Response Models
# =============================================================================


class MomentBuildRequest(BaseModel):
    """Request to trigger moment building for a session."""

    session_id: str = Field(description="Session ID to build moments for")
    user_id: str | None = Field(
        default=None,
        description="User ID to build moments for. If not provided, uses authenticated user.",
    )
    force: bool = Field(
        default=False,
        description="Bypass threshold check and force moment building",
    )


class MomentBuildResponse(BaseModel):
    """Response from moment build trigger."""

    status: str = Field(description="Status: 'accepted' or 'skipped'")
    message: str = Field(description="Human-readable status message")
    job_id: str | None = Field(
        default=None,
        description="Job ID for tracking (if accepted)",
    )


class MomentSummary(BaseModel):
    """Lightweight moment info for list responses."""

    key: str = Field(description="Moment key/name")
    date: str = Field(description="Date (YYYY-MM-DD)")
    time_range: str | None = Field(description="Time range (HH:MM-HH:MM)")
    topics: list[str] = Field(description="Topic tags")


class MomentListResponse(BaseModel):
    """Paginated list of moments."""

    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    total_pages: int = Field(description="Total number of pages")
    total_moments: int = Field(description="Total number of moments")
    moments: list[MomentSummary] = Field(description="Moment summaries")


class MomentDetailResponse(BaseModel):
    """Full moment detail."""

    key: str = Field(description="Moment key/name")
    summary: str | None = Field(description="Natural language summary")
    topic_tags: list[str] = Field(description="Topic/concept tags")
    emotion_tags: list[str] = Field(description="Emotion/sentiment tags")
    starts_timestamp: str | None = Field(description="Start time (ISO 8601)")
    ends_timestamp: str | None = Field(description="End time (ISO 8601)")
    source_session_id: str | None = Field(description="Source session ID")
    previous_moment_keys: list[str] = Field(
        description="Keys for backwards chaining"
    )
    category: str | None = Field(description="Moment category")


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/build",
    response_model=MomentBuildResponse,
    status_code=202,
    responses={
        202: {"description": "Moment building accepted and queued"},
        400: {"description": "Invalid request"},
        503: {"description": "Moment builder not enabled or database unavailable"},
    },
)
async def build_moments(
    request: Request,
    body: MomentBuildRequest,
) -> MomentBuildResponse:
    """
    Trigger async moment building for a session.

    This endpoint accepts the request immediately and queues the moment
    building process to run asynchronously. Use this after streaming
    responses when thresholds are crossed.

    The moment builder will:
    1. Load unprocessed messages since last partition event
    2. Create discrete moments summarizing conversation segments
    3. Insert a partition event as a checkpoint
    4. Update user summary with evolving interests

    Args:
        body: Session ID and optional force flag

    Returns:
        Accepted status with job ID for tracking
    """
    if not settings.moment_builder.enabled:
        raise HTTPException(
            status_code=503,
            detail="Moment builder is not enabled. Set MOMENT_BUILDER__ENABLED=true",
        )

    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    # Use explicit user_id from body if provided, otherwise fall back to request user
    user_id = body.user_id or get_user_id_from_request(request)

    # Generate job ID for tracking
    import uuid
    job_id = str(uuid.uuid4())

    logger.info(
        f"Moment build requested: session={body.session_id}, "
        f"user={user_id}, force={body.force}, job_id={job_id}"
    )

    # Fire and forget - queue the moment building task
    asyncio.create_task(
        _run_moment_builder(
            session_id=body.session_id,
            user_id=user_id,
            force=body.force,
            job_id=job_id,
        )
    )

    return MomentBuildResponse(
        status="accepted",
        message="Moment building queued",
        job_id=job_id,
    )


@router.get(
    "/{page}",
    response_model=MomentListResponse,
    responses={
        503: {"description": "Database not enabled"},
    },
)
async def list_moments(
    request: Request,
    page: int = 1,
) -> MomentListResponse:
    """
    List paginated moment keys for the current user.

    Returns lightweight moment entries (key, date, topics) for navigation.
    Use GET /api/v1/moments/key/{key} to retrieve full moment details.

    Moments are sorted by start timestamp descending (most recent first).
    Page size is configured via MOMENT_BUILDER__PAGE_SIZE (default: 25).

    Args:
        page: Page number (1-indexed, default: 1)

    Returns:
        Paginated list of moment summaries
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    user_id = get_user_id_from_request(request)
    page_size = settings.moment_builder.page_size

    # Ensure page is at least 1
    if page < 1:
        page = 1

    offset = (page - 1) * page_size

    # Query moments for this user, ordered by starts_timestamp DESC
    from ...services.postgres import PostgresService

    db = PostgresService()
    if not db.pool:
        await db.connect()

    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection failed")

    # Get total count
    count_query = """
        SELECT COUNT(*) FROM moments
        WHERE user_id = $1 AND deleted_at IS NULL
    """

    # Get paginated moments
    list_query = """
        SELECT name, starts_timestamp, ends_timestamp, topic_tags
        FROM moments
        WHERE user_id = $1 AND deleted_at IS NULL
        ORDER BY starts_timestamp DESC
        LIMIT $2 OFFSET $3
    """

    async with db.pool.acquire() as conn:
        total_count = await conn.fetchval(count_query, user_id)
        rows = await conn.fetch(list_query, user_id, page_size, offset)

    total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

    moments = []
    for row in rows:
        starts = row["starts_timestamp"]
        ends = row["ends_timestamp"]

        date_str = starts.strftime("%Y-%m-%d") if starts else ""
        time_range = None
        if starts and ends:
            time_range = f"{starts.strftime('%H:%M')}-{ends.strftime('%H:%M')}"
        elif starts:
            time_range = starts.strftime("%H:%M")

        moments.append(
            MomentSummary(
                key=row["name"] or "",
                date=date_str,
                time_range=time_range,
                topics=row["topic_tags"] or [],
            )
        )

    return MomentListResponse(
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        total_moments=total_count or 0,
        moments=moments,
    )


@router.get(
    "/key/{key:path}",
    response_model=MomentDetailResponse,
    responses={
        404: {"description": "Moment not found"},
        503: {"description": "Database not enabled"},
    },
)
async def get_moment(
    request: Request,
    key: str,
) -> MomentDetailResponse:
    """
    Get full details of a specific moment by key.

    The moment must belong to the current user (user-scoped access).
    Returns 404 if moment doesn't exist or belongs to a different user.

    Args:
        key: Moment key/name

    Returns:
        Full moment details including summary, tags, and timestamps
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    user_id = get_user_id_from_request(request)

    # Query moment by name AND user_id for security
    from ...services.postgres import PostgresService

    db = PostgresService()
    if not db.pool:
        await db.connect()

    if not db.pool:
        raise HTTPException(status_code=503, detail="Database connection failed")

    query = """
        SELECT name, summary, topic_tags, emotion_tags,
               starts_timestamp, ends_timestamp, source_session_id,
               previous_moment_keys, category
        FROM moments
        WHERE name = $1 AND user_id = $2 AND deleted_at IS NULL
        LIMIT 1
    """

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(query, key, user_id)

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Moment '{key}' not found",
        )

    return MomentDetailResponse(
        key=row["name"] or key,
        summary=row["summary"],
        topic_tags=row["topic_tags"] or [],
        emotion_tags=row["emotion_tags"] or [],
        starts_timestamp=row["starts_timestamp"].isoformat() if row["starts_timestamp"] else None,
        ends_timestamp=row["ends_timestamp"].isoformat() if row["ends_timestamp"] else None,
        source_session_id=row["source_session_id"],
        previous_moment_keys=row["previous_moment_keys"] or [],
        category=row["category"],
    )


# =============================================================================
# Background Task
# =============================================================================


async def _run_moment_builder(
    session_id: str,
    user_id: str,
    force: bool,
    job_id: str,
) -> None:
    """
    Run moment builder in background.

    This is called via asyncio.create_task() from the endpoint.
    Errors are logged but don't affect the caller.
    """
    try:
        logger.info(f"Starting moment builder: job_id={job_id}, session={session_id}")

        from ...agentic.agents import run_moment_builder

        result = await run_moment_builder(
            session_id=session_id,
            user_id=user_id,
            force=force,
        )

        if result.success:
            logger.info(
                f"Moment builder completed: job_id={job_id}, "
                f"moments_created={result.moments_created}, "
                f"partition_inserted={result.partition_event_inserted}"
            )
        else:
            logger.error(
                f"Moment builder failed: job_id={job_id}, error={result.error}"
            )

    except Exception as e:
        logger.error(f"Moment builder failed: job_id={job_id}, error={e}")
