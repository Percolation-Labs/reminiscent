"""
Integration tests for SharedSessions workflow.

Tests the complete session sharing lifecycle:
1. Create test users with messages in multiple sessions
2. Share sessions between users via API endpoints
3. Verify aggregate views (who is sharing with me)
4. Test getting shared messages
5. Revoke shares and verify state updates
6. Test SQL functions directly

This test creates test data and cleans up shared_sessions at the beginning.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from rem.api.deps import require_auth
from rem.api.main import create_app
from rem.models.entities import Message, User
from rem.services.postgres import PostgresService, Repository
from rem.settings import settings


# =============================================================================
# Test Configuration
# =============================================================================

TENANT_ID = "test-shared-sessions"

# Test users
TEST_USERS = [
    {"id": "user-alice", "name": "Alice Johnson", "email": "alice@example.com"},
    {"id": "user-bob", "name": "Bob Smith", "email": "bob@example.com"},
    {"id": "user-charlie", "name": "Charlie Brown", "email": "charlie@example.com"},
]

# Sample messages for each user's sessions
ALICE_SESSIONS = {
    "alice-session-1": [
        {"role": "user", "content": "Hello, what's the weather like?"},
        {"role": "assistant", "content": "It's sunny and 72F today!"},
        {"role": "user", "content": "Great, thanks!"},
    ],
    "alice-session-2": [
        {"role": "user", "content": "Can you help me with Python?"},
        {"role": "assistant", "content": "Of course! What do you need help with?"},
        {"role": "user", "content": "How do I read a file?"},
        {"role": "assistant", "content": "Use open('file.txt', 'r') and read() method."},
    ],
}

BOB_SESSIONS = {
    "bob-session-1": [
        {"role": "user", "content": "What is REM?"},
        {"role": "assistant", "content": "REM is a bio-inspired memory system for AI agents."},
    ],
    "bob-session-2": [
        {"role": "user", "content": "How do LOOKUP queries work?"},
        {"role": "assistant", "content": "LOOKUP queries provide O(1) retrieval by entity key."},
        {"role": "user", "content": "That's fast!"},
    ],
    "bob-session-3": [
        {"role": "user", "content": "Tell me about graph traversal"},
        {"role": "assistant", "content": "TRAVERSE queries walk the knowledge graph."},
    ],
}

CHARLIE_SESSIONS = {
    "charlie-session-1": [
        {"role": "user", "content": "What time is it?"},
        {"role": "assistant", "content": "I don't have access to the current time."},
    ],
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def postgres_service():
    """Create connected PostgresService instance."""
    if not settings.postgres.enabled:
        pytest.skip("Postgres is disabled")

    pg = PostgresService()
    await pg.connect()
    yield pg
    await pg.disconnect()


@pytest.fixture
async def clean_shared_sessions(postgres_service):
    """Clean up shared_sessions table before test."""
    await postgres_service.fetch(
        "DELETE FROM shared_sessions WHERE tenant_id = $1",
        TENANT_ID,
    )
    yield
    # Cleanup after test as well
    await postgres_service.fetch(
        "DELETE FROM shared_sessions WHERE tenant_id = $1",
        TENANT_ID,
    )


@pytest.fixture
async def setup_test_users(postgres_service):
    """Create test users in the database."""
    user_repo = Repository(User, table_name="users")

    created_users = []
    for user_data in TEST_USERS:
        user = User(
            name=user_data["name"],
            email=user_data["email"],
            user_id=user_data["id"],
            tenant_id=TENANT_ID,
        )
        result = await user_repo.upsert(user)
        created_users.append(result)

    yield created_users

    # Cleanup - delete test users
    for user in created_users:
        if user.id:
            await postgres_service.fetch(
                "DELETE FROM users WHERE id = $1",
                user.id,
            )


@pytest.fixture
async def setup_test_messages(postgres_service, setup_test_users):
    """Create test messages for all users."""
    message_repo = Repository(Message, table_name="messages")

    all_messages = []

    # Alice's messages
    for session_id, messages in ALICE_SESSIONS.items():
        for msg in messages:
            message = Message(
                content=msg["content"],
                message_type=msg["role"],
                session_id=session_id,
                user_id="user-alice",
                tenant_id=TENANT_ID,
            )
            result = await message_repo.upsert(message)
            all_messages.append(result)

    # Bob's messages
    for session_id, messages in BOB_SESSIONS.items():
        for msg in messages:
            message = Message(
                content=msg["content"],
                message_type=msg["role"],
                session_id=session_id,
                user_id="user-bob",
                tenant_id=TENANT_ID,
            )
            result = await message_repo.upsert(message)
            all_messages.append(result)

    # Charlie's messages
    for session_id, messages in CHARLIE_SESSIONS.items():
        for msg in messages:
            message = Message(
                content=msg["content"],
                message_type=msg["role"],
                session_id=session_id,
                user_id="user-charlie",
                tenant_id=TENANT_ID,
            )
            result = await message_repo.upsert(message)
            all_messages.append(result)

    yield all_messages

    # Cleanup - delete test messages
    await postgres_service.fetch(
        "DELETE FROM messages WHERE tenant_id = $1",
        TENANT_ID,
    )


# Global variable to hold the current test user
_current_test_user: dict | None = None


def get_mock_user():
    """Return the current test user for dependency injection."""
    if _current_test_user is None:
        raise ValueError("Test user not set - call set_test_user first")
    return _current_test_user


def set_test_user(user_id: str):
    """Set the current test user."""
    global _current_test_user
    _current_test_user = {
        "id": user_id,
        "email": f"{user_id}@test.com",
        "roles": ["user"],
    }


@pytest.fixture
async def app():
    """Create test application with mocked auth."""
    app = create_app()
    # Override require_auth to return our mock user
    app.dependency_overrides[require_auth] = get_mock_user
    yield app
    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    """Create async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def auth_headers(user_id: str) -> dict:
    """Set test user and return headers."""
    set_test_user(user_id)
    return {
        "X-User-Id": user_id,
        "X-Tenant-Id": TENANT_ID,
    }


# =============================================================================
# SQL Function Tests
# =============================================================================


@pytest.mark.asyncio
async def test_sql_functions_empty_state(postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test SQL functions with no shares."""
    # Count should be 0
    result = await postgres_service.fetchrow(
        "SELECT fn_count_shared_with_me($1, $2) as count",
        TENANT_ID,
        "user-alice",
    )
    assert result["count"] == 0

    # Get shared should return empty
    rows = await postgres_service.fetch(
        "SELECT * FROM fn_get_shared_with_me($1, $2, $3, $4)",
        TENANT_ID,
        "user-alice",
        50,
        0,
    )
    assert len(rows) == 0


@pytest.mark.asyncio
async def test_sql_functions_with_shares(postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test SQL functions after creating shares."""
    # Alice shares her sessions with Bob
    for session_id in ALICE_SESSIONS.keys():
        await postgres_service.fetch(
            """
            INSERT INTO shared_sessions (session_id, owner_user_id, shared_with_user_id, tenant_id)
            VALUES ($1, $2, $3, $4)
            """,
            session_id,
            "user-alice",
            "user-bob",
            TENANT_ID,
        )

    # Bob should now see Alice sharing with him
    result = await postgres_service.fetchrow(
        "SELECT fn_count_shared_with_me($1, $2) as count",
        TENANT_ID,
        "user-bob",
    )
    assert result["count"] == 1  # One user (Alice) sharing

    # Get the aggregate
    rows = await postgres_service.fetch(
        "SELECT * FROM fn_get_shared_with_me($1, $2, $3, $4)",
        TENANT_ID,
        "user-bob",
        50,
        0,
    )
    assert len(rows) == 1

    alice_summary = rows[0]
    assert alice_summary["user_id"] == "user-alice"
    assert alice_summary["name"] == "Alice Johnson"
    assert alice_summary["email"] == "alice@example.com"
    assert alice_summary["session_count"] == 2  # 2 sessions
    # Total messages across Alice's sessions = 3 + 4 = 7
    assert alice_summary["message_count"] == 7


@pytest.mark.asyncio
async def test_sql_get_shared_messages(postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test getting messages from shared sessions."""
    # Bob shares his sessions with Alice
    for session_id in BOB_SESSIONS.keys():
        await postgres_service.fetch(
            """
            INSERT INTO shared_sessions (session_id, owner_user_id, shared_with_user_id, tenant_id)
            VALUES ($1, $2, $3, $4)
            """,
            session_id,
            "user-bob",
            "user-alice",
            TENANT_ID,
        )

    # Get messages shared by Bob with Alice
    rows = await postgres_service.fetch(
        "SELECT * FROM fn_get_shared_messages($1, $2, $3, $4, $5)",
        TENANT_ID,
        "user-alice",  # recipient
        "user-bob",     # owner
        50,
        0,
    )

    # Bob has 2 + 3 + 2 = 7 messages across 3 sessions
    assert len(rows) == 7

    # Count should match
    count_result = await postgres_service.fetchrow(
        "SELECT fn_count_shared_messages($1, $2, $3) as count",
        TENANT_ID,
        "user-alice",
        "user-bob",
    )
    assert count_result["count"] == 7


@pytest.mark.asyncio
async def test_sql_soft_delete(postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test that soft-deleted shares are excluded."""
    # Alice shares with Bob
    await postgres_service.fetch(
        """
        INSERT INTO shared_sessions (session_id, owner_user_id, shared_with_user_id, tenant_id)
        VALUES ($1, $2, $3, $4)
        """,
        "alice-session-1",
        "user-alice",
        "user-bob",
        TENANT_ID,
    )

    # Verify share exists
    result = await postgres_service.fetchrow(
        "SELECT fn_count_shared_with_me($1, $2) as count",
        TENANT_ID,
        "user-bob",
    )
    assert result["count"] == 1

    # Soft delete the share
    await postgres_service.fetch(
        """
        UPDATE shared_sessions
        SET deleted_at = NOW()
        WHERE session_id = $1 AND owner_user_id = $2 AND shared_with_user_id = $3 AND tenant_id = $4
        """,
        "alice-session-1",
        "user-alice",
        "user-bob",
        TENANT_ID,
    )

    # Share should no longer be visible
    result = await postgres_service.fetchrow(
        "SELECT fn_count_shared_with_me($1, $2) as count",
        TENANT_ID,
        "user-bob",
    )
    assert result["count"] == 0


# =============================================================================
# API Endpoint Tests
# =============================================================================


@pytest.mark.asyncio
async def test_share_session_endpoint(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test POST /api/v1/sessions/{session_id}/share endpoint."""
    # Alice shares her session with Bob
    response = await client.post(
        "/api/v1/sessions/alice-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["share"]["session_id"] == "alice-session-1"
    assert data["share"]["owner_user_id"] == "user-alice"
    assert data["share"]["shared_with_user_id"] == "user-bob"
    assert data["share"]["deleted_at"] is None


@pytest.mark.asyncio
async def test_share_session_duplicate_fails(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test that sharing the same session twice fails."""
    # First share
    response = await client.post(
        "/api/v1/sessions/alice-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 201

    # Duplicate share should fail
    response = await client.post(
        "/api/v1/sessions/alice-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 400
    assert "already shared" in response.json()["detail"]


@pytest.mark.asyncio
async def test_remove_session_share_endpoint(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test DELETE /api/v1/sessions/{session_id}/share/{user_id} endpoint."""
    # First share
    await client.post(
        "/api/v1/sessions/alice-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )

    # Remove share
    response = await client.delete(
        "/api/v1/sessions/alice-session-1/share/user-bob",
        headers=auth_headers("user-alice"),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True

    # Verify soft delete (record still exists but has deleted_at)
    result = await postgres_service.fetchrow(
        """
        SELECT deleted_at FROM shared_sessions
        WHERE session_id = $1 AND owner_user_id = $2 AND shared_with_user_id = $3 AND tenant_id = $4
        """,
        "alice-session-1",
        "user-alice",
        "user-bob",
        TENANT_ID,
    )
    assert result is not None
    assert result["deleted_at"] is not None


@pytest.mark.asyncio
async def test_remove_nonexistent_share_fails(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test removing a share that doesn't exist."""
    response = await client.delete(
        "/api/v1/sessions/nonexistent-session/share/user-bob",
        headers=auth_headers("user-alice"),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_shared_with_me_endpoint(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test GET /api/v1/shared-with-me endpoint."""
    # Alice shares 2 sessions with Bob
    for session_id in ALICE_SESSIONS.keys():
        await client.post(
            f"/api/v1/sessions/{session_id}/share",
            json={"shared_with_user_id": "user-bob"},
            headers=auth_headers("user-alice"),
        )

    # Charlie shares 1 session with Bob (but not Alice)
    await client.post(
        "/api/v1/sessions/charlie-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-charlie"),
    )

    # Bob checks who is sharing with him
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["object"] == "list"
    assert len(data["data"]) == 2  # Alice and Charlie

    # Verify pagination metadata
    assert data["metadata"]["total"] == 2
    assert data["metadata"]["page"] == 1

    # Find Alice's entry
    alice_entry = next((d for d in data["data"] if d["user_id"] == "user-alice"), None)
    assert alice_entry is not None
    assert alice_entry["name"] == "Alice Johnson"
    assert alice_entry["session_count"] == 2
    assert alice_entry["message_count"] == 7  # 3 + 4

    # Find Charlie's entry
    charlie_entry = next((d for d in data["data"] if d["user_id"] == "user-charlie"), None)
    assert charlie_entry is not None
    assert charlie_entry["session_count"] == 1
    assert charlie_entry["message_count"] == 2


@pytest.mark.asyncio
async def test_get_shared_with_me_pagination(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test pagination for shared-with-me endpoint."""
    # Alice and Bob both share with Charlie
    for session_id in ALICE_SESSIONS.keys():
        await client.post(
            f"/api/v1/sessions/{session_id}/share",
            json={"shared_with_user_id": "user-charlie"},
            headers=auth_headers("user-alice"),
        )

    for session_id in BOB_SESSIONS.keys():
        await client.post(
            f"/api/v1/sessions/{session_id}/share",
            json={"shared_with_user_id": "user-charlie"},
            headers=auth_headers("user-bob"),
        )

    # Get first page with page_size=1
    response = await client.get(
        "/api/v1/shared-with-me?page=1&page_size=1",
        headers=auth_headers("user-charlie"),
    )

    assert response.status_code == 200
    data = response.json()

    assert len(data["data"]) == 1
    assert data["metadata"]["total"] == 2
    assert data["metadata"]["page"] == 1
    assert data["metadata"]["page_size"] == 1
    assert data["metadata"]["total_pages"] == 2
    assert data["metadata"]["has_next"] is True
    assert data["metadata"]["has_previous"] is False

    # Get second page
    response = await client.get(
        "/api/v1/shared-with-me?page=2&page_size=1",
        headers=auth_headers("user-charlie"),
    )

    data = response.json()
    assert len(data["data"]) == 1
    assert data["metadata"]["has_next"] is False
    assert data["metadata"]["has_previous"] is True


@pytest.mark.asyncio
async def test_get_shared_messages_endpoint(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test GET /api/v1/shared-with-me/{user_id}/messages endpoint."""
    # Bob shares all his sessions with Alice
    for session_id in BOB_SESSIONS.keys():
        await client.post(
            f"/api/v1/sessions/{session_id}/share",
            json={"shared_with_user_id": "user-alice"},
            headers=auth_headers("user-bob"),
        )

    # Alice gets messages from Bob's shared sessions
    response = await client.get(
        "/api/v1/shared-with-me/user-bob/messages",
        headers=auth_headers("user-alice"),
    )

    assert response.status_code == 200
    data = response.json()

    assert data["object"] == "list"
    assert len(data["data"]) == 7  # All of Bob's messages

    # Verify messages are from Bob's sessions
    session_ids = {msg["session_id"] for msg in data["data"]}
    assert session_ids == set(BOB_SESSIONS.keys())


@pytest.mark.asyncio
async def test_get_shared_messages_pagination(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test pagination for shared messages endpoint."""
    # Bob shares with Alice
    for session_id in BOB_SESSIONS.keys():
        await client.post(
            f"/api/v1/sessions/{session_id}/share",
            json={"shared_with_user_id": "user-alice"},
            headers=auth_headers("user-bob"),
        )

    # Get first 3 messages
    response = await client.get(
        "/api/v1/shared-with-me/user-bob/messages?page=1&page_size=3",
        headers=auth_headers("user-alice"),
    )

    assert response.status_code == 200
    data = response.json()

    assert len(data["data"]) == 3
    assert data["metadata"]["total"] == 7
    assert data["metadata"]["has_next"] is True


# =============================================================================
# Full Workflow Test
# =============================================================================


@pytest.mark.asyncio
async def test_full_sharing_workflow(client, postgres_service, clean_shared_sessions, setup_test_users, setup_test_messages):
    """Test complete sharing workflow: share, view, unshare, verify."""
    # 1. Initial state - Bob has no shares
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )
    assert response.json()["metadata"]["total"] == 0

    # 2. Alice shares session-1 with Bob
    response = await client.post(
        "/api/v1/sessions/alice-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 201

    # 3. Bob can now see Alice in shared-with-me
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )
    data = response.json()
    assert data["metadata"]["total"] == 1
    assert data["data"][0]["user_id"] == "user-alice"
    assert data["data"][0]["session_count"] == 1
    assert data["data"][0]["message_count"] == 3  # alice-session-1 has 3 messages

    # 4. Alice shares session-2 as well
    response = await client.post(
        "/api/v1/sessions/alice-session-2/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 201

    # 5. Bob's view updates
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )
    data = response.json()
    assert data["data"][0]["session_count"] == 2
    assert data["data"][0]["message_count"] == 7  # 3 + 4

    # 6. Bob can view Alice's shared messages
    response = await client.get(
        "/api/v1/shared-with-me/user-alice/messages",
        headers=auth_headers("user-bob"),
    )
    assert len(response.json()["data"]) == 7

    # 7. Alice revokes session-1
    response = await client.delete(
        "/api/v1/sessions/alice-session-1/share/user-bob",
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 200

    # 8. Bob's view updates - only session-2 remains
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )
    data = response.json()
    assert data["data"][0]["session_count"] == 1
    assert data["data"][0]["message_count"] == 4  # Only session-2

    # 9. Alice revokes session-2
    response = await client.delete(
        "/api/v1/sessions/alice-session-2/share/user-bob",
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 200

    # 10. Bob has no shares again
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )
    assert response.json()["metadata"]["total"] == 0

    # 11. Alice can re-share (soft delete allows re-creation)
    response = await client.post(
        "/api/v1/sessions/alice-session-1/share",
        json={"shared_with_user_id": "user-bob"},
        headers=auth_headers("user-alice"),
    )
    assert response.status_code == 201

    # 12. Bob can see Alice again
    response = await client.get(
        "/api/v1/shared-with-me",
        headers=auth_headers("user-bob"),
    )
    assert response.json()["metadata"]["total"] == 1
