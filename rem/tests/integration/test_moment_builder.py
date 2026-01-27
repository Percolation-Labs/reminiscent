"""Integration tests for the Moment Builder.

Tests the full moment building lifecycle with proper user isolation.

Run with:
    POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5052/rem" \
    pytest tests/integration/test_moment_builder.py -v
"""

import json
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from rem.agentic.agents import MomentBuilder, run_moment_builder
from rem.models.entities import Message, Moment, Session
from rem.services.postgres import get_postgres_service
from rem.services.session import SessionMessageStore
from rem.settings import settings
from rem.utils.date_utils import utc_now


# Mark all tests as requiring database
pytestmark = [
    pytest.mark.db_only,
    pytest.mark.skipif(
        not settings.postgres.enabled,
        reason="Database not enabled (POSTGRES__ENABLED=false)"
    ),
]


# Load sample conversation data
SAMPLE_DATA_PATH = Path(__file__).parent.parent / "data" / "moments" / "sample_conversation.json"


@pytest.fixture
def sample_conversation():
    """Load sample conversation from test data."""
    with open(SAMPLE_DATA_PATH) as f:
        data = json.load(f)
    return data["messages"]


@pytest.fixture
def test_user_id():
    """Generate a unique user ID for test isolation."""
    return str(uuid.uuid4())


@pytest.fixture
def test_session_id():
    """Generate a unique session ID."""
    return f"test-session-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def db():
    """Get database connection."""
    postgres = get_postgres_service()
    await postgres.connect()
    yield postgres
    await postgres.disconnect()


async def cleanup_test_data(db, user_id: str, session_id: str = None):
    """Clean up test data for a user."""
    try:
        if session_id:
            await db.fetch(
                "DELETE FROM messages WHERE session_id = $1 AND user_id = $2",
                session_id, user_id
            )
            await db.fetch(
                "DELETE FROM moments WHERE source_session_id = $1 AND user_id = $2",
                session_id, user_id
            )
            await db.fetch(
                "DELETE FROM sessions WHERE name = $1 AND user_id = $2",
                session_id, user_id
            )
        else:
            await db.fetch("DELETE FROM messages WHERE user_id = $1", user_id)
            await db.fetch("DELETE FROM moments WHERE user_id = $1", user_id)
            await db.fetch("DELETE FROM sessions WHERE user_id = $1", user_id)
    except Exception as e:
        print(f"Cleanup warning: {e}")


@pytest.mark.asyncio
async def test_moment_user_isolation(db, test_user_id):
    """Test that moments are properly isolated by user_id."""
    user1_id = test_user_id
    user2_id = str(uuid.uuid4())
    moment_name = f"isolation-test-{uuid.uuid4().hex[:8]}"

    try:
        # Create a moment for user1 only via direct SQL
        await db.fetch(
            """
            INSERT INTO moments (id, tenant_id, user_id, name, summary, topic_tags,
                                 starts_timestamp, category, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, 'Test moment', ARRAY['test']::text[],
                    NOW(), 'session-compression', NOW(), NOW())
            """,
            user1_id, moment_name
        )

        # Query moments for each user
        user1_moments = await db.fetch(
            "SELECT * FROM moments WHERE user_id = $1 AND name = $2",
            user1_id, moment_name
        )
        user2_moments = await db.fetch(
            "SELECT * FROM moments WHERE user_id = $1 AND name = $2",
            user2_id, moment_name
        )

        # Verify isolation
        assert len(user1_moments) == 1, f"User1 should have 1 moment, got {len(user1_moments)}"
        assert len(user2_moments) == 0, f"User2 should have 0 moments, got {len(user2_moments)}"

        print(f"\n✅ User isolation verified: user1={len(user1_moments)}, user2={len(user2_moments)}")

    finally:
        await cleanup_test_data(db, user1_id)
        await cleanup_test_data(db, user2_id)


@pytest.mark.asyncio
async def test_partition_event_detection(db, test_user_id, test_session_id):
    """Test that load_session_messages detects partition events."""
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

        # Create some messages
        for i, content in enumerate(["Hello", "Hi there", "How are you?"]):
            await db.fetch(
                """
                INSERT INTO messages (id, tenant_id, user_id, session_id, message_type,
                                      content, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $1, $2, $3, $4, NOW() + ($5 || ' minutes')::interval, NOW())
                """,
                user_id, session_id,
                "user" if i % 2 == 0 else "assistant",
                content, str(i)
            )

        # Create a partition event - tool_name stored in metadata JSON
        # Pass content as a string (it's a text column) but metadata as a dict (JSONB column)
        partition_content = json.dumps({
            "partition_type": "moment_compression",
            "moment_keys": ["test-moment-1"],
            "last_n_moment_keys": ["test-moment-1"],
            "recent_moments_summary": "Test summary",
            "messages_compressed": 3,
        })
        # Pass metadata as a Python dict - asyncpg JSONB codec handles encoding
        partition_metadata = {"tool_name": "session_partition"}

        await db.fetch(
            """
            INSERT INTO messages (id, tenant_id, user_id, session_id, message_type,
                                  content, metadata, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, 'tool', $3, $4, NOW() + '10 minutes'::interval, NOW())
            """,
            user_id, session_id, partition_content, partition_metadata
        )

        # Load messages and check for partition event
        store = SessionMessageStore(user_id=user_id)
        messages, has_partition = await store.load_session_messages(
            session_id=session_id,
            user_id=user_id,
        )

        assert has_partition, "Should detect partition event"
        assert len(messages) >= 3, f"Should have messages, got {len(messages)}"

        print(f"\n✅ Partition detection works: has_partition={has_partition}, messages={len(messages)}")

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
async def test_moment_api_list_endpoint(db, test_user_id):
    """Test the moments list API endpoint."""
    from fastapi.testclient import TestClient
    from rem.api.main import app

    user_id = test_user_id
    moment_name = f"api-test-{uuid.uuid4().hex[:8]}"

    try:
        # Create test moment directly
        await db.fetch(
            """
            INSERT INTO moments (id, tenant_id, user_id, name, summary, topic_tags,
                                 emotion_tags, starts_timestamp, category, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, 'API test moment',
                    ARRAY['api', 'test']::text[], ARRAY['focused']::text[],
                    NOW(), 'session-compression', NOW(), NOW())
            """,
            user_id, moment_name
        )

        # Test list endpoint
        client = TestClient(app)
        response = client.get(
            "/api/v1/moments/1",
            headers={"X-User-Id": user_id}
        )

        # Should return 200
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.json()
        assert "moments" in data
        assert "page" in data
        assert "total_moments" in data

        print(f"\n✅ Moments list API works: {data['total_moments']} total moments")

    finally:
        await cleanup_test_data(db, user_id)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_moment_builder_creates_moments(db, test_user_id, test_session_id, sample_conversation):
    """Test that moment builder creates moments from conversation (requires LLM)."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, message_count,
                                  created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, $3, NOW(), NOW())
            """,
            user_id, session_id, len(sample_conversation)
        )

        # Create messages from sample conversation
        base_time = utc_now() - timedelta(hours=2)
        for i, msg in enumerate(sample_conversation):
            msg_time = base_time + timedelta(minutes=i * 5)
            await db.fetch(
                """
                INSERT INTO messages (id, tenant_id, user_id, session_id, message_type,
                                      content, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $1, $2, $3, $4, $5, NOW())
                """,
                user_id, session_id, msg["role"], msg["content"], msg_time
            )

        # Run moment builder
        result = await run_moment_builder(
            session_id=session_id,
            user_id=user_id,
            force=True,
        )

        # Verify success
        assert result.success, f"Moment builder failed: {result.error}"
        assert result.moments_created > 0, "No moments were created"

        # Reconnect db (moment builder disconnects the singleton)
        await db.connect()

        # Query created moments
        moments = await db.fetch(
            """
            SELECT name, summary, topic_tags, emotion_tags,
                   starts_timestamp, ends_timestamp, source_session_id,
                   previous_moment_keys, category
            FROM moments
            WHERE source_session_id = $1 AND user_id = $2
            ORDER BY starts_timestamp ASC
            """,
            session_id, user_id
        )

        assert len(moments) > 0, "No moments found in database"
        assert len(moments) == result.moments_created

        # Verify moment structure
        for moment in moments:
            assert moment["name"] is not None, "Moment name is required"
            assert moment["summary"] is not None, "Moment summary is required"
            assert moment["source_session_id"] == session_id
            assert moment["category"] == "session-compression"

        print(f"\n✅ Created {len(moments)} moments:")
        for m in moments:
            print(f"  - {m['name']}: {m['summary'][:80]}...")
            print(f"    Topics: {m['topic_tags']}")

    finally:
        await cleanup_test_data(db, user_id, session_id)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_moment_builder_inserts_partition_event(db, test_user_id, test_session_id, sample_conversation):
    """Test that moment builder inserts partition event (requires LLM)."""
    user_id = test_user_id
    session_id = test_session_id

    try:
        # Create session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, message_count,
                                  created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, $3, NOW(), NOW())
            """,
            user_id, session_id, len(sample_conversation)
        )

        # Create messages
        base_time = utc_now() - timedelta(hours=2)
        for i, msg in enumerate(sample_conversation[:4]):  # Just first 4 messages
            msg_time = base_time + timedelta(minutes=i * 5)
            await db.fetch(
                """
                INSERT INTO messages (id, tenant_id, user_id, session_id, message_type,
                                      content, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $1, $2, $3, $4, $5, NOW())
                """,
                user_id, session_id, msg["role"], msg["content"], msg_time
            )

        # Run moment builder
        result = await run_moment_builder(
            session_id=session_id,
            user_id=user_id,
            force=True,
        )

        assert result.success, f"Moment builder failed: {result.error}"
        assert result.partition_event_inserted, "Partition event was not inserted"

        # Reconnect db (moment builder disconnects the singleton)
        await db.connect()

        # Query partition event - tool_name is in metadata column
        partition_events = await db.fetch(
            """
            SELECT content, metadata
            FROM messages
            WHERE session_id = $1 AND user_id = $2 AND metadata->>'tool_name' = 'session_partition'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            session_id, user_id
        )

        assert len(partition_events) == 1, "Partition event not found"

        content = json.loads(partition_events[0]["content"])

        # Verify partition event structure
        assert content["partition_type"] == "moment_compression"
        assert "moment_keys" in content
        assert "last_n_moment_keys" in content
        assert "recent_moments_summary" in content
        assert content["messages_compressed"] > 0

        print(f"\n✅ Partition event created:")
        print(f"  Moment keys: {content['moment_keys']}")
        print(f"  Recent summary: {content['recent_moments_summary'][:100]}...")

    finally:
        await cleanup_test_data(db, user_id, session_id)
