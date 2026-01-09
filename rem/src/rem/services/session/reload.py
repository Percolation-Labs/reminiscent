"""Session reloading logic for conversation history restoration.

This module implements session history loading from the database,
allowing conversations to be resumed across multiple API calls.

Design Pattern:
- Session identified by session_id from X-Session-Id header
- All messages for session loaded in chronological order
- Long assistant messages compressed on load with REM LOOKUP hints
- Tool messages (register_metadata, etc.) are NEVER compressed
- Gracefully handles missing database (returns empty history)

Message Types on Reload:
- user: Returned as-is
- tool: Returned with metadata (tool_call_id, tool_name). tool_arguments may be in
  metadata (parent calls) or parsed from content (child calls) by pydantic_messages.py
- assistant: Compressed on load if long (>400 chars), with REM LOOKUP for recovery
"""

from loguru import logger

from rem.services.session.compression import SessionMessageStore
from rem.settings import settings


async def reload_session(
    session_id: str,
    user_id: str,
    compress_on_load: bool = True,
) -> list[dict]:
    """
    Reload all messages for a session from the database.

    Args:
        session_id: Session/conversation identifier
        user_id: User identifier for data isolation
        compress_on_load: Whether to compress long assistant messages (default: True)
                         Tool messages are NEVER compressed.

    Returns:
        List of message dicts in chronological order (oldest first)

    Example:
        ```python
        # In completions endpoint
        context = AgentContext.from_headers(dict(request.headers))

        # Reload previous conversation history
        history = await reload_session(
            session_id=context.session_id,
            user_id=context.user_id,
            compress_on_load=True,  # Compress long assistant messages
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
        store = SessionMessageStore(user_id=user_id)

        # Load messages (assistant messages compressed on load, tool messages never compressed)
        messages = await store.load_session_messages(
            session_id=session_id, user_id=user_id, compress_on_load=compress_on_load
        )

        logger.debug(
            f"Reloaded {len(messages)} messages for session {session_id} "
            f"(compress_on_load={compress_on_load})"
        )

        return messages

    except Exception as e:
        logger.error(f"Failed to reload session {session_id}: {e}")
        return []
