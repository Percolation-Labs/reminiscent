"""
Messages and Sessions endpoints.

Provides endpoints for:
- Listing and filtering messages by date, user_id, session_id
- Creating and managing sessions (normal or evaluation mode)

Endpoints:
    GET  /api/v1/messages           - List messages with filters
    GET  /api/v1/messages/{id}      - Get a specific message

    GET  /api/v1/sessions           - List sessions
    POST /api/v1/sessions           - Create a session
    GET  /api/v1/sessions/{id}      - Get a specific session
    PUT  /api/v1/sessions/{id}      - Update a session
"""

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from .common import ErrorResponse

from ..deps import (
    get_current_user,
    get_user_filter,
    is_admin,
    require_admin,
    require_auth,
)
from ...models.entities import Message, Session, SessionMode
from ...services.postgres import Repository, get_postgres_service
from ...settings import settings
from ...utils.date_utils import parse_iso, utc_now

router = APIRouter(prefix="/api/v1")


# =============================================================================
# Enums
# =============================================================================


class SortOrder(str, Enum):
    """Sort order for list queries."""

    ASC = "asc"
    DESC = "desc"


# =============================================================================
# Request/Response Models
# =============================================================================


class MessageListResponse(BaseModel):
    """Response for message list endpoint."""

    object: Literal["list"] = "list"
    data: list[Message]
    total: int
    has_more: bool


class SessionCreateRequest(BaseModel):
    """Request to create a new session."""

    name: str = Field(description="Session name/identifier")
    mode: SessionMode = Field(
        default=SessionMode.NORMAL, description="Session mode: 'normal' or 'evaluation'"
    )
    description: str | None = Field(default=None, description="Session description")
    original_trace_id: str | None = Field(
        default=None,
        description="For evaluation: ID of the original session being evaluated",
    )
    settings_overrides: dict | None = Field(
        default=None,
        description="Settings overrides (model, temperature, max_tokens, system_prompt)",
    )
    prompt: str | None = Field(default=None, description="Custom prompt for this session")
    agent_schema_uri: str | None = Field(
        default=None, description="Agent schema URI for this session"
    )


class SessionUpdateRequest(BaseModel):
    """Request to update a session."""

    description: str | None = None
    settings_overrides: dict | None = None
    prompt: str | None = None
    message_count: int | None = None
    total_tokens: int | None = None


class SessionListResponse(BaseModel):
    """Response for session list endpoint (deprecated, use SessionsQueryResponse)."""

    object: Literal["list"] = "list"
    data: list[Session]
    total: int
    has_more: bool


class SessionWithUser(BaseModel):
    """Session with user info for admin views."""

    id: str
    name: str
    mode: str | None = None
    description: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    message_count: int = 0
    total_tokens: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict | None = None


class PaginationMetadata(BaseModel):
    """Pagination metadata for paginated responses."""

    total: int = Field(description="Total number of records matching filters")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of records per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there are more pages after this one")
    has_previous: bool = Field(description="Whether there are pages before this one")


class SessionsQueryResponse(BaseModel):
    """Response for paginated sessions query."""

    object: Literal["list"] = "list"
    data: list[SessionWithUser] = Field(description="List of sessions for the current page")
    metadata: PaginationMetadata = Field(description="Pagination metadata")


# =============================================================================
# Messages Endpoints
# =============================================================================


@router.get(
    "/messages",
    response_model=MessageListResponse,
    tags=["messages"],
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def list_messages(
    request: Request,
    mine: bool = Query(default=False, description="Only show my messages (uses JWT identity)"),
    user_id: str | None = Query(default=None, description="Filter by user ID (admin only for cross-user)"),
    session_id: str | None = Query(default=None, description="Filter by session ID"),
    start_date: str | None = Query(
        default=None, description="Filter messages after this ISO date"
    ),
    end_date: str | None = Query(
        default=None, description="Filter messages before this ISO date"
    ),
    message_type: str | None = Query(
        default=None, description="Filter by message type (user, assistant, system, tool)"
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    sort: SortOrder = Query(default=SortOrder.DESC, description="Sort order by created_at (asc or desc)"),
) -> MessageListResponse:
    """
    List messages with optional filters.

    Access Control:
    - Regular users: Only see their own messages
    - Admin users: Can filter by any user_id or see all messages
    - mine=true: Forces filter to current user (useful for admins to see only their own)

    Filters can be combined:
    - mine: Only show messages owned by current JWT user (overrides user_id)
    - user_id: Filter by the user who created/owns the message (admin only for cross-user)
    - session_id: Filter by conversation session
    - start_date/end_date: Filter by creation time range (ISO 8601 format)
    - message_type: Filter by role (user, assistant, system, tool)
    - sort: Sort order by created_at (asc or desc, default: desc)

    Returns paginated results ordered by created_at.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Message, table_name="messages")

    # Get current user for logging
    current_user = get_current_user(request)
    jwt_user_id = current_user.get("id") if current_user else None

    # If mine=true, force filter to current user's ID from JWT
    effective_user_id = user_id
    if mine:
        if current_user:
            effective_user_id = current_user.get("id")

    # Build user-scoped filters (admin can see all, regular users see only their own)
    filters = await get_user_filter(request, x_user_id=effective_user_id)

    # Apply optional filters
    if session_id:
        # session_id is the session UUID - use directly
        filters["session_id"] = session_id
    if message_type:
        filters["message_type"] = message_type

    # Log the query parameters for debugging
    logger.debug(
        f"[messages] Query: session_id={session_id} | "
        f"jwt_user_id={jwt_user_id} | "
        f"filters={filters}"
    )

    # Build order_by clause based on sort parameter
    order_by = f"created_at {sort.value.upper()}"

    # For date filtering, we need custom SQL (not supported by basic Repository)
    # For now, fetch all matching base filters and filter in Python
    # TODO: Extend Repository to support date range filters
    messages = await repo.find(
        filters,
        order_by=order_by,
        limit=limit + 1,  # Fetch one extra to determine has_more
        offset=offset,
    )

    # Apply date filters in Python if provided
    if start_date or end_date:
        start_dt = parse_iso(start_date) if start_date else None
        end_dt = parse_iso(end_date) if end_date else None

        filtered = []
        for msg in messages:
            if start_dt and msg.created_at < start_dt:
                continue
            if end_dt and msg.created_at > end_dt:
                continue
            filtered.append(msg)
        messages = filtered

    # Determine if there are more results
    has_more = len(messages) > limit
    if has_more:
        messages = messages[:limit]

    # Get total count for pagination info
    total = await repo.count(filters)

    # Log result count
    logger.debug(
        f"[messages] Result: returned={len(messages)} | total={total} | "
        f"session_id={session_id}"
    )

    return MessageListResponse(data=messages, total=total, has_more=has_more)


@router.get(
    "/messages/{message_id}",
    response_model=Message,
    tags=["messages"],
    responses={
        403: {"model": ErrorResponse, "description": "Access denied: not owner"},
        404: {"model": ErrorResponse, "description": "Message not found"},
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def get_message(
    request: Request,
    message_id: str,
) -> Message:
    """
    Get a specific message by ID.

    Access Control:
    - Regular users: Only access their own messages
    - Admin users: Can access any message

    Args:
        message_id: UUID of the message

    Returns:
        Message object if found

    Raises:
        404: Message not found
        403: Access denied (not owner and not admin)
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Message, table_name="messages")
    message = await repo.get_by_id(message_id)

    if not message:
        raise HTTPException(status_code=404, detail=f"Message '{message_id}' not found")

    # Check access: admin or owner
    current_user = get_current_user(request)
    if not is_admin(current_user):
        user_id = current_user.get("id") if current_user else None
        if message.user_id and message.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied: not owner")

    return message


# =============================================================================
# Sessions Endpoints
# =============================================================================


@router.get(
    "/sessions",
    response_model=SessionsQueryResponse,
    tags=["sessions"],
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled or connection failed"},
    },
)
async def list_sessions(
    request: Request,
    user_id: str | None = Query(default=None, description="Filter by user ID (admin only for cross-user)"),
    user_name: str | None = Query(default=None, description="Filter by user name (partial match, admin only)"),
    user_email: str | None = Query(default=None, description="Filter by user email (partial match, admin only)"),
    mode: SessionMode | None = Query(default=None, description="Filter by session mode"),
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=100, description="Number of results per page"),
) -> SessionsQueryResponse:
    """
    List sessions with optional filters and page-based pagination.

    Access Control:
    - Regular users: Only see their own sessions
    - Admin users: Can filter by any user_id, user_name, user_email, or see all sessions

    Filters:
    - user_id: Filter by session owner (admin only for cross-user)
    - user_name: Filter by user name partial match (admin only)
    - user_email: Filter by user email partial match (admin only)
    - mode: Filter by session mode (normal or evaluation)

    Pagination:
    - page: Page number (1-indexed, default: 1)
    - page_size: Number of sessions per page (default: 50, max: 100)

    Returns paginated results with user info ordered by created_at descending.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    current_user = get_current_user(request)
    admin = is_admin(current_user)

    # Get postgres service for raw SQL query
    db = get_postgres_service()
    if not db:
        raise HTTPException(status_code=503, detail="Database connection failed")
    if not db.pool:
        await db.connect()

    # Build effective filters based on user role
    effective_user_id = user_id
    effective_user_name = user_name if admin else None  # Only admin can search by name
    effective_user_email = user_email if admin else None  # Only admin can search by email

    if not admin:
        # Non-admin users can only see their own sessions
        effective_user_id = current_user.get("id") if current_user else None
        if not effective_user_id:
            # Anonymous user - return empty
            return SessionsQueryResponse(
                data=[],
                metadata=PaginationMetadata(
                    total=0, page=page, page_size=page_size,
                    total_pages=0, has_next=False, has_previous=False,
                ),
            )

    # Call the SQL function for sessions with user info
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM fn_list_sessions_with_user(
                $1, $2, $3, $4, $5, $6
            )
            """,
            effective_user_id,
            effective_user_name,
            effective_user_email,
            mode.value if mode else None,
            page,
            page_size,
        )

    # Extract total from first row
    total = rows[0]["total_count"] if rows else 0

    # Convert rows to SessionWithUser
    data = [
        SessionWithUser(
            id=str(row["id"]),
            name=row["name"],
            mode=row["mode"],
            description=row["description"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            user_email=row["user_email"],
            message_count=row["message_count"] or 0,
            total_tokens=row["total_tokens"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=row["metadata"],
        )
        for row in rows
    ]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return SessionsQueryResponse(
        data=data,
        metadata=PaginationMetadata(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_previous=page > 1,
        ),
    )


@router.post(
    "/sessions",
    response_model=Session,
    status_code=201,
    tags=["sessions"],
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def create_session(
    request_body: SessionCreateRequest,
    user: dict = Depends(require_admin),
    x_user_id: str = Header(alias="X-User-Id", default="default"),
) -> Session:
    """
    Create a new session.

    **Requires admin role.**

    For normal sessions, only name is required.
    For evaluation sessions, you can specify:
    - original_trace_id: The session being re-evaluated
    - settings_overrides: Model, temperature, prompt overrides
    - prompt: Custom prompt to test

    Headers:
    - X-User-Id: User identifier (owner of the session)

    Returns:
        Created session object
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    # Admin can specify x_user_id, or default to their own
    effective_user_id = x_user_id if x_user_id != "default" else user.get("id", "default")

    session = Session(
        name=request_body.name,
        mode=request_body.mode,
        description=request_body.description,
        original_trace_id=request_body.original_trace_id,
        settings_overrides=request_body.settings_overrides,
        prompt=request_body.prompt,
        agent_schema_uri=request_body.agent_schema_uri,
        user_id=effective_user_id,
        tenant_id="default",  # tenant_id not used for filtering, set to default
    )

    repo = Repository(Session, table_name="sessions")
    result = await repo.upsert(session)

    logger.info(
        f"Admin {user.get('email')} created session '{session.name}' "
        f"(mode={session.mode}) for user={effective_user_id}"
    )

    return result  # type: ignore


@router.get(
    "/sessions/{session_id}",
    response_model=Session,
    tags=["sessions"],
    responses={
        403: {"model": ErrorResponse, "description": "Access denied: not owner"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def get_session(
    request: Request,
    session_id: str,
) -> Session:
    """
    Get a specific session by ID.

    Access Control:
    - Regular users: Only access their own sessions
    - Admin users: Can access any session

    Args:
        session_id: UUID of the session

    Returns:
        Session object if found

    Raises:
        404: Session not found
        403: Access denied (not owner and not admin)
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Session, table_name="sessions")
    session = await repo.get_by_id(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Check access: admin or owner
    current_user = get_current_user(request)
    if not is_admin(current_user):
        user_id = current_user.get("id") if current_user else None
        if session.user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied: not owner")

    return session


@router.put(
    "/sessions/{session_id}",
    response_model=Session,
    tags=["sessions"],
    responses={
        403: {"model": ErrorResponse, "description": "Access denied: not owner"},
        404: {"model": ErrorResponse, "description": "Session not found"},
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def update_session(
    request: Request,
    session_id: str,
    request_body: SessionUpdateRequest,
) -> Session:
    """
    Update an existing session.

    Access Control:
    - Regular users: Only update their own sessions
    - Admin users: Can update any session

    Allows updating:
    - description
    - settings_overrides
    - prompt
    - message_count (typically updated automatically)
    - total_tokens (typically updated automatically)

    Args:
        session_id: UUID of the session

    Returns:
        Updated session object

    Raises:
        404: Session not found
        403: Access denied (not owner and not admin)
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Session, table_name="sessions")
    session = await repo.get_by_id(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Check access: admin or owner
    current_user = get_current_user(request)
    if not is_admin(current_user):
        user_id = current_user.get("id") if current_user else None
        if session.user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied: not owner")

    # Apply updates
    update_data = request_body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(session, field, value)

    session.updated_at = utc_now()

    result = await repo.update(session)
    return result
