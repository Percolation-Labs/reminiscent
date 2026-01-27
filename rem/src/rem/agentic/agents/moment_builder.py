"""
Moment Builder - Session compression into discrete moments.

This module provides the MomentBuilder class that:
1. Loads unprocessed messages since last partition event
2. Calls the moment builder agent to create discrete moments
3. Saves moments to the database with previous_moment_keys
4. Inserts a partition event with recent_moments_summary and last_n_moment_keys
5. Updates session.last_moment_message_idx

Usage:
    builder = MomentBuilder(session_id=session_id, user_id=user_id)
    result = await builder.run()
"""

import json
from datetime import datetime
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field

from ...models.entities import Moment, Message, Session
from ...services.postgres import get_postgres_service
from ...settings import settings
from ...utils.date_utils import utc_now, to_iso


class MomentBuilderOutput(BaseModel):
    """Output schema for moment builder agent."""

    moments: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of moments created from the conversation",
    )
    user_summary_update: str | None = Field(
        default=None,
        description="Brief update to user's evolving summary",
    )


class MomentBuilderResult(BaseModel):
    """Result of a moment building run."""

    success: bool
    moments_created: int = 0
    partition_event_inserted: bool = False
    error: str | None = None


class MomentBuilder:
    """
    Builds moments from session messages.

    The moment builder:
    1. Queries messages since last partition event (incremental compaction)
    2. Calls the moment builder agent to identify discrete moments
    3. Saves moments with previous_moment_keys for backwards chaining
    4. Inserts partition event containing:
       - moment_keys: Keys of moments just created
       - last_n_moment_keys: Last N moment keys overall for full awareness
       - recent_moments_summary: Brief narrative of user's recent journey
    5. Updates session.last_moment_message_idx
    """

    def __init__(
        self,
        session_id: str,
        user_id: str,
        force: bool = False,
    ):
        """
        Initialize moment builder.

        Args:
            session_id: Session to build moments for
            user_id: User who owns the session
            force: Bypass threshold check
        """
        self.session_id = session_id
        self.user_id = user_id
        self.force = force

    async def run(self) -> MomentBuilderResult:
        """
        Run the moment builder.

        Returns:
            MomentBuilderResult with success status and counts
        """
        try:
            # 1. Load unprocessed messages (with lag applied)
            messages, partition_timestamp = await self._load_unprocessed_messages()

            if not messages:
                logger.info(
                    f"No unprocessed messages for session={self.session_id}"
                )
                return MomentBuilderResult(success=True)

            logger.info(
                f"Building moments from {len(messages)} messages "
                f"for session={self.session_id}"
            )

            # 2. Get previous moments for backwards chaining
            previous_moments = await self._get_recent_moments(limit=3)
            previous_moment_keys = [m["name"] for m in previous_moments if m.get("name")]

            # 3. Call the moment builder agent
            agent_output = await self._call_moment_agent(messages)

            if not agent_output.moments:
                logger.info(
                    f"Moment agent returned no moments for session={self.session_id}"
                )
                return MomentBuilderResult(success=True)

            # 4. Save moments to database
            moment_keys = await self._save_moments(
                agent_output.moments,
                previous_moment_keys,
            )

            # 5. Get last N moment keys for full awareness (including just created)
            last_n_moment_keys = await self._get_last_n_moment_keys(
                limit=settings.moment_builder.recent_moment_count
            )

            # 6. Generate recent moments summary
            recent_moments_summary = await self._generate_recent_moments_summary()

            # 7. Insert partition event (if enabled) - with backdated timestamp
            partition_inserted = False
            if settings.moment_builder.insert_partition_event:
                partition_inserted = await self._insert_partition_event(
                    moment_keys=moment_keys,
                    last_n_moment_keys=last_n_moment_keys,
                    recent_moments_summary=recent_moments_summary,
                    messages_compressed=len(messages),
                    partition_timestamp=partition_timestamp,
                )

            # 8. Update session tracking
            await self._update_session_tracking(len(messages))

            # 9. Update user summary (if provided)
            if agent_output.user_summary_update:
                await self._update_user_summary(agent_output.user_summary_update)

            logger.info(
                f"Moment builder completed: {len(moment_keys)} moments created, "
                f"partition_event={partition_inserted}"
            )

            return MomentBuilderResult(
                success=True,
                moments_created=len(moment_keys),
                partition_event_inserted=partition_inserted,
            )

        except Exception as e:
            logger.error(f"Moment builder failed: {e}")
            return MomentBuilderResult(success=False, error=str(e))

    async def _load_unprocessed_messages(self) -> tuple[list[dict[str, Any]], datetime | None]:
        """
        Load messages since last partition event, respecting the lag mechanism.

        Uses incremental compaction - only fetches messages created after
        the most recent session_partition event, then applies lag to ensure
        the partition event appears "in the past" from the LLM's perspective.

        Returns:
            Tuple of (messages_to_compress, partition_timestamp)
            - messages_to_compress: Messages that should be compressed (excludes lag)
            - partition_timestamp: When to insert the partition event (last message's timestamp)
        """
        postgres = get_postgres_service()
        if not postgres:
            return [], None

        await postgres.connect()
        try:
            # Query messages since last partition event
            # Note: message_type is used as role, tool info stored in metadata JSONB
            query = """
                SELECT id, session_id, message_type, content, metadata, created_at
                FROM messages
                WHERE session_id = $1
                  AND user_id = $2
                  AND deleted_at IS NULL
                  AND created_at > (
                    SELECT COALESCE(MAX(created_at), '1970-01-01'::timestamptz)
                    FROM messages
                    WHERE session_id = $1
                      AND user_id = $2
                      AND message_type = 'tool'
                      AND metadata->>'tool_name' = 'session_partition'
                  )
                  AND NOT (message_type = 'tool'
                           AND metadata->>'tool_name' = 'session_partition')
                ORDER BY created_at ASC
            """

            rows = await postgres.fetch(query, self.session_id, self.user_id)

            all_messages = [
                {
                    "id": str(row["id"]),
                    "session_id": row["session_id"],
                    "message_type": row["message_type"],
                    "role": row["message_type"] or "assistant",  # Use message_type as role
                    "content": row["content"],
                    "metadata": row["metadata"] or {},
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "_created_at_dt": row["created_at"],  # Keep datetime for partition timestamp
                }
                for row in rows
            ]

            # Apply lag mechanism - keep lag_messages after the moment boundary
            # This ensures the partition event appears "in the past"
            total_messages = len(all_messages)
            lag_by_count = settings.moment_builder.lag_messages
            lag_by_percent = int(total_messages * settings.moment_builder.lag_percentage)
            lag = max(lag_by_count, lag_by_percent)

            # Minimum threshold to compress - need at least lag + some messages to compress
            min_messages_to_compress = lag + 5
            if total_messages < min_messages_to_compress:
                logger.info(
                    f"Not enough messages for compression with lag: "
                    f"total={total_messages}, lag={lag}, min_required={min_messages_to_compress}"
                )
                return [], None

            # Compress messages up to (total - lag)
            compress_up_to = total_messages - lag
            messages_to_compress = all_messages[:compress_up_to]

            # Partition timestamp is the last message being compressed
            partition_timestamp = messages_to_compress[-1]["_created_at_dt"] if messages_to_compress else None

            logger.info(
                f"Lag mechanism applied: total={total_messages}, lag={lag}, "
                f"compressing first {compress_up_to} messages"
            )

            # Remove the internal datetime field before returning
            for msg in messages_to_compress:
                msg.pop("_created_at_dt", None)

            return messages_to_compress, partition_timestamp
        finally:
            await postgres.disconnect()

    async def _get_recent_moments(self, limit: int = 3) -> list[dict[str, Any]]:
        """Get the most recent moments for backwards chaining."""
        postgres = get_postgres_service()
        if not postgres:
            return []

        await postgres.connect()
        try:
            query = """
                SELECT name, summary, topic_tags, starts_timestamp
                FROM moments
                WHERE user_id = $1
                  AND source_session_id = $2
                  AND deleted_at IS NULL
                ORDER BY starts_timestamp DESC
                LIMIT $3
            """
            rows = await postgres.fetch(query, self.user_id, self.session_id, limit)
            return [dict(row) for row in rows]
        finally:
            await postgres.disconnect()

    async def _call_moment_agent(
        self,
        messages: list[dict[str, Any]],
    ) -> MomentBuilderOutput:
        """
        Call the moment builder agent to create moments.

        The agent receives the conversation messages and returns
        discrete moments with summaries, tags, and timestamps.
        """
        from .. import create_agent_from_schema_file, AgentContext

        # Format messages for the agent
        formatted_messages = self._format_messages_for_agent(messages)

        # Create agent context
        context = AgentContext(
            user_id=self.user_id,
            tenant_id=self.user_id,
            agent_schema_uri="moment-builder",
        )

        # Create agent from schema file
        agent = await create_agent_from_schema_file(
            schema_name_or_path="moment-builder",
            context=context,
        )

        # Build prompt
        prompt = f"""Analyze the following conversation messages and create a moment summary.

## Conversation Messages

{formatted_messages}

## Instructions

Create **1 moment** (or 2-3 only if the session has clearly distinct major phases).

A moment is a holistic narrative summary of a conversation segment. It should:
- Capture the full arc of what was discussed, even if multifaceted
- Be comprehensive enough to replace ~70% of context window
- Enable continuing the conversation without losing important context

For example, a single moment might be: "Technical discussion covering JWT authentication setup,
CORS configuration for React frontend, and initial AWS deployment planning. User is building
a Python API with security focus."

For each moment, provide:
- name: Descriptive title (e.g., "API Security and Deployment Planning Session")
- summary: 2-4 sentence narrative of what happened and key decisions/outcomes
- content: Detailed summary including specific technical details, code patterns discussed, decisions made
- topic_tags: All relevant topics covered (can be many for multifaceted moments)
- emotion_tags: Overall emotional arc of the session
- starts_timestamp: ISO timestamp of first message
- ends_timestamp: ISO timestamp of last message

Only split into multiple moments if there's a **major context shift** (e.g., completely
different project, next day, user explicitly starts new topic).

Optionally provide a user_summary_update with new learnings about this user's interests/patterns.
"""

        # Run the agent
        result = await agent.run(prompt)

        # Debug: log the result structure
        logger.debug(f"Moment agent result type: {type(result)}")
        logger.debug(f"Moment agent result attributes: {dir(result)}")
        if hasattr(result, "data"):
            logger.debug(f"result.data type: {type(result.data)}, value: {result.data}")
        if hasattr(result, "output"):
            logger.debug(f"result.output type: {type(result.output)}, value: {result.output}")

        # Parse the output - check both .data and .output patterns
        output_data = None
        if hasattr(result, "data") and result.data:
            output_data = result.data
        elif hasattr(result, "output") and result.output:
            output_data = result.output

        if output_data:
            if hasattr(output_data, "model_dump"):
                output_dict = output_data.model_dump()
            elif isinstance(output_data, dict):
                output_dict = output_data
            else:
                logger.warning(f"Unexpected output_data type: {type(output_data)}")
                output_dict = {}

            logger.debug(f"Parsed output_dict: {output_dict}")

            return MomentBuilderOutput(
                moments=output_dict.get("moments", []),
                user_summary_update=output_dict.get("user_summary_update"),
            )

        logger.warning("No data/output in agent result")
        return MomentBuilderOutput()

    def _format_messages_for_agent(self, messages: list[dict[str, Any]]) -> str:
        """Format messages as a readable conversation for the agent."""
        lines = []

        for msg in messages:
            timestamp = msg.get("created_at", "")
            role = msg.get("role") or msg.get("message_type", "unknown")
            content = msg.get("content", "")
            metadata = msg.get("metadata", {}) or {}

            # Handle different message types
            # Tool info is stored in metadata JSONB column
            if metadata.get("tool_name"):
                tool_name = metadata["tool_name"]
                tool_result = metadata.get("tool_result", content)
                lines.append(f"[{timestamp}] TOOL ({tool_name}): {tool_result}")
            elif metadata.get("tool_calls"):
                tool_calls = metadata["tool_calls"]
                lines.append(f"[{timestamp}] ASSISTANT (tool calls): {json.dumps(tool_calls)}")
            else:
                lines.append(f"[{timestamp}] {role.upper()}: {content}")

        return "\n".join(lines)

    async def _save_moments(
        self,
        moments_data: list[dict[str, Any]],
        previous_moment_keys: list[str],
    ) -> list[str]:
        """
        Save moments to the database.

        Returns list of moment keys (names).
        """
        postgres = get_postgres_service()
        if not postgres:
            return []

        await postgres.connect()
        try:
            moment_keys = []

            for moment_data in moments_data:
                # Parse timestamps
                starts_timestamp = moment_data.get("starts_timestamp")
                if isinstance(starts_timestamp, str):
                    starts_timestamp = datetime.fromisoformat(
                        starts_timestamp.replace("Z", "+00:00")
                    )
                elif not starts_timestamp:
                    starts_timestamp = utc_now()

                ends_timestamp = moment_data.get("ends_timestamp")
                if isinstance(ends_timestamp, str):
                    ends_timestamp = datetime.fromisoformat(
                        ends_timestamp.replace("Z", "+00:00")
                    )

                # Create moment entity
                moment = Moment(
                    tenant_id=self.user_id,
                    user_id=self.user_id,
                    name=moment_data.get("name"),
                    summary=moment_data.get("summary"),
                    topic_tags=moment_data.get("topic_tags", []),
                    emotion_tags=moment_data.get("emotion_tags", []),
                    starts_timestamp=starts_timestamp,
                    ends_timestamp=ends_timestamp,
                    source_session_id=self.session_id,
                    previous_moment_keys=previous_moment_keys,
                    category="session-compression",
                )

                # Save to database
                await postgres.batch_upsert(
                    records=[moment],
                    model=Moment,
                    table_name="moments",
                    entity_key_field="name",
                    generate_embeddings=True,
                )

                if moment.name:
                    moment_keys.append(moment.name)

                # Update previous_moment_keys for next moment in this batch
                # (chain within the batch)
                previous_moment_keys = [moment.name] if moment.name else []

            return moment_keys
        finally:
            await postgres.disconnect()

    async def _get_last_n_moment_keys(self, limit: int = 5) -> list[str]:
        """Get the last N moment keys for this user (across all sessions)."""
        postgres = get_postgres_service()
        if not postgres:
            return []

        await postgres.connect()
        try:
            query = """
                SELECT name FROM moments
                WHERE user_id = $1 AND deleted_at IS NULL
                ORDER BY starts_timestamp DESC
                LIMIT $2
            """
            rows = await postgres.fetch(query, self.user_id, limit)
            return [row["name"] for row in rows if row["name"]]
        finally:
            await postgres.disconnect()

    async def _generate_recent_moments_summary(self) -> str:
        """
        Generate a brief narrative summary of the user's recent journey.

        This summary helps the LLM understand the user's overall context
        without needing to read each moment individually.
        """
        postgres = get_postgres_service()
        if not postgres:
            return ""

        await postgres.connect()
        try:
            # Get recent moments with their summaries
            query = """
                SELECT name, summary, topic_tags, starts_timestamp
                FROM moments
                WHERE user_id = $1 AND deleted_at IS NULL
                ORDER BY starts_timestamp DESC
                LIMIT 5
            """
            rows = await postgres.fetch(query, self.user_id)

            if not rows:
                return "No previous moments recorded."

            # Build narrative
            parts = []
            for row in reversed(rows):  # Oldest to newest
                date_str = row["starts_timestamp"].strftime("%b %d") if row["starts_timestamp"] else "recently"
                topics = ", ".join(row["topic_tags"][:3]) if row["topic_tags"] else "general discussion"
                summary = row["summary"][:100] if row["summary"] else "conversation segment"
                parts.append(f"{date_str}: {summary} ({topics})")

            return "Recent journey: " + "; ".join(parts)
        finally:
            await postgres.disconnect()

    async def _insert_partition_event(
        self,
        moment_keys: list[str],
        last_n_moment_keys: list[str],
        recent_moments_summary: str,
        messages_compressed: int,
        partition_timestamp: datetime | None = None,
    ) -> bool:
        """
        Insert a session partition event as a marker at the compression boundary.

        The partition event is inserted with a backdated created_at timestamp
        (the timestamp of the last compressed message) to ensure it appears
        "in the past" when loading session history. This prevents the LLM
        from seeing a moment boundary right before the most recent messages.

        Args:
            moment_keys: Keys of moments just created in this compression
            last_n_moment_keys: Last N moment keys overall for full awareness
            recent_moments_summary: Brief narrative of user's recent journey
            messages_compressed: Number of messages compressed
            partition_timestamp: When to insert the partition (backdated). If None, uses now.
        """
        postgres = get_postgres_service()
        if not postgres:
            return False

        await postgres.connect()
        try:
            # Use backdated timestamp if provided, otherwise use now
            effective_timestamp = partition_timestamp or utc_now()

            # Build partition event content
            partition_content = {
                "partition_type": "moment_compression",
                "created_at": to_iso(effective_timestamp),
                "user_key": f"user-{self.user_id[:8]}",
                "moment_keys": moment_keys,
                "last_n_moment_keys": last_n_moment_keys,
                "recent_moments_summary": recent_moments_summary,
                "messages_compressed": messages_compressed,
                "summary": f"Compressed {messages_compressed} messages into {len(moment_keys)} moments. "
                           f"Use rem://moments/key/{{key}} for full context.",
                "recovery_hint": (
                    "This is a memory checkpoint. The conversation history before this point "
                    "has been summarized into moments. To recover detailed context, use "
                    "REM LOOKUP on the moment_keys above. You can chain backwards through "
                    "previous_moment_keys on each moment for deeper history."
                ),
            }

            # Insert partition event with backdated timestamp using raw SQL
            # This ensures the partition event appears at the correct chronological position
            query = """
                INSERT INTO messages (id, tenant_id, user_id, session_id, message_type, content, metadata, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $1, $2, 'tool', $3, $4, $5, NOW())
            """
            await postgres.execute(
                query,
                (
                    self.user_id,
                    self.session_id,
                    json.dumps(partition_content),
                    json.dumps({"tool_name": "session_partition", "tool_result": partition_content}),
                    effective_timestamp,
                ),
            )

            logger.info(
                f"Inserted partition event at {effective_timestamp.isoformat()} "
                f"(backdated by lag mechanism)"
            )

            return True
        finally:
            await postgres.disconnect()

    async def _update_session_tracking(self, messages_processed: int) -> None:
        """Update session.last_moment_message_idx."""
        postgres = get_postgres_service()
        if not postgres:
            return

        await postgres.connect()
        try:
            # Get current message count and update last_moment_message_idx
            query = """
                UPDATE sessions
                SET last_moment_message_idx = COALESCE(last_moment_message_idx, 0) + $1,
                    updated_at = NOW()
                WHERE name = $2 AND user_id = $3
            """
            await postgres.execute(query, (messages_processed, self.session_id, self.user_id))
        finally:
            await postgres.disconnect()

    async def _update_user_summary(self, summary_update: str) -> None:
        """
        Update user's evolving summary.

        Appends new learnings to the user's summary field.
        """
        postgres = get_postgres_service()
        if not postgres:
            return

        await postgres.connect()
        try:
            # Append to user summary (create if not exists)
            query = """
                UPDATE users
                SET summary = COALESCE(summary, '') || E'\\n' || $1,
                    updated_at = NOW()
                WHERE name = $2 OR id::text = $2
            """
            await postgres.execute(query, summary_update, self.user_id)
        finally:
            await postgres.disconnect()


async def run_moment_builder(
    session_id: str,
    user_id: str,
    force: bool = False,
) -> MomentBuilderResult:
    """
    Convenience function to run the moment builder.

    Args:
        session_id: Session to build moments for
        user_id: User who owns the session
        force: Bypass threshold check

    Returns:
        MomentBuilderResult with success status and counts
    """
    builder = MomentBuilder(session_id=session_id, user_id=user_id, force=force)
    return await builder.run()
