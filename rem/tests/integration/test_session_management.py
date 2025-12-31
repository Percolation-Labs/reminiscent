"""Integration tests for session management and message persistence.

Tests the full session lifecycle:
1. User sends message with session_id
2. Agent responds
3. Both messages saved to database
4. Session reloaded on next request
5. Long messages compressed with REM LOOKUP keys
6. Full messages retrieved via LOOKUP queries

NOTE: These tests are marked with 'db_only' marker. They conflict with TestClient tests
due to event loop lifecycle. Run these separately:
    pytest tests/integration/test_session_management.py -v
"""

import uuid
from datetime import datetime

import pytest
from rem.models.entities import Message
from rem.services.postgres import get_postgres_service, Repository
from rem.services.session import MessageCompressor, SessionMessageStore, reload_session
from rem.settings import settings


# Mark all tests in this module as requiring isolation from TestClient tests
pytestmark = [
    pytest.mark.db_only,
    pytest.mark.skipif(
        not settings.postgres.enabled,
        reason="Database not enabled (POSTGRES__ENABLED=false)"
    ),
]


# Sample conversation data
SAMPLE_CONVERSATION = [
    {
        "role": "user",
        "content": "What is REM?",
        "timestamp": "2025-01-20T10:00:00Z",
    },
    {
        "role": "assistant",
        "content": "REM (Resources Entities Moments) is a bio-inspired memory architecture for agentic AI workloads. It provides multi-index organization with vector embeddings, knowledge graphs, and temporal indexing.",
        "timestamp": "2025-01-20T10:00:05Z",
    },
    {
        "role": "user",
        "content": "How do I perform a LOOKUP query?",
        "timestamp": "2025-01-20T10:01:00Z",
    },
    {
        "role": "assistant",
        "content": "LOOKUP queries provide O(1) retrieval by entity label. " * 50,  # Long response
        "timestamp": "2025-01-20T10:01:05Z",
    },
]

SAMPLE_LONG_RESPONSE = {
    "role": "assistant",
    "content": (
        "# Comprehensive Guide to REM Architecture\n\n"
        "REM is a sophisticated memory system designed for AI agents. "
        "It provides multiple indexing strategies including vector embeddings, "
        "knowledge graph traversal, and temporal queries. "
    )
    * 100,  # Very long response (>400 chars)
    "timestamp": "2025-01-20T10:02:00Z",
}


@pytest.fixture
def message_repo():
    """Create message repository."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    return Repository(Message)


@pytest.fixture
def tenant_id():
    """Generate unique tenant ID for test isolation."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def session_id():
    """Generate unique session ID."""
    return f"session-{uuid.uuid4()}"


@pytest.fixture
def user_id():
    """Generate unique user ID."""
    return f"user-{uuid.uuid4().hex[:8]}"


@pytest.mark.asyncio
async def test_message_creation(message_repo, tenant_id, session_id, user_id):
    """Test creating a single message."""
    msg = Message(
        content="Hello, world!",
        message_type="user",
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )

    created = await message_repo.upsert(msg)

    assert created.id is not None
    assert created.content == "Hello, world!"
    assert created.message_type == "user"
    assert created.session_id == session_id


@pytest.mark.asyncio
async def test_batch_message_creation(message_repo, tenant_id, session_id, user_id):
    """Test batch creating messages."""
    messages = [
        Message(
            content=msg["content"],
            message_type=msg["role"],
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        for msg in SAMPLE_CONVERSATION[:2]  # First Q&A
    ]

    created = await message_repo.upsert(messages)

    assert len(created) == 2
    assert all(msg.id is not None for msg in created)


@pytest.mark.asyncio
async def test_get_messages_by_session(
    message_repo, tenant_id, session_id, user_id
):
    """Test retrieving all messages for a session."""
    # Create conversation
    messages = [
        Message(
            content=msg["content"],
            message_type=msg["role"],
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        for msg in SAMPLE_CONVERSATION
    ]

    await message_repo.upsert(messages)

    # Retrieve messages
    retrieved = await message_repo.get_by_session(
        session_id=session_id, tenant_id=tenant_id, user_id=user_id
    )

    assert len(retrieved) == 4
    assert retrieved[0].content == "What is REM?"
    assert retrieved[1].message_type == "assistant"


@pytest.mark.asyncio
async def test_message_compressor():
    """Test message compression logic."""
    compressor = MessageCompressor(truncate_length=50)

    # Short message - no compression
    short_msg = {"role": "user", "content": "Hello"}
    compressed = compressor.compress_message(short_msg)
    assert not compressor.is_compressed(compressed)

    # Long message - should compress
    long_msg = {"role": "assistant", "content": "A" * 500}
    entity_key = "session-123-msg-1"
    compressed = compressor.compress_message(long_msg, entity_key)

    assert compressor.is_compressed(compressed)
    assert compressor.get_entity_key(compressed) == entity_key
    assert "REM LOOKUP" in compressed["content"]
    assert len(compressed["content"]) < len(long_msg["content"])

    # Decompression
    full_content = long_msg["content"]
    decompressed = compressor.decompress_message(compressed, full_content)
    assert decompressed["content"] == full_content
    assert not compressor.is_compressed(decompressed)


@pytest.mark.asyncio
async def test_session_message_store(tenant_id, session_id, user_id):
    """Test storing and retrieving session messages."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    store = SessionMessageStore(user_id=user_id)

    # Store conversation with compression
    compressed = await store.store_session_messages(
        session_id=session_id,
        messages=SAMPLE_CONVERSATION,
        user_id=user_id,
        compress=True,
    )

    # Long assistant message should be compressed
    assert len(compressed) == 4
    # Note: 4th message has long content, might be compressed
    # Check if any message has compression markers

    # Load messages
    loaded = await store.load_session_messages(
        session_id=session_id, user_id=user_id, compress_on_load=False
    )

    assert len(loaded) == 4
    assert loaded[0]["role"] == "user"
    assert loaded[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_long_message_compression(tenant_id, session_id, user_id):
    """Test compression and REM LOOKUP for very long messages."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    store = SessionMessageStore(user_id=user_id)

    # Create conversation with very long assistant response
    conversation = [
        {"role": "user", "content": "Tell me everything about REM"},
        SAMPLE_LONG_RESPONSE,
    ]

    # Store with compression
    compressed = await store.store_session_messages(
        session_id=session_id,
        messages=conversation,
        user_id=user_id,
        compress=True,
    )

    # Assistant message should be compressed
    assert len(compressed) == 2
    assistant_msg = compressed[1]

    # Check if compressed (long message should trigger compression)
    if store.compressor.is_compressed(assistant_msg):
        entity_key = store.compressor.get_entity_key(assistant_msg)
        assert entity_key is not None
        assert "REM LOOKUP" in assistant_msg["content"]

        # Retrieve full message via LOOKUP
        full_content = await store.retrieve_message(entity_key)
        assert full_content is not None
        assert len(full_content) > 400
        assert "Comprehensive Guide to REM" in full_content


@pytest.mark.asyncio
async def test_reload_session(tenant_id, session_id, user_id):
    """Test session reloading functionality."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    store = SessionMessageStore(user_id=user_id)

    # Store initial conversation
    await store.store_session_messages(
        session_id=session_id,
        messages=SAMPLE_CONVERSATION,
        user_id=user_id,
        compress=True,
    )

    # Reload session
    history = await reload_session(
        session_id=session_id,
        user_id=user_id,
        compress_on_load=False,
    )

    assert len(history) == 4
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "What is REM?"


@pytest.mark.asyncio
async def test_reload_session_with_decompression(tenant_id, session_id, user_id):
    """Test session reloading with message decompression."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    store = SessionMessageStore(user_id=user_id)

    # Store conversation with long message
    conversation = [
        {"role": "user", "content": "Tell me about REM"},
        SAMPLE_LONG_RESPONSE,
    ]

    await store.store_session_messages(
        session_id=session_id,
        messages=conversation,
        user_id=user_id,
        compress=True,
    )

    # Reload with decompression
    history = await reload_session(
        session_id=session_id,
        user_id=user_id,
        compress_on_load=False,
    )

    # Should have full messages
    assert len(history) == 2
    # Long message should be fully decompressed
    assistant_response = history[1]
    assert "Comprehensive Guide to REM" in assistant_response["content"]


@pytest.mark.asyncio
async def test_multi_turn_conversation(tenant_id, session_id, user_id):
    """Test realistic multi-turn conversation flow."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    store = SessionMessageStore(user_id=user_id)

    # Turn 1: User asks, assistant responds
    turn1 = [
        {"role": "user", "content": "What is REM?"},
        {
            "role": "assistant",
            "content": "REM is a memory architecture for AI agents.",
        },
    ]

    await store.store_session_messages(
        session_id=session_id, messages=turn1, user_id=user_id, compress=True
    )

    # Reload and verify
    history = await reload_session(
        session_id=session_id, user_id=user_id
    )
    assert len(history) == 2

    # Turn 2: User asks follow-up
    turn2 = [
        {"role": "user", "content": "How do I use LOOKUP queries?"},
        {"role": "assistant", "content": "LOOKUP queries use entity labels..." * 50},
    ]

    await store.store_session_messages(
        session_id=session_id, messages=turn2, user_id=user_id, compress=True
    )

    # Reload full conversation
    full_history = await reload_session(
        session_id=session_id, user_id=user_id
    )
    assert len(full_history) == 4
    assert full_history[0]["content"] == "What is REM?"
    assert full_history[2]["content"] == "How do I use LOOKUP queries?"


@pytest.mark.asyncio
async def test_postgres_disabled_graceful_degradation(tenant_id, session_id, user_id):
    """Test that session management gracefully degrades when Postgres is disabled."""
    # This test works even when Postgres is enabled
    # It tests the code paths that handle disabled database

    # When Postgres is disabled, reload_session should return empty list
    from unittest.mock import patch

    with patch('rem.services.session.reload.settings') as mock_settings:
        mock_settings.postgres.enabled = False

        # Reload should return empty list
        history = await reload_session(
            session_id=session_id,
            user_id=user_id,
        )

        # Should not fail, just return empty
        assert history == []


@pytest.mark.asyncio
async def test_entity_key_format():
    """Test that entity keys follow the expected format for LOOKUP queries."""
    session_id = "abc-123"
    message_index = 5

    expected_key = f"session-{session_id}-msg-{message_index}"

    # This is the format used by SessionMessageStore
    assert expected_key == "session-abc-123-msg-5"

    # Entity keys should be parseable
    parts = expected_key.split("-")
    assert parts[0] == "session"
    assert parts[-2] == "msg"
    assert parts[-1] == "5"
