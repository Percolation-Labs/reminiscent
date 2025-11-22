"""Session message compression and rehydration for efficient context loading.

This module implements message compression to keep conversation history within
context windows while preserving full content via REM LOOKUP.

Design Pattern:
- Long assistant messages (>400 chars) are stored as separate Message entities
- In-memory conversation uses truncated versions with REM lookup hints
- Full content retrieved on-demand via LOOKUP queries
- Compression disabled when Postgres is disabled
"""

from typing import Any

from loguru import logger

from rem.models.entities import Message
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
        tenant_id: str,
        compressor: MessageCompressor | None = None,
    ):
        """
        Initialize session message store.

        Args:
            tenant_id: Tenant identifier
            compressor: Optional message compressor (creates default if None)
        """
        self.tenant_id = tenant_id
        self.compressor = compressor or MessageCompressor()
        self.repo = Repository(Message)

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
        entity_key = f"session-{session_id}-msg-{message_index}"

        # Create Message entity for assistant response
        msg = Message(
            content=message.get("content", ""),
            message_type=message.get("role", "assistant"),
            session_id=session_id,
            tenant_id=self.tenant_id,
            user_id=user_id,
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
                  AND tenant_id = $2
                  AND deleted_at IS NULL
                LIMIT 1
            """

            row = await self.repo.db.fetchrow(query, entity_key, self.tenant_id)

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

        Args:
            session_id: Session identifier
            messages: List of messages to store
            user_id: Optional user identifier
            compress: Whether to compress messages (default: True)

        Returns:
            List of compressed messages with REM lookup keys
        """
        if not settings.postgres.enabled:
            logger.debug("Postgres disabled, returning messages uncompressed")
            return messages

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
                # Short assistant messages, user messages, and system messages stored as-is
                # Store ALL messages in database for full audit trail
                msg = Message(
                    content=content,
                    message_type=message.get("role", "user"),
                    session_id=session_id,
                    tenant_id=self.tenant_id,
                    user_id=user_id,
                    metadata={
                        "message_index": idx,
                        "timestamp": message.get("timestamp"),
                    },
                )
                await self.repo.upsert(msg)
                compressed_messages.append(message.copy())

        return compressed_messages

    async def load_session_messages(
        self, session_id: str, user_id: str | None = None, decompress: bool = False
    ) -> list[dict[str, Any]]:
        """
        Load session messages from database.

        Args:
            session_id: Session identifier
            user_id: Optional user identifier for filtering
            decompress: Whether to decompress messages (default: False)

        Returns:
            List of session messages in chronological order
        """
        if not settings.postgres.enabled:
            logger.debug("Postgres disabled, returning empty message list")
            return []

        try:
            # Load messages from repository
            filters = {"session_id": session_id, "tenant_id": self.tenant_id}
            if user_id:
                filters["user_id"] = user_id

            messages = await self.repo.find(filters, order_by="created_at ASC")

            # Convert Message entities to dict format
            message_dicts = []
            for msg in messages:
                msg_dict = {
                    "role": msg.message_type or "assistant",
                    "content": msg.content,
                    "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                }

                # Check if message was compressed
                entity_key = msg.metadata.get("entity_key") if msg.metadata else None
                if entity_key and len(msg.content) <= self.compressor.min_length_for_compression:
                    # This is a compressed reference, mark it
                    msg_dict["_compressed"] = True
                    msg_dict["_entity_key"] = entity_key
                    msg_dict["_original_length"] = msg.metadata.get("original_length", 0)

                message_dicts.append(msg_dict)

            # Decompress if requested
            if decompress:
                decompressed_messages = []
                for message in message_dicts:
                    if self.compressor.is_compressed(message):
                        entity_key = self.compressor.get_entity_key(message)
                        if entity_key:
                            full_content = await self.retrieve_message(entity_key)
                            if full_content:
                                decompressed_messages.append(
                                    self.compressor.decompress_message(
                                        message, full_content
                                    )
                                )
                            else:
                                # Fallback to compressed version if retrieval fails
                                decompressed_messages.append(message)
                        else:
                            decompressed_messages.append(message)
                    else:
                        decompressed_messages.append(message)

                return decompressed_messages

            return message_dicts

        except Exception as e:
            logger.error(f"Failed to load session messages: {e}")
            return []
