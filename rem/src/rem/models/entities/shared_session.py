"""
SharedSession - Session sharing between users in REM.

SharedSessions enable collaborative access to conversation sessions. When a user
shares a session with another user, a SharedSession record is created to track
this relationship.

## Design Philosophy

Messages already have a session_id field that links them to sessions. The Session
entity itself is optional and can be left-joined - we don't require explicit Session
records for sharing to work. What matters is the session_id on messages.

SharedSession is a lightweight linking table that:
1. Records who shared which session with whom
2. Enables soft deletion (deleted_at) so shares can be revoked without data loss
3. Supports aggregation queries to see "who is sharing with me"

## Data Model

    SharedSession
    ├── session_id: str          # The session being shared (matches Message.session_id)
    ├── owner_user_id: str       # Who owns/created the session (the sharer)
    ├── shared_with_user_id: str # Who the session is shared with (the recipient)
    ├── tenant_id: str           # Multi-tenancy isolation
    ├── created_at: datetime     # When the share was created
    ├── updated_at: datetime     # Last modification
    └── deleted_at: datetime     # Soft delete (null = active share)

## Aggregation Query

The primary use case is answering: "Who is sharing messages with me?"

This is provided by a Postgres function that aggregates:
- Messages grouped by owner_user_id
- Joined with users table for name/email
- Counting messages with min/max dates
- Filtering out deleted shares

Result shape:
    {
        "user_id": "uuid",
        "name": "John Doe",
        "email": "john@example.com",
        "message_count": 42,
        "first_message_at": "2024-01-15T10:30:00Z",
        "last_message_at": "2024-03-20T14:45:00Z",
        "session_count": 3
    }

## API Endpoints

1. POST /api/v1/sessions/{session_id}/share
   - Share a session with another user
   - Body: { "shared_with_user_id": "..." }
   - Creates SharedSession record

2. DELETE /api/v1/sessions/{session_id}/share/{shared_with_user_id}
   - Revoke a share (soft delete)
   - Sets deleted_at on SharedSession

3. GET /api/v1/shared-with-me
   - Get paginated aggregate of users sharing with you
   - Query params: page, page_size (default 50)
   - Returns: list of user summaries with message counts

4. GET /api/v1/shared-with-me/{user_id}/messages
   - Get messages from a specific user's shared sessions
   - Uses existing session message loading
   - Respects pagination

## Soft Delete Pattern

Removing a share does NOT delete the SharedSession record. Instead:
- deleted_at is set to current timestamp
- All queries filter WHERE deleted_at IS NULL
- This preserves audit trail and allows "undo"

To permanently delete, an admin can run:
    DELETE FROM shared_sessions WHERE deleted_at IS NOT NULL AND deleted_at < NOW() - INTERVAL '30 days'

## Example Usage

    # Share a session
    POST /api/v1/sessions/abc-123/share
    {"shared_with_user_id": "user-456"}

    # See who's sharing with me
    GET /api/v1/shared-with-me
    {
        "data": [
            {
                "user_id": "user-789",
                "name": "Alice",
                "email": "alice@example.com",
                "message_count": 150,
                "session_count": 5,
                "first_message_at": "2024-01-01T00:00:00Z",
                "last_message_at": "2024-03-15T12:00:00Z"
            }
        ],
        "metadata": {"total": 1, "page": 1, "page_size": 50, ...}
    }

    # Get messages from Alice's shared sessions
    GET /api/v1/shared-with-me/user-789/messages?page=1&page_size=50

    # Revoke a share
    DELETE /api/v1/sessions/abc-123/share/user-456
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from ..core import CoreModel


class SharedSession(CoreModel):
    """
    Session sharing record between users.

    Links a session (identified by session_id from Message records) to a
    recipient user, enabling collaborative access to conversation history.
    """

    session_id: str = Field(
        ...,
        description="The session being shared (matches Message.session_id)",
    )
    owner_user_id: str = Field(
        ...,
        description="User ID of the session owner (the sharer)",
    )
    shared_with_user_id: str = Field(
        ...,
        description="User ID of the recipient (who can now view the session)",
    )


class SharedSessionCreate(BaseModel):
    """Request to create a session share."""

    shared_with_user_id: str = Field(
        ...,
        description="User ID to share the session with",
    )


class SharedWithMeSummary(BaseModel):
    """
    Aggregate summary of a user sharing sessions with you.

    Returned by GET /api/v1/shared-with-me endpoint.
    """

    user_id: str = Field(description="User ID of the person sharing with you")
    name: Optional[str] = Field(default=None, description="User's display name")
    email: Optional[str] = Field(default=None, description="User's email address")
    message_count: int = Field(description="Total messages across all shared sessions")
    session_count: int = Field(description="Number of sessions shared with you")
    first_message_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of earliest message in shared sessions",
    )
    last_message_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of most recent message in shared sessions",
    )


class SharedWithMeResponse(BaseModel):
    """Response for paginated shared-with-me query."""

    object: str = "list"
    data: list[SharedWithMeSummary] = Field(
        description="List of users sharing sessions with you"
    )
    metadata: dict = Field(description="Pagination metadata")
