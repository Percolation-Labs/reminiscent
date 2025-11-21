"""Session reloading logic for conversation history restoration.

This module implements session history loading from the database,
allowing conversations to be resumed across multiple API calls.

Design Pattern:
- Session identified by session_id from X-Session-Id header
- All messages for session loaded in chronological order
- Optional decompression of long assistant messages via REM LOOKUP
- Gracefully handles missing database (returns empty history)
"""

from loguru import logger

from rem.services.postgres import PostgresService
from rem.services.session.compression import SessionMessageStore
from rem.settings import settings


async def reload_session(
    db: PostgresService,
    session_id: str,
    tenant_id: str,
    user_id: str | None = None,
    decompress_messages: bool = False,
) -> list[dict]:
    """
    Reload all messages for a session from the database.

    Args:
        db: Postgres service instance
        session_id: Session/conversation identifier
        tenant_id: Tenant identifier for multi-tenancy isolation
        user_id: Optional user identifier for filtering
        decompress_messages: Whether to decompress long messages via REM LOOKUP

    Returns:
        List of message dicts in chronological order (oldest first)

    Example:
        ```python
        # In completions endpoint
        context = AgentContext.from_headers(dict(request.headers))

        # Reload previous conversation history
        history = await reload_session(
            db=db,
            session_id=context.session_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            decompress_messages=False,  # Use compressed versions for efficiency
        )

        # Combine with new user message
        messages = history + [{"role": "user", "content": prompt}]
        ```
    """
    if not settings.postgres.enabled:
        logger.debug("Postgres disabled, returning empty session history")
        return []

    if not session_id:
        logger.debug("No session_id provided, returning empty history")
        return []

    try:
        # Create message store for this session
        store = SessionMessageStore(db=db, tenant_id=tenant_id)

        # Load messages (optionally decompressed)
        messages = await store.load_session_messages(
            session_id=session_id, user_id=user_id, decompress=decompress_messages
        )

        logger.info(
            f"Reloaded {len(messages)} messages for session {session_id} "
            f"(decompressed={decompress_messages})"
        )

        return messages

    except Exception as e:
        logger.error(f"Failed to reload session {session_id}: {e}")
        return []
