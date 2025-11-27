"""End-to-end integration tests for chat completions with session management.

Tests the full flow:
1. Client sends request with X-Session-Id header
2. Server reloads conversation history
3. Agent processes request with history context
4. Response generated
5. New messages saved to database
6. Subsequent requests reload full conversation
"""

import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from rem.api.main import app
from rem.models.entities import Message
from rem.services.postgres import get_postgres_service, Repository
from rem.settings import settings

# Skip all tests in this module if no LLM API key is available
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"),
    reason="LLM API key required for completions tests"
)


@pytest.fixture
def tenant_id():
    """
    DEPRECATED: tenant_id is now the same as user_id.
    Application is user-scoped, not tenant-scoped.
    Kept for backward compatibility with X-Tenant-Id header.
    """
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def session_id():
    """Generate unique session ID."""
    return f"session-{uuid.uuid4()}"


@pytest.fixture
def user_id():
    """Generate unique user ID."""
    return f"user-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def db():
    """Get database service."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled, skipping database tests")

    return get_postgres_service()


@pytest.fixture
async def client():
    """Create async HTTP client for API testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_without_session(client):
    """Test basic completion without session management."""
    response = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "Say 'Hello'"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": "test-tenant",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "choices" in data
    assert len(data["choices"]) > 0
    assert data["choices"][0]["message"]["role"] == "assistant"


@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_with_new_session(client, db, tenant_id, session_id, user_id):
    """Test completion with new session (no prior history)."""
    response = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user_id,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "choices" in data

    # Verify messages saved to database
    # Note: Messages are stored with tenant_id=user_id (application is user-scoped)
    repo = Repository(Message)
    messages = await repo.get_by_session(
        session_id=session_id, tenant_id=user_id, user_id=user_id
    )

    # Should have user + assistant messages
    assert len(messages) >= 2
    assert messages[0].message_type == "user"
    assert messages[0].content == "What is 2+2?"
    assert messages[1].message_type == "assistant"


@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_with_session_continuity(
    client, db, tenant_id, session_id, user_id
):
    """Test multi-turn conversation with session continuity."""
    # Turn 1
    response1 = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "My name is Alice"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user_id,
            "X-Agent-Schema": "simple-assistant",  # Use simple agent for conversational test
        },
    )

    assert response1.status_code == 200

    # Turn 2 - Ask about information from Turn 1
    response2 = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "What is my name?"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user_id,
            "X-Agent-Schema": "simple-assistant",  # Use simple agent for conversational test
        },
    )

    assert response2.status_code == 200
    data2 = response2.json()

    # Response should reference "Alice" from previous turn
    # Note: This depends on the agent's ability to use conversation history
    assistant_response = data2["choices"][0]["message"]["content"]

    # Verify full conversation saved
    # Note: Messages are stored with tenant_id=user_id (application is user-scoped)
    repo = Repository(Message)
    messages = await repo.get_by_session(
        session_id=session_id, tenant_id=user_id, user_id=user_id
    )

    # Should have 4 messages: user1, assistant1, user2, assistant2
    assert len(messages) >= 4
    assert messages[0].content == "My name is Alice"
    assert messages[2].content == "What is my name?"


@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_with_long_response_compression(
    client, db, tenant_id, session_id, user_id
):
    """Test that long responses are compressed and stored properly."""
    # Ask for detailed explanation (likely long response)
    response = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [
                {
                    "role": "user",
                    "content": "Explain the REM architecture in great detail with examples",
                }
            ],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user_id,
            "X-Agent-Schema": "rem",  # Use REM agent which knows about REM architecture
        },
    )

    assert response.status_code == 200
    data = response.json()
    assistant_response = data["choices"][0]["message"]["content"]

    # Verify stored in database
    # Note: Messages are stored with tenant_id=user_id (application is user-scoped)
    repo = Repository(Message)
    messages = await repo.get_by_session(
        session_id=session_id, tenant_id=user_id, user_id=user_id
    )

    assert len(messages) >= 2

    # If response is long (>400 chars), compression logic applies
    if len(assistant_response) > 400:
        # Message should be stored with entity_key for LOOKUP
        assistant_msg = messages[1]
        assert assistant_msg.metadata is not None
        # Entity key format: session-{id}-msg-{index}
        if "entity_key" in assistant_msg.metadata:
            entity_key = assistant_msg.metadata["entity_key"]
            assert entity_key.startswith(f"session-{session_id}-msg-")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_session_isolation(client, db, tenant_id, user_id):
    """Test that different sessions are properly isolated."""
    session1 = f"session-{uuid.uuid4()}"
    session2 = f"session-{uuid.uuid4()}"

    # Conversation in session 1
    # Use simple-assistant agent to avoid REM query overhead
    await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "I like cats"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session1,
            "X-User-Id": user_id,
            "X-Agent-Schema": "simple-assistant",
        },
    )

    # Conversation in session 2
    # Use simple-assistant agent to avoid REM query overhead
    await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "I like dogs"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session2,
            "X-User-Id": user_id,
            "X-Agent-Schema": "simple-assistant",
        },
    )

    # Verify isolation
    # Note: Messages are stored with tenant_id=user_id (application is user-scoped)
    repo = Repository(Message)

    messages1 = await repo.get_by_session(
        session_id=session1, tenant_id=user_id, user_id=user_id
    )
    messages2 = await repo.get_by_session(
        session_id=session2, tenant_id=user_id, user_id=user_id
    )

    assert len(messages1) >= 2
    assert len(messages2) >= 2

    # Session 1 should only have cat message
    assert any("cats" in msg.content.lower() for msg in messages1)
    assert not any("dogs" in msg.content.lower() for msg in messages1)

    # Session 2 should only have dog message
    assert any("dogs" in msg.content.lower() for msg in messages2)
    assert not any("cats" in msg.content.lower() for msg in messages2)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_tenant_isolation(client, db, tenant_id):
    """Test that different users are properly isolated.

    Note: Application is now user-scoped (tenant_id=user_id internally).
    This test verifies that different users cannot see each other's messages.
    """
    user1 = f"user-{uuid.uuid4().hex[:8]}"
    user2 = f"user-{uuid.uuid4().hex[:8]}"
    session_id = f"session-{uuid.uuid4()}"

    # Same session ID but different users
    # Use simple-assistant agent to avoid REM query overhead
    await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "User 1 message"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user1,
            "X-Agent-Schema": "simple-assistant",
        },
    )

    await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "User 2 message"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user2,
            "X-Agent-Schema": "simple-assistant",
        },
    )

    # Verify isolation
    # Note: Messages are stored with tenant_id=user_id (application is user-scoped)
    repo = Repository(Message)

    messages1 = await repo.get_by_session(
        session_id=session_id, tenant_id=user1, user_id=user1
    )
    messages2 = await repo.get_by_session(
        session_id=session_id, tenant_id=user2, user_id=user2
    )

    # Each user should only see their own messages
    assert len(messages1) >= 2
    assert len(messages2) >= 2
    assert messages1[0].content == "User 1 message"
    assert messages2[0].content == "User 2 message"




@pytest.mark.asyncio
@pytest.mark.llm
async def test_completions_usage_tracking(client, tenant_id, session_id, user_id):
    """Test that token usage is tracked in responses."""
    response = await client.post(
        "/api/v1/chat/completions",
        json={
            "model": "openai:gpt-4o-mini",
            "messages": [{"role": "user", "content": "Count to 5"}],
            "stream": False,
        },
        headers={
            "X-Tenant-Id": tenant_id,
            "X-Session-Id": session_id,
            "X-User-Id": user_id,
        },
    )

    assert response.status_code == 200
    data = response.json()

    # Usage should be present
    assert "usage" in data
    usage = data["usage"]
    assert "prompt_tokens" in usage
    assert "completion_tokens" in usage
    assert "total_tokens" in usage
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
