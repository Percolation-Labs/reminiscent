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
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

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
    """Response for session list endpoint."""

    object: Literal["list"] = "list"
    data: list[Session]
    total: int
    has_more: bool


# =============================================================================
# Messages Endpoints
# =============================================================================


@router.get("/messages", response_model=MessageListResponse, tags=["messages"])
async def list_messages(
    request: Request,
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
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> MessageListResponse:
    """
    List messages with optional filters.

    Access Control:
    - Regular users: Only see their own messages
    - Admin users: Can filter by any user_id or see all messages

    Filters can be combined:
    - user_id: Filter by the user who created/owns the message (admin only for cross-user)
    - session_id: Filter by conversation session
    - start_date/end_date: Filter by creation time range (ISO 8601 format)
    - message_type: Filter by role (user, assistant, system, tool)

    Returns paginated results ordered by created_at descending.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Message, table_name="messages")

    # Build user-scoped filters (admin can see all, regular users see only their own)
    filters = await get_user_filter(request, x_user_id=user_id, x_tenant_id=x_tenant_id)

    # Apply optional filters
    if session_id:
        filters["session_id"] = session_id
    if message_type:
        filters["message_type"] = message_type

    # For date filtering, we need custom SQL (not supported by basic Repository)
    # For now, fetch all matching base filters and filter in Python
    # TODO: Extend Repository to support date range filters
    messages = await repo.find(
        filters,
        order_by="created_at DESC",
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

    return MessageListResponse(data=messages, total=total, has_more=has_more)


@router.get("/messages/{message_id}", response_model=Message, tags=["messages"])
async def get_message(
    request: Request,
    message_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
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
    message = await repo.get_by_id(message_id, x_tenant_id)

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


@router.get("/sessions", response_model=SessionListResponse, tags=["sessions"])
async def list_sessions(
    request: Request,
    user_id: str | None = Query(default=None, description="Filter by user ID (admin only for cross-user)"),
    mode: SessionMode | None = Query(default=None, description="Filter by session mode"),
    limit: int = Query(default=50, ge=1, le=100, description="Max results to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> SessionListResponse:
    """
    List sessions with optional filters.

    Access Control:
    - Regular users: Only see their own sessions
    - Admin users: Can filter by any user_id or see all sessions

    Filters:
    - user_id: Filter by session owner (admin only for cross-user)
    - mode: Filter by session mode (normal or evaluation)

    Returns paginated results ordered by created_at descending.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Session, table_name="sessions")

    # Build user-scoped filters (admin can see all, regular users see only their own)
    filters = await get_user_filter(request, x_user_id=user_id, x_tenant_id=x_tenant_id)
    if mode:
        filters["mode"] = mode.value

    sessions = await repo.find(
        filters,
        order_by="created_at DESC",
        limit=limit + 1,
        offset=offset,
    )

    has_more = len(sessions) > limit
    if has_more:
        sessions = sessions[:limit]

    total = await repo.count(filters)

    return SessionListResponse(data=sessions, total=total, has_more=has_more)


@router.post("/sessions", response_model=Session, status_code=201, tags=["sessions"])
async def create_session(
    request_body: SessionCreateRequest,
    user: dict = Depends(require_admin),
    x_user_id: str = Header(alias="X-User-Id", default="default"),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
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
    - X-Tenant-Id: Tenant identifier

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
        tenant_id=x_tenant_id,
    )

    repo = Repository(Session, table_name="sessions")
    result = await repo.upsert(session)

    logger.info(
        f"Admin {user.get('email')} created session '{session.name}' "
        f"(mode={session.mode}) for user={effective_user_id}"
    )

    return result  # type: ignore


@router.get("/sessions/{session_id}", response_model=Session, tags=["sessions"])
async def get_session(
    request: Request,
    session_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> Session:
    """
    Get a specific session by ID.

    Access Control:
    - Regular users: Only access their own sessions
    - Admin users: Can access any session

    Args:
        session_id: UUID or name of the session

    Returns:
        Session object if found

    Raises:
        404: Session not found
        403: Access denied (not owner and not admin)
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Session, table_name="sessions")
    session = await repo.get_by_id(session_id, x_tenant_id)

    if not session:
        # Try finding by name
        sessions = await repo.find({"name": session_id, "tenant_id": x_tenant_id}, limit=1)
        if sessions:
            session = sessions[0]
        else:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # Check access: admin or owner
    current_user = get_current_user(request)
    if not is_admin(current_user):
        user_id = current_user.get("id") if current_user else None
        if session.user_id and session.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied: not owner")

    return session


@router.put("/sessions/{session_id}", response_model=Session, tags=["sessions"])
async def update_session(
    request: Request,
    session_id: str,
    request_body: SessionUpdateRequest,
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
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
    session = await repo.get_by_id(session_id, x_tenant_id)

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
