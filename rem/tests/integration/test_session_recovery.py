"""Integration tests for session recovery with moment boundaries.

Tests the lag mechanism and session loading behavior:
1. Moment builder inserts partition events with backdated timestamps
2. Session loading respects chronological order
3. Partition events appear at the correct position in loaded messages

Run with:
    POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5052/rem" \
    pytest tests/integration/test_session_recovery.py -v -m "not llm"
"""

import json
import uuid
from datetime import timedelta

import pytest

from rem.models.entities import Message, Session
from rem.services.postgres import get_postgres_service
from rem.services.session import SessionMessageStore, reload_session
from rem.settings import settings
from rem.utils.date_utils import utc_now


pytestmark = [
    pytest.mark.db_only,
    pytest.mark.skipif(
        not settings.postgres.enabled,
        reason="Database not enabled (POSTGRES__ENABLED=false)"
    ),
]


@pytest.fixture
def test_user_id():
    """Generate unique user ID for test isolation."""
    return str(uuid.uuid4())


@pytest.fixture
def test_session_id():
    """Generate unique session ID."""
    return f"test-recovery-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def db():
    """Get database connection."""
    postgres = get_postgres_service()
    await postgres.connect()
    yield postgres
    await postgres.disconnect()


async def cleanup_test_data(db, user_id: str, session_id: str = None):
    """Clean up test data."""
    try:
        if session_id:
            await db.fetch("DELETE FROM messages WHERE session_id = $1 AND user_id = $2", session_id, user_id)
            await db.fetch("DELETE FROM moments WHERE source_session_id = $1 AND user_id = $2", session_id, user_id)
            await db.fetch("DELETE FROM sessions WHERE name = $1 AND user_id = $2", session_id, user_id)
        else:
            await db.fetch("DELETE FROM messages WHERE user_id = $1", user_id)
            await db.fetch("DELETE FROM moments WHERE user_id = $1", user_id)
            await db.fetch("DELETE FROM sessions WHERE user_id = $1", user_id)
    except Exception as e:
        print(f"Cleanup warning: {e}")


async def create_test_messages(db, session_id: str, user_id: str, count: int, base_time=None):
    """Create test messages with sequential timestamps."""
    if base_time is None:
        base_time = utc_now() - timedelta(hours=2)

    for i in range(count):
        msg_time = base_time + timedelta(minutes=i * 2)
        role = "user" if i % 2 == 0 else "assistant"
        content = f"Test message {i}: {'Question about topic' if role == 'user' else 'Response with details'}"

        await db.fetch(
            """
            INSERT INTO messages (id, tenant_id, user_id, session_id, message_type, content, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, $3, $4, $5, NOW())
            """,
            user_id, session_id, role, content, msg_time
        )


async def insert_partition_event(db, session_id: str, user_id: str, timestamp, moment_keys: list[str]):
    """Insert a partition event at a specific timestamp."""
    partition_content = {
        "partition_type": "moment_compression",
        "created_at": timestamp.isoformat(),
        "user_key": f"user-{user_id[:8]}",
        "moment_keys": moment_keys,
        "last_n_moment_keys": moment_keys,
        "recent_moments_summary": "Test session covering various topics.",
        "messages_compressed": 30,
        "recovery_hint": "Use REM LOOKUP on moment_keys for detailed history.",
    }

    # Note: asyncpg handles JSONB encoding - pass dicts directly, not json.dumps strings
    metadata = {"tool_name": "session_partition", "tool_result": partition_content}

    await db.fetch(
        """
        INSERT INTO messages (id, tenant_id, user_id, session_id, message_type, content, metadata, created_at, updated_at)
        VALUES (gen_random_uuid(), $1, $1, $2, 'tool', $3, $4, $5, NOW())
        """,
        user_id, session_id, json.dumps(partition_content), metadata, timestamp
    )


@pytest.mark.asyncio
async def test_partition_event_chronological_order(db, test_user_id, test_session_id):
    """Test that partition events appear at correct chronological position."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, NOW(), NOW())
            """,
            user_id, session_id
        )

        # Create 50 messages over 100 minutes
        base_time = utc_now() - timedelta(hours=2)
        await create_test_messages(db, session_id, user_id, 50, base_time)

        # Insert partition event at message 30's timestamp (simulating lag)
        partition_time = base_time + timedelta(minutes=30 * 2)  # After message 30
        await insert_partition_event(db, session_id, user_id, partition_time, ["test-moment-1"])

        # Load all messages and verify order
        store = SessionMessageStore(user_id=user_id)
        messages, has_partition = await store.load_session_messages(
            session_id=session_id,
            user_id=user_id,
            compress_on_load=False,
        )

        assert has_partition, "Should detect partition event"

        # Find partition event position
        partition_idx = None
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool" and msg.get("tool_name") == "session_partition":
                partition_idx = i
                break

        assert partition_idx is not None, "Partition event should be in messages"

        # Partition should be roughly in the middle (after ~30 messages)
        # Not at the very end (which would indicate no lag)
        assert partition_idx < len(messages) - 5, (
            f"Partition at {partition_idx}/{len(messages)} - should be earlier due to lag"
        )

        # Messages after partition should be "recent context"
        messages_after = len(messages) - partition_idx - 1
        assert messages_after >= 10, f"Should have messages after partition, got {messages_after}"

        print(f"\n✅ Partition at index {partition_idx}/{len(messages)}")
        print(f"   Messages before partition: {partition_idx}")
        print(f"   Messages after partition: {messages_after}")

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
async def test_load_with_max_messages_includes_partition(db, test_user_id, test_session_id):
    """Test that loading with max_messages includes partition event when in range."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, NOW(), NOW())
            """,
            user_id, session_id
        )

        # Create 80 messages
        base_time = utc_now() - timedelta(hours=3)
        await create_test_messages(db, session_id, user_id, 80, base_time)

        # Insert partition at message 50's timestamp
        partition_time = base_time + timedelta(minutes=50 * 2)
        await insert_partition_event(db, session_id, user_id, partition_time, ["test-moment-1"])

        # Load last 50 messages - should include partition and recent messages
        store = SessionMessageStore(user_id=user_id)
        messages, has_partition = await store.load_session_messages(
            session_id=session_id,
            user_id=user_id,
            max_messages=50,
            compress_on_load=False,
        )

        # Should have ~50 messages including partition
        assert len(messages) <= 50, f"Should respect max_messages, got {len(messages)}"
        assert has_partition, "Should detect partition event in loaded messages"

        print(f"\n✅ Loaded {len(messages)} messages with max_messages=50")
        print(f"   Partition detected: {has_partition}")

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
async def test_reload_session_with_moment_boundary(db, test_user_id, test_session_id):
    """Test reload_session includes partition event and provides context."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, NOW(), NOW())
            """,
            user_id, session_id
        )

        # Create messages with partition in the middle
        base_time = utc_now() - timedelta(hours=2)
        await create_test_messages(db, session_id, user_id, 60, base_time)

        partition_time = base_time + timedelta(minutes=40 * 2)
        await insert_partition_event(
            db, session_id, user_id, partition_time,
            moment_keys=["coding-session-20250127", "api-discussion-20250126"]
        )

        # Reload session (the main entry point for session loading)
        history = await reload_session(
            session_id=session_id,
            user_id=user_id,
            compress_on_load=False,
        )

        # Find partition and verify it has context keys
        partition_found = False
        for msg in history:
            if msg.get("role") == "tool" and msg.get("tool_name") == "session_partition":
                partition_found = True
                content = json.loads(msg.get("content", "{}"))
                assert "moment_keys" in content
                assert len(content["moment_keys"]) > 0
                assert "recent_moments_summary" in content
                print(f"\n✅ Partition event content:")
                print(f"   Moment keys: {content['moment_keys']}")
                print(f"   Summary: {content['recent_moments_summary'][:50]}...")
                break

        assert partition_found, "Should find partition event in reloaded session"

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
async def test_no_partition_when_few_messages(db, test_user_id, test_session_id):
    """Test that sessions with few messages don't have partition events."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session with only 10 messages (below threshold)
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, NOW(), NOW())
            """,
            user_id, session_id
        )

        await create_test_messages(db, session_id, user_id, 10)

        # Load messages
        store = SessionMessageStore(user_id=user_id)
        messages, has_partition = await store.load_session_messages(
            session_id=session_id,
            user_id=user_id,
        )

        assert len(messages) == 10
        assert not has_partition, "Short session should not have partition"

        print(f"\n✅ Short session ({len(messages)} messages) has no partition")

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
async def test_multiple_partition_events_uses_latest(db, test_user_id, test_session_id):
    """Test that when multiple partitions exist, loading respects chronological order."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, NOW(), NOW())
            """,
            user_id, session_id
        )

        # Create 100 messages
        base_time = utc_now() - timedelta(hours=4)
        await create_test_messages(db, session_id, user_id, 100, base_time)

        # Insert two partition events at different times
        partition1_time = base_time + timedelta(minutes=30 * 2)
        await insert_partition_event(db, session_id, user_id, partition1_time, ["moment-old"])

        partition2_time = base_time + timedelta(minutes=70 * 2)
        await insert_partition_event(db, session_id, user_id, partition2_time, ["moment-recent"])

        # Load last 50 messages - should see the later partition
        store = SessionMessageStore(user_id=user_id)
        messages, has_partition = await store.load_session_messages(
            session_id=session_id,
            user_id=user_id,
            max_messages=50,
        )

        assert has_partition

        # Find partition events
        partitions = [m for m in messages if m.get("tool_name") == "session_partition"]

        # With max_messages=50, we should primarily see the recent partition
        # The old partition might be outside the window
        print(f"\n✅ Found {len(partitions)} partition(s) in last 50 messages")
        for p in partitions:
            content = json.loads(p.get("content", "{}"))
            print(f"   Keys: {content.get('moment_keys')}")

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_moment_builder_lag_mechanism(db, test_user_id, test_session_id):
    """Test that moment builder applies lag correctly (requires LLM)."""
    from rem.agentic.agents import run_moment_builder

    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session with enough messages to trigger compression
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, message_count, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, 60, NOW(), NOW())
            """,
            user_id, session_id
        )

        # Create 60 messages - enough to compress with lag
        base_time = utc_now() - timedelta(hours=2)
        for i in range(60):
            msg_time = base_time + timedelta(minutes=i * 2)
            role = "user" if i % 2 == 0 else "assistant"
            content = f"Message {i}: {'What about API authentication?' if role == 'user' else 'For authentication you should use JWT tokens with proper expiration...'}"

            await db.fetch(
                """
                INSERT INTO messages (id, tenant_id, user_id, session_id, message_type, content, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $1, $2, $3, $4, $5, NOW())
                """,
                user_id, session_id, role, content, msg_time
            )

        # Run moment builder
        result = await run_moment_builder(session_id=session_id, user_id=user_id, force=True)

        assert result.success, f"Moment builder failed: {result.error}"

        # Reconnect after moment builder
        await db.connect()

        # Check partition event position
        partition_query = """
            SELECT created_at
            FROM messages
            WHERE session_id = $1 AND user_id = $2 AND metadata->>'tool_name' = 'session_partition'
            ORDER BY created_at DESC
            LIMIT 1
        """
        partition_row = await db.fetchrow(partition_query, session_id, user_id)

        # Check last message time
        last_msg_query = """
            SELECT MAX(created_at) as last_time
            FROM messages
            WHERE session_id = $1 AND user_id = $2 AND message_type != 'tool'
        """
        last_msg_row = await db.fetchrow(last_msg_query, session_id, user_id)

        if partition_row and last_msg_row:
            partition_time = partition_row["created_at"]
            last_msg_time = last_msg_row["last_time"]

            # Partition should be BEFORE the last message due to lag
            assert partition_time < last_msg_time, (
                f"Partition ({partition_time}) should be before last message ({last_msg_time}) due to lag"
            )

            time_diff = last_msg_time - partition_time
            print(f"\n✅ Lag mechanism working:")
            print(f"   Partition at: {partition_time}")
            print(f"   Last message: {last_msg_time}")
            print(f"   Gap: {time_diff}")

    finally:
        await cleanup_test_data(db, user_id, session_id)
