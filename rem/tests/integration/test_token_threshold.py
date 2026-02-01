"""
Integration test for token threshold filtering.

Tests the actual behavior:
1. Messages loaded from session are filtered when token threshold exceeded
2. When truncation happens, a moment summary is injected for context
"""

import uuid
from datetime import datetime

import pytest

from rem.services.session.compression import filter_within_token_threshold
from rem.utils.agentic_chunking import estimate_tokens


@pytest.mark.db_only
class TestTokenThresholdIntegration:
    """Integration tests for token threshold filtering with real database."""

    @pytest.fixture
    def session_id(self):
        return str(uuid.uuid4())

    @pytest.fixture
    def user_id(self):
        return str(uuid.uuid4())

    @pytest.fixture
    def many_messages(self):
        """Create 100 messages with substantial content (~500 tokens each)."""
        messages = []
        for i in range(100):
            role = "user" if i % 2 == 0 else "assistant"
            # Each message ~500 tokens (100 words * ~5 chars = 500 chars / 4 ≈ 125 tokens with tiktoken)
            content = f"Message {i}: " + ("This is a detailed message with content. " * 25)
            messages.append({"role": role, "content": content})
        return messages

    @pytest.fixture
    def few_large_messages(self):
        """Create 20 messages with very large content (~5000 tokens each = 100K total)."""
        messages = []
        for i in range(20):
            role = "user" if i % 2 == 0 else "assistant"
            # Each message ~5000 tokens
            content = f"Message {i}: " + ("This is detailed content. " * 500)
            messages.append({"role": role, "content": content})
        return messages

    @pytest.mark.asyncio
    async def test_messages_within_threshold_not_truncated(self, session_id, user_id):
        """Messages within threshold should all be returned."""
        # Small set of messages well under threshold
        messages = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thanks for asking!"},
            {"role": "user", "content": "That's good to hear."},
        ]

        filtered, total_tokens = await filter_within_token_threshold(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            token_threshold=90000,
            model="gpt-4o",
        )

        # All messages kept
        assert len(filtered) == len(messages)
        assert total_tokens < 90000

    @pytest.mark.asyncio
    async def test_messages_exceeding_threshold_truncated(self, session_id, user_id, many_messages):
        """Messages exceeding threshold should be truncated to fit."""
        # Calculate original token count
        original_tokens = sum(
            estimate_tokens(m.get("content", ""), "gpt-4o") + 4
            for m in many_messages
        )

        # Set threshold to about half
        threshold = original_tokens // 2

        filtered, total_tokens = await filter_within_token_threshold(
            messages=many_messages,
            session_id=session_id,
            user_id=user_id,
            token_threshold=threshold,
            model="gpt-4o",
        )

        # Fewer messages
        assert len(filtered) < len(many_messages)
        # Within threshold
        assert total_tokens <= threshold
        # Most recent messages preserved (newest at end)
        assert many_messages[-1]["content"] in filtered[-1]["content"]

    @pytest.mark.asyncio
    async def test_few_messages_high_tokens_truncated(self, session_id, user_id, few_large_messages):
        """
        The original problem case: few messages (20) with high token count (100K).

        Message count (20) is below message threshold (200), but token count (100K)
        exceeds token threshold (90K). Should still truncate.
        """
        filtered, total_tokens = await filter_within_token_threshold(
            messages=few_large_messages,
            session_id=session_id,
            user_id=user_id,
            token_threshold=50000,  # Force truncation
            model="gpt-4o",
        )

        # Should truncate
        assert len(filtered) < len(few_large_messages)
        # Should be within threshold
        assert total_tokens <= 50000

    @pytest.mark.asyncio
    async def test_empty_messages_returns_empty(self, session_id, user_id):
        """Empty message list should return empty."""
        filtered, total_tokens = await filter_within_token_threshold(
            messages=[],
            session_id=session_id,
            user_id=user_id,
            token_threshold=90000,
        )

        assert filtered == []
        assert total_tokens == 0

    @pytest.mark.asyncio
    async def test_newest_messages_preserved_on_truncation(self, session_id, user_id, many_messages):
        """When truncating, newest messages should be kept, oldest dropped."""
        # Very low threshold to force aggressive truncation
        filtered, total_tokens = await filter_within_token_threshold(
            messages=many_messages,
            session_id=session_id,
            user_id=user_id,
            token_threshold=5000,  # Very low
            model="gpt-4o",
        )

        # Should have much fewer messages (100 original, should be truncated significantly)
        assert len(filtered) < len(many_messages) // 2

        # Most recent messages should be present
        if len(filtered) > 0:
            # Last original message should be in filtered list
            last_original = many_messages[-1]["content"]
            assert any(last_original in m.get("content", "") for m in filtered)

    @pytest.mark.asyncio
    async def test_moment_injected_when_truncating_with_existing_moment(self):
        """When truncating, inject moment summary if one exists for the truncated period."""
        from rem.services.postgres import get_postgres_service

        session_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        tenant_id = "test-tenant"

        # Create messages that will be truncated
        messages = []
        for i in range(50):
            role = "user" if i % 2 == 0 else "assistant"
            content = f"Message {i}: " + ("This is detailed content. " * 100)
            messages.append({"role": role, "content": content})

        # Insert a moment in the database for this session
        postgres = get_postgres_service()
        await postgres.connect()

        try:
            moment_id = str(uuid.uuid4())
            moment_summary = "Earlier in this session, the user discussed anxiety symptoms and coping strategies."

            # Insert the moment with correct column names from schema
            # Use naive datetime since table uses TIMESTAMP without timezone
            # Include category='session-compression' which the lookup query requires
            now = datetime.utcnow()
            await postgres.execute(
                """
                INSERT INTO moments (id, user_id, tenant_id, source_session_id, name, summary,
                                   starts_timestamp, ends_timestamp, category, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                (
                    moment_id,
                    user_id,
                    tenant_id,
                    session_id,
                    "Test Moment",
                    moment_summary,
                    now,
                    now,  # ends_timestamp - needed for ORDER BY
                    "session-compression",  # category - required by lookup query
                    now,
                ),
            )

            # Now filter with truncation
            filtered, total_tokens = await filter_within_token_threshold(
                messages=messages,
                session_id=session_id,
                user_id=user_id,
                token_threshold=10000,  # Force truncation
                model="gpt-4o",
            )

            # Should be truncated
            assert len(filtered) < len(messages)

            # The moment summary should be injected at the beginning
            has_moment = any(
                "[CONVERSATION HISTORY SUMMARY]" in m.get("content", "")
                or moment_summary in m.get("content", "")
                for m in filtered
            )
            assert has_moment, "Moment summary should be injected when truncating"

        finally:
            # Cleanup - need to reconnect since filter_within_token_threshold may have disconnected
            await postgres.connect()
            await postgres.execute(
                "DELETE FROM moments WHERE id = $1",
                (moment_id,),
            )
            await postgres.disconnect()

    @pytest.mark.asyncio
    async def test_no_duplicate_moment_if_already_present(self, session_id, user_id):
        """If messages already contain a moment summary, don't add another."""
        # Messages that already have a moment summary
        messages = [
            {"role": "system", "content": "[CONVERSATION HISTORY SUMMARY]\nPrevious discussion about anxiety."},
            {"role": "user", "content": "How are you feeling?" * 50},
            {"role": "assistant", "content": "I understand your concern." * 100},
            {"role": "user", "content": "What should I do?" * 50},
            {"role": "assistant", "content": "Here are some strategies." * 100},
        ]

        filtered, total_tokens = await filter_within_token_threshold(
            messages=messages,
            session_id=session_id,
            user_id=user_id,
            token_threshold=5000,  # Force truncation
            model="gpt-4o",
        )

        # Count moment summaries - should be at most 1
        moment_count = sum(
            1 for m in filtered
            if "[CONVERSATION HISTORY SUMMARY]" in m.get("content", "")
        )
        assert moment_count <= 1, "Should not duplicate moment summaries"
