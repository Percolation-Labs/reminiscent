"""Session message compression and rehydration for efficient context loading.

This module implements message storage and compression to keep conversation history
within context windows while preserving full content via REM LOOKUP.

Message Types and Storage Strategy
===================================

All messages are stored UNCOMPRESSED in the database for full audit/analysis.
Compression happens only on RELOAD when reconstructing context for the LLM.

Message Types:
- `user`: User messages - stored and reloaded as-is
- `tool`: Tool call messages (e.g., register_metadata) - stored and reloaded as-is
         NEVER compressed - contains important structured metadata
- `assistant`: Assistant text responses - stored uncompressed, but MAY BE
              compressed on reload if long (>400 chars) with REM LOOKUP hints

Example Session Flow:
```
Turn 1 (stored uncompressed):
  - user: "I have a headache"
  - tool: register_metadata({confidence: 0.3, collected_fields: {...}})
  - assistant: "I'm sorry to hear that. How long has this been going on?"

Turn 2 (stored uncompressed):
  - user: "About 3 days, really bad"
  - tool: register_metadata({confidence: 0.6, collected_fields: {...}})
  - assistant: "Got it - 3 days. On a scale of 1-10..."

On reload (for LLM context):
  - user messages: returned as-is
  - tool messages: returned as-is (never compressed)
  - assistant messages: compressed if long, with REM LOOKUP hint for full retrieval
```

REM LOOKUP Pattern:
- Long assistant messages get truncated with hint: "... [REM LOOKUP session-{id}-msg-{idx}] ..."
- Agent can retrieve full content on-demand using the LOOKUP key
- Keeps context window efficient while preserving data integrity

Key Design Decisions:
1. Store everything uncompressed - full audit trail in database
2. Compress only on reload - optimize for LLM context window
3. Never compress tool messages - structured metadata must stay intact
4. REM LOOKUP enables on-demand retrieval of full assistant responses
"""

from typing import Any

from loguru import logger

# Max length for entity keys (kv_store.entity_key is varchar(255))
MAX_ENTITY_KEY_LENGTH = 255


def truncate_key(key: str, max_length: int = MAX_ENTITY_KEY_LENGTH) -> str:
    """Truncate a key to max length, preserving useful suffix if possible."""
    if len(key) <= max_length:
        return key
    # Keep first part and add hash suffix for uniqueness
    import hashlib
    hash_suffix = hashlib.md5(key.encode()).hexdigest()[:8]
    truncated = key[:max_length - 9] + "-" + hash_suffix
    logger.warning(f"Truncated key from {len(key)} to {len(truncated)} chars: {key[:50]}...")
    return truncated

from rem.models.entities import Message, Session
from rem.services.postgres import PostgresService, Repository
from rem.settings import settings


class MessageCompressor:
    """Compress and decompress session messages with REM lookup keys."""

    def __init__(self, truncate_length: int = 200):
        """
        Initialize message compressor.

        Args:
            truncate_length: Number of characters to keep from start/end (default: 200)
        """
        self.truncate_length = truncate_length
        self.min_length_for_compression = truncate_length * 2

    def compress_message(
        self, message: dict[str, Any], entity_key: str | None = None
    ) -> dict[str, Any]:
        """
        Compress a message by truncating long content and adding REM lookup key.

        Args:
            message: Message dict with role and content
            entity_key: Optional REM lookup key for full message recovery

        Returns:
            Compressed message dict
        """
        content = message.get("content", "")

        # Don't compress short messages or system messages
        if (
            len(content) <= self.min_length_for_compression
            or message.get("role") == "system"
        ):
            return message.copy()

        # Compress long messages
        n = self.truncate_length
        start = content[:n]
        end = content[-n:]

        # Create compressed content with REM lookup hint
        if entity_key:
            compressed_content = f"{start}\n\n... [Message truncated - REM LOOKUP {entity_key} to recover full content] ...\n\n{end}"
        else:
            compressed_content = f"{start}\n\n... [Message truncated - {len(content) - 2*n} characters omitted] ...\n\n{end}"

        compressed_message = message.copy()
        compressed_message["content"] = compressed_content
        compressed_message["_compressed"] = True
        compressed_message["_original_length"] = len(content)
        if entity_key:
            compressed_message["_entity_key"] = entity_key

        logger.debug(
            f"Compressed message from {len(content)} to {len(compressed_content)} chars (key={entity_key})"
        )

        return compressed_message

    def decompress_message(
        self, message: dict[str, Any], full_content: str
    ) -> dict[str, Any]:
        """
        Decompress a message by restoring full content.

        Args:
            message: Compressed message dict
            full_content: Full content to restore

        Returns:
            Decompressed message dict
        """
        decompressed = message.copy()
        decompressed["content"] = full_content
        decompressed.pop("_compressed", None)
        decompressed.pop("_original_length", None)
        decompressed.pop("_entity_key", None)

        return decompressed

    def is_compressed(self, message: dict[str, Any]) -> bool:
        """Check if a message is compressed."""
        return message.get("_compressed", False)

    def get_entity_key(self, message: dict[str, Any]) -> str | None:
        """Get REM lookup key from compressed message."""
        return message.get("_entity_key")


class SessionMessageStore:
    """Store and retrieve session messages with compression."""

    def __init__(
        self,
        user_id: str,
        compressor: MessageCompressor | None = None,
    ):
        """
        Initialize session message store.

        Args:
            user_id: User identifier for data isolation
            compressor: Optional message compressor (creates default if None)
        """
        self.user_id = user_id
        self.compressor = compressor or MessageCompressor()
        self.repo = Repository(Message)
        self._session_repo = Repository(Session, table_name="sessions")

    async def _ensure_session_exists(
        self,
        session_id: str,
        user_id: str | None = None,
    ) -> None:
        """
        Ensure session exists, creating it if necessary.

        Args:
            session_id: Session UUID from X-Session-Id header
            user_id: Optional user identifier
        """
        try:
            # Check if session already exists by UUID
            existing = await self._session_repo.get_by_id(session_id)
            if existing:
                return  # Session already exists

            # Create new session with the provided UUID as id
            session = Session(
                id=session_id,  # Use the provided UUID as session id
                name=session_id,  # Default name to UUID, can be updated later
                user_id=user_id or self.user_id,
                tenant_id=self.user_id,  # tenant_id set to user_id for scoping
            )
            await self._session_repo.upsert(session)
            logger.info(f"Created session {session_id} for user {user_id or self.user_id}")

        except Exception as e:
            # Log but don't fail - session creation is best-effort
            logger.warning(f"Failed to ensure session exists: {e}")

    async def store_message(
        self,
        session_id: str,
        message: dict[str, Any],
        message_index: int,
        user_id: str | None = None,
    ) -> str:
        """
        Store a long assistant message as a Message entity for REM lookup.

        Args:
            session_id: Parent session identifier
            message: Message dict to store
            message_index: Index of message in conversation
            user_id: Optional user identifier

        Returns:
            Entity key for REM lookup (message ID)
        """
        if not settings.postgres.enabled:
            logger.debug("Postgres disabled, skipping message storage")
            return f"msg-{message_index}"

        # Create entity key for REM LOOKUP: session-{session_id}-msg-{index}
        # Truncate to avoid exceeding kv_store.entity_key varchar(255) limit
        entity_key = truncate_key(f"session-{session_id}-msg-{message_index}")

        # Create Message entity for assistant response
        # Use pre-generated id from message dict if available (for frontend feedback)
        msg = Message(
            id=message.get("id"),  # Use pre-generated ID if provided
            content=message.get("content", ""),
            message_type=message.get("role", "assistant"),
            session_id=session_id,
            tenant_id=self.user_id,  # Set tenant_id to user_id (application scoped to user)
            user_id=user_id or self.user_id,
            trace_id=message.get("trace_id"),
            span_id=message.get("span_id"),
            metadata={
                "message_index": message_index,
                "entity_key": entity_key,  # Store entity key for LOOKUP
                "timestamp": message.get("timestamp"),
            },
        )

        # Store in database
        await self.repo.upsert(msg)

        logger.debug(f"Stored assistant response: {entity_key} (id={msg.id})")
        return entity_key

    async def retrieve_message(self, entity_key: str) -> str | None:
        """
        Retrieve full message content by REM lookup key.

        Uses LOOKUP query pattern: finds message by entity_key in metadata.

        Args:
            entity_key: REM lookup key (session-{id}-msg-{index})

        Returns:
            Full message content or None if not found
        """
        if not settings.postgres.enabled:
            logger.debug("Postgres disabled, cannot retrieve message")
            return None

        try:
            # LOOKUP pattern: find message by entity_key in metadata
            query = """
                SELECT * FROM messages
                WHERE metadata->>'entity_key' = $1
                  AND user_id = $2
                  AND deleted_at IS NULL
                LIMIT 1
            """

            if not self.repo.db:
                logger.warning("Database not available for message lookup")
                return None

            row = await self.repo.db.fetchrow(query, entity_key, self.user_id)

            if row:
                msg = Message.model_validate(dict(row))
                logger.debug(f"Retrieved message via LOOKUP: {entity_key}")
                return msg.content

            logger.warning(f"Message not found via LOOKUP: {entity_key}")
            return None

        except Exception as e:
            logger.error(f"Failed to retrieve message {entity_key}: {e}")
            return None

    async def store_session_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        user_id: str | None = None,
        compress: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Store all session messages and return compressed versions.

        Ensures session exists before storing messages.

        Args:
            session_id: Session UUID
            messages: List of messages to store
            user_id: Optional user identifier
            compress: Whether to compress messages (default: True)

        Returns:
            List of compressed messages with REM lookup keys
        """
        if not settings.postgres.enabled:
            logger.debug("Postgres disabled, returning messages uncompressed")
            return messages

        # Ensure session exists before storing messages
        await self._ensure_session_exists(session_id, user_id)

        compressed_messages = []

        for idx, message in enumerate(messages):
            content = message.get("content", "")

            # Only store and compress long assistant responses
            if (
                message.get("role") == "assistant"
                and len(content) > self.compressor.min_length_for_compression
            ):
                # Store full message as separate Message entity
                entity_key = await self.store_message(
                    session_id, message, idx, user_id
                )

                if compress:
                    compressed_msg = self.compressor.compress_message(
                        message, entity_key
                    )
                    compressed_messages.append(compressed_msg)
                else:
                    msg_copy = message.copy()
                    msg_copy["_entity_key"] = entity_key
                    compressed_messages.append(msg_copy)
            else:
                # Short assistant messages, user messages, tool messages, and system messages stored as-is
                # Store ALL messages in database for full audit trail
                # Build metadata dict with standard fields
                msg_metadata = {
                    "message_index": idx,
                    "timestamp": message.get("timestamp"),
                }

                # For tool messages, include tool call details in metadata
                if message.get("role") == "tool":
                    if message.get("tool_call_id"):
                        msg_metadata["tool_call_id"] = message.get("tool_call_id")
                    if message.get("tool_name"):
                        msg_metadata["tool_name"] = message.get("tool_name")
                    if message.get("tool_arguments"):
                        msg_metadata["tool_arguments"] = message.get("tool_arguments")

                msg = Message(
                    id=message.get("id"),  # Use pre-generated ID if provided
                    content=content,
                    message_type=message.get("role", "user"),
                    session_id=session_id,
                    tenant_id=self.user_id,  # Set tenant_id to user_id (application scoped to user)
                    user_id=user_id or self.user_id,
                    trace_id=message.get("trace_id"),
                    span_id=message.get("span_id"),
                    metadata=msg_metadata,
                )
                await self.repo.upsert(msg)
                compressed_messages.append(message.copy())

        return compressed_messages

    async def load_session_messages(
        self, session_id: str, user_id: str | None = None, compress_on_load: bool = True
    ) -> list[dict[str, Any]]:
        """
        Load session messages from database, optionally compressing long assistant messages.

        Compression on Load:
        - Tool messages (role: "tool") are NEVER compressed - they contain structured metadata
        - User messages are returned as-is
        - Assistant messages MAY be compressed if long (>400 chars) with REM LOOKUP hints

        Args:
            session_id: Session identifier
            user_id: Optional user identifier for filtering
            compress_on_load: Whether to compress long assistant messages (default: True)

        Returns:
            List of session messages in chronological order, with long assistant
            messages optionally compressed with REM LOOKUP hints
        """
        if not settings.postgres.enabled:
            logger.debug("Postgres disabled, returning empty message list")
            return []

        try:
            # Load messages from repository
            # Note: tenant_id column in messages table maps to user_id (user-scoped partitioning)
            filters = {"session_id": session_id, "tenant_id": self.user_id}
            if user_id:
                filters["user_id"] = user_id

            messages = await self.repo.find(filters, order_by="created_at ASC")

            # Convert Message entities to dict format
            message_dicts = []
            for idx, msg in enumerate(messages):
                role = msg.message_type or "assistant"
                msg_dict = {
                    "role": role,
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                }

                # For tool messages, reconstruct tool call metadata
                if role == "tool" and msg.metadata:
                    if msg.metadata.get("tool_call_id"):
                        msg_dict["tool_call_id"] = msg.metadata["tool_call_id"]
                    if msg.metadata.get("tool_name"):
                        msg_dict["tool_name"] = msg.metadata["tool_name"]
                    if msg.metadata.get("tool_arguments"):
                        msg_dict["tool_arguments"] = msg.metadata["tool_arguments"]

                # Compress long ASSISTANT messages on load (never tool messages)
                if (
                    compress_on_load
                    and role == "assistant"
                    and len(msg.content) > self.compressor.min_length_for_compression
                ):
                    # Generate entity key for REM LOOKUP
                    entity_key = truncate_key(f"session-{session_id}-msg-{idx}")
                    msg_dict = self.compressor.compress_message(msg_dict, entity_key)

                message_dicts.append(msg_dict)

            logger.debug(
                f"Loaded {len(message_dicts)} messages for session {session_id} "
                f"(compress_on_load={compress_on_load})"
            )
            return message_dicts

        except Exception as e:
            logger.error(f"Failed to load session messages: {e}")
            return []

    async def retrieve_full_message(self, session_id: str, message_index: int) -> str | None:
        """
        Retrieve full message content by session and message index (for REM LOOKUP).

        This is used when an agent needs to recover full content from a compressed
        message that has a REM LOOKUP hint.

        Args:
            session_id: Session identifier
            message_index: Index of message in session (from REM LOOKUP key)

        Returns:
            Full message content or None if not found
        """
        entity_key = truncate_key(f"session-{session_id}-msg-{message_index}")
        return await self.retrieve_message(entity_key)
