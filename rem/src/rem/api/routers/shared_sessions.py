"""
Session sharing endpoints.

Enables session sharing between users for collaborative access to conversation history.

Endpoints:
    POST   /api/v1/sessions/{session_id}/share                      - Share a session with another user
    DELETE /api/v1/sessions/{session_id}/share/{user_id}            - Revoke a share (soft delete)
    GET    /api/v1/sessions/shared-with-me                          - Get users sharing sessions with you
    GET    /api/v1/sessions/shared-with-me/{user_id}/messages       - Get messages from a user's shared sessions

See src/rem/models/entities/shared_session.py for full documentation.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from .common import ErrorResponse

from ..deps import get_current_user, require_auth
from ...models.entities import (
    Message,
    SharedSession,
    SharedSessionCreate,
    SharedWithMeResponse,
    SharedWithMeSummary,
)
from ...services.postgres import get_postgres_service
from ...settings import settings
from ...utils.date_utils import utc_now

router = APIRouter(prefix="/api/v1")


async def get_connected_postgres():
    """Get a connected PostgresService instance."""
    pg = get_postgres_service()
    if pg and not pg.pool:
        await pg.connect()
    return pg


# =============================================================================
# Request/Response Models
# =============================================================================


class PaginationMetadata(BaseModel):
    """Pagination metadata for paginated responses."""

    total: int = Field(description="Total number of records matching filters")
    page: int = Field(description="Current page number (1-indexed)")
    page_size: int = Field(description="Number of records per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there are more pages after this one")
    has_previous: bool = Field(description="Whether there are pages before this one")


class SharedMessagesResponse(BaseModel):
    """Response for shared messages query."""

    object: Literal["list"] = "list"
    data: list[Message] = Field(description="List of messages from shared sessions")
    metadata: PaginationMetadata = Field(description="Pagination metadata")


class ShareSessionResponse(BaseModel):
    """Response after sharing a session."""

    success: bool = True
    message: str
    share: SharedSession


# =============================================================================
# Share Session Endpoints
# =============================================================================


@router.post(
    "/sessions/{session_id}/share",
    response_model=ShareSessionResponse,
    status_code=201,
    tags=["sessions"],
    responses={
        400: {"model": ErrorResponse, "description": "Session already shared with this user"},
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def share_session(
    request: Request,
    session_id: str,
    body: SharedSessionCreate,
    user: dict = Depends(require_auth),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> ShareSessionResponse:
    """
    Share a session with another user.

    Creates a SharedSession record that grants the recipient access to view
    messages in this session.

    Args:
        session_id: The session to share
        body: Contains shared_with_user_id - the recipient

    Returns:
        The created SharedSession record

    Raises:
        400: Session already shared with this user
        503: Database not enabled
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    current_user_id = user.get("id", "default")
    pg = await get_connected_postgres()

    # Check if share already exists (active)
    existing = await pg.fetchrow(
        """
        SELECT id FROM shared_sessions
        WHERE tenant_id = $1
          AND session_id = $2
          AND owner_user_id = $3
          AND shared_with_user_id = $4
          AND deleted_at IS NULL
        """,
        x_tenant_id,
        session_id,
        current_user_id,
        body.shared_with_user_id,
    )

    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Session '{session_id}' is already shared with user '{body.shared_with_user_id}'",
        )

    # Create the share
    result = await pg.fetchrow(
        """
        INSERT INTO shared_sessions (session_id, owner_user_id, shared_with_user_id, tenant_id)
        VALUES ($1, $2, $3, $4)
        RETURNING id, session_id, owner_user_id, shared_with_user_id, tenant_id, created_at, updated_at, deleted_at
        """,
        session_id,
        current_user_id,
        body.shared_with_user_id,
        x_tenant_id,
    )

    share = SharedSession(
        id=result["id"],
        session_id=result["session_id"],
        owner_user_id=result["owner_user_id"],
        shared_with_user_id=result["shared_with_user_id"],
        tenant_id=result["tenant_id"],
        created_at=result["created_at"],
        updated_at=result["updated_at"],
        deleted_at=result["deleted_at"],
    )

    logger.debug(
        f"User {current_user_id} shared session '{session_id}' with {body.shared_with_user_id}"
    )

    return ShareSessionResponse(
        success=True,
        message=f"Session shared with {body.shared_with_user_id}",
        share=share,
    )


@router.delete(
    "/sessions/{session_id}/share/{shared_with_user_id}",
    status_code=200,
    tags=["sessions"],
    responses={
        404: {"model": ErrorResponse, "description": "Share not found"},
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def remove_session_share(
    request: Request,
    session_id: str,
    shared_with_user_id: str,
    user: dict = Depends(require_auth),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> dict:
    """
    Remove a session share (soft delete).

    Sets deleted_at on the SharedSession record. The share can be re-created
    later if needed.

    Args:
        session_id: The session to unshare
        shared_with_user_id: The user to remove access from

    Returns:
        Success message

    Raises:
        404: Share not found
        503: Database not enabled
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    current_user_id = user.get("id", "default")
    pg = await get_connected_postgres()

    # Soft delete the share
    result = await pg.fetchrow(
        """
        UPDATE shared_sessions
        SET deleted_at = $1, updated_at = $1
        WHERE tenant_id = $2
          AND session_id = $3
          AND owner_user_id = $4
          AND shared_with_user_id = $5
          AND deleted_at IS NULL
        RETURNING id
        """,
        utc_now(),
        x_tenant_id,
        session_id,
        current_user_id,
        shared_with_user_id,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Share not found for session '{session_id}' with user '{shared_with_user_id}'",
        )

    logger.debug(
        f"User {current_user_id} removed share for session '{session_id}' with {shared_with_user_id}"
    )

    return {
        "success": True,
        "message": f"Share removed for user {shared_with_user_id}",
    }


# =============================================================================
# Shared With Me Endpoints
# =============================================================================


@router.get(
    "/sessions/shared-with-me",
    response_model=SharedWithMeResponse,
    tags=["sessions"],
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def get_shared_with_me(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=100, description="Results per page"),
    user: dict = Depends(require_auth),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> SharedWithMeResponse:
    """
    Get aggregate summary of users sharing sessions with you.

    Returns a paginated list of users who have shared sessions with the
    current user, including message counts and date ranges.

    Each entry shows:
    - user_id, name, email of the person sharing
    - message_count: total messages across all their shared sessions
    - session_count: number of sessions they've shared
    - first_message_at, last_message_at: date range

    Results are ordered by most recent message first.
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    current_user_id = user.get("id", "default")
    pg = await get_connected_postgres()
    offset = (page - 1) * page_size

    # Get total count
    count_result = await pg.fetchrow(
        "SELECT fn_count_shared_with_me($1, $2) as total",
        x_tenant_id,
        current_user_id,
    )
    total = count_result["total"] if count_result else 0

    # Get paginated results
    rows = await pg.fetch(
        "SELECT * FROM fn_get_shared_with_me($1, $2, $3, $4)",
        x_tenant_id,
        current_user_id,
        page_size,
        offset,
    )

    data = [
        SharedWithMeSummary(
            user_id=row["user_id"],
            name=row["name"],
            email=row["email"],
            message_count=row["message_count"],
            session_count=row["session_count"],
            first_message_at=row["first_message_at"],
            last_message_at=row["last_message_at"],
        )
        for row in rows
    ]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return SharedWithMeResponse(
        data=data,
        metadata={
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_previous": page > 1,
        },
    )


@router.get(
    "/sessions/shared-with-me/{owner_user_id}/messages",
    response_model=SharedMessagesResponse,
    tags=["sessions"],
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def get_shared_messages(
    request: Request,
    owner_user_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=50, ge=1, le=100, description="Results per page"),
    user: dict = Depends(require_auth),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> SharedMessagesResponse:
    """
    Get messages from sessions shared by a specific user.

    Returns paginated messages from all sessions that owner_user_id has
    shared with the current user. Messages are ordered by created_at DESC.

    Args:
        owner_user_id: The user who shared the sessions

    Returns:
        Paginated list of Message objects
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    current_user_id = user.get("id", "default")
    pg = await get_connected_postgres()
    offset = (page - 1) * page_size

    # Get total count
    count_result = await pg.fetchrow(
        "SELECT fn_count_shared_messages($1, $2, $3) as total",
        x_tenant_id,
        current_user_id,
        owner_user_id,
    )
    total = count_result["total"] if count_result else 0

    # Get paginated messages
    rows = await pg.fetch(
        "SELECT * FROM fn_get_shared_messages($1, $2, $3, $4, $5)",
        x_tenant_id,
        current_user_id,
        owner_user_id,
        page_size,
        offset,
    )

    # Convert to Message objects
    data = [
        Message(
            id=row["id"],
            content=row["content"],
            message_type=row["message_type"],
            session_id=row["session_id"],
            model=row["model"],
            token_count=row["token_count"],
            created_at=row["created_at"],
            metadata=row["metadata"] or {},
            tenant_id=x_tenant_id,
        )
        for row in rows
    ]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return SharedMessagesResponse(
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
