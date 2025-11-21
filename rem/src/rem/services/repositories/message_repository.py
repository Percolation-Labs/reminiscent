"""MessageRepository for message entity persistence and session management."""

from loguru import logger

from rem.models.entities import Message
from rem.services.postgres import PostgresService
from rem.settings import settings


class MessageRepository:
    """Repository for Message entities with session grouping and filtering."""

    def __init__(self, db: PostgresService):
        self.db = db
        self.table = "messages"

    async def create(self, message: Message) -> Message:
        """
        Create a single message.

        Args:
            message: Message entity to create

        Returns:
            Created message with generated ID
        """
        if not settings.postgres.enabled:
            logger.warning("Postgres disabled, skipping message creation")
            return message

        await self.db.upsert(
            record=message,
            model=Message,
            table_name=self.table,
        )
        return message

    async def batch_create(self, messages: list[Message]) -> list[Message]:
        """
        Batch create messages.

        Args:
            messages: List of message entities to create

        Returns:
            Created messages with generated IDs
        """
        if not settings.postgres.enabled:
            logger.warning("Postgres disabled, skipping message batch creation")
            return messages

        await self.db.batch_upsert(
            records=messages,
            model=Message,
            table_name=self.table,
        )
        return messages

    async def get_by_session(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[Message]:
        """
        Get all messages for a session in chronological order.

        Args:
            session_id: Session identifier
            tenant_id: Tenant identifier for multi-tenancy isolation
            user_id: Optional user identifier for additional filtering
            limit: Optional limit on number of messages

        Returns:
            List of messages ordered by created_at
        """
        if not settings.postgres.enabled:
            logger.warning("Postgres disabled, returning empty message list")
            return []

        query = f"""
            SELECT * FROM {self.table}
            WHERE session_id = $1 AND tenant_id = $2
            {"AND user_id = $3" if user_id else ""}
            AND deleted_at IS NULL
            ORDER BY created_at ASC
            {"LIMIT $" + str(3 if user_id else 2) if limit else ""}
        """

        params = [session_id, tenant_id]
        if user_id:
            params.append(user_id)
        if limit:
            params.append(limit)

        rows = await self.db.fetch(query, *params)
        return [Message.model_validate(dict(row)) for row in rows]

    async def get_by_id(self, message_id: str, tenant_id: str) -> Message | None:
        """
        Get a single message by ID.

        Args:
            message_id: Message identifier
            tenant_id: Tenant identifier for multi-tenancy isolation

        Returns:
            Message entity or None if not found
        """
        if not settings.postgres.enabled:
            logger.warning("Postgres disabled, returning None for message get")
            return None

        query = f"""
            SELECT * FROM {self.table}
            WHERE id = $1 AND tenant_id = $2 AND deleted_at IS NULL
        """

        row = await self.db.fetchrow(query, message_id, tenant_id)
        return Message.model_validate(dict(row)) if row else None
