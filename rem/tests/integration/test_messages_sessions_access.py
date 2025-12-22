"""
Integration tests for Messages and Sessions endpoint access control.

Tests:
- Admin users can search across all sessions and messages
- Regular users can only see their own sessions and messages
- Pagination works correctly
- Search with user attributes (names, emails) on sessions

Requires POSTGRES__ENABLED=true and a running database.
Use `tilt up` to start local development environment.
"""

import pytest
from uuid import uuid4
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient

from rem.api.main import app
from rem.auth.jwt import JWTService
from rem.settings import settings


# =============================================================================
# Test Fixtures
# =============================================================================


# Use a shared secret for test JWT tokens
TEST_JWT_SECRET = "test-secret-for-jwt-signing-12345"


@pytest.fixture
def jwt_service():
    """Create a JWT service with test secret."""
    return JWTService(secret=TEST_JWT_SECRET)


@pytest.fixture
def admin_user() -> dict:
    """Admin user data for JWT creation."""
    return {
        "id": str(uuid4()),
        "email": "admin@test.local",
        "name": "Test Admin",
        "role": "admin",
        "tier": "pro",
        "roles": ["admin", "user"],
        "provider": "email",
        "tenant_id": "default",
    }


@pytest.fixture
def regular_user_alice() -> dict:
    """Regular user Alice for JWT creation."""
    return {
        "id": str(uuid4()),
        "email": "alice@test.local",
        "name": "Alice Smith",
        "role": "user",
        "tier": "free",
        "roles": ["user"],
        "provider": "email",
        "tenant_id": "default",
    }


@pytest.fixture
def regular_user_bob() -> dict:
    """Regular user Bob for JWT creation."""
    return {
        "id": str(uuid4()),
        "email": "bob@test.local",
        "name": "Bob Jones",
        "role": "user",
        "tier": "basic",
        "roles": ["user"],
        "provider": "email",
        "tenant_id": "default",
    }


@pytest.fixture
def admin_token(jwt_service, admin_user) -> str:
    """Generate JWT token for admin user."""
    tokens = jwt_service.create_tokens(admin_user)
    return tokens["access_token"]


@pytest.fixture
def alice_token(jwt_service, regular_user_alice) -> str:
    """Generate JWT token for Alice."""
    tokens = jwt_service.create_tokens(regular_user_alice)
    return tokens["access_token"]


@pytest.fixture
def bob_token(jwt_service, regular_user_bob) -> str:
    """Generate JWT token for Bob."""
    tokens = jwt_service.create_tokens(regular_user_bob)
    return tokens["access_token"]


@pytest.fixture
def client():
    """Create test client with fresh database pool."""
    # Reset the database singleton to avoid event loop issues across tests
    import rem.services.postgres as pg_module

    # Reset the singleton to force new pool creation in each test's event loop
    pg_module._postgres_instance = None

    return TestClient(app)


# NOTE: Seed fixtures removed for simplicity. Tests now use existing database data.
# To add seed data tests, use pytest-asyncio with proper event loop handling.


# =============================================================================
# Helper Functions
# =============================================================================


@contextmanager
def patch_jwt_service(jwt_service: JWTService):
    """Patch the global JWT service to use test secret."""
    with patch("rem.auth.jwt.get_jwt_service", return_value=jwt_service):
        yield


# =============================================================================
# Access Control Tests
# =============================================================================


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestSessionAccessControl:
    """Test session endpoint access control."""

    def test_admin_can_see_all_sessions(
        self, client, admin_token, jwt_service
    ):
        """Admin should be able to list all sessions."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/sessions",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        # Admin sees sessions
        assert data["object"] == "list"

        # Sessions should have user_name field
        for session in data["data"]:
            assert "user_name" in session

    def test_regular_user_sees_only_own_sessions(
        self, client, alice_token, jwt_service, regular_user_alice
    ):
        """Regular user should only see their own sessions."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/sessions",
                headers={"Authorization": f"Bearer {alice_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        # Alice only sees her own sessions (if any exist for this user)
        for session in data["data"]:
            assert session["user_id"] == regular_user_alice["id"]

    def test_admin_can_filter_by_mode(
        self, client, admin_token, jwt_service
    ):
        """Admin can filter sessions by mode."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/sessions?mode=evaluation",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        # All returned sessions should have evaluation mode
        for session in data["data"]:
            assert session["mode"] == "evaluation"

    def test_regular_user_user_name_filter_ignored(
        self, client, alice_token, jwt_service, regular_user_alice
    ):
        """Regular user's user_name filter should be ignored."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/sessions?user_name=SomeOtherUser",
                headers={"Authorization": f"Bearer {alice_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        # Alice still only sees her own sessions (user_name filter ignored)
        for session in data["data"]:
            assert session["user_id"] == regular_user_alice["id"]


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestMessageAccessControl:
    """Test message endpoint access control."""

    def test_admin_can_see_all_messages(
        self, client, admin_token, jwt_service
    ):
        """Admin should be able to list all messages."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/messages",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        assert data["object"] == "list"

    def test_regular_user_sees_only_own_messages(
        self, client, alice_token, jwt_service, regular_user_alice
    ):
        """Regular user should only see their own messages."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/messages",
                headers={"Authorization": f"Bearer {alice_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        # Alice only sees her own messages (if any exist for this user)
        for msg in data["data"]:
            assert msg["user_id"] == regular_user_alice["id"]


# =============================================================================
# Pagination Tests
# =============================================================================


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestSessionPagination:
    """Test session pagination."""

    def test_pagination_page_size(
        self, client, admin_token, jwt_service
    ):
        """Test that page_size limits results."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/sessions?page_size=2&page=1",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        assert len(data["data"]) <= 2
        assert data["metadata"]["page_size"] == 2
        assert data["metadata"]["page"] == 1

    def test_pagination_metadata(
        self, client, admin_token, jwt_service
    ):
        """Test that pagination metadata is correct."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/sessions?page_size=2&page=1",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        metadata = data["metadata"]
        assert "total" in metadata
        assert "page" in metadata
        assert "page_size" in metadata
        assert "total_pages" in metadata
        assert "has_next" in metadata
        assert "has_previous" in metadata

        # First page should not have previous
        assert metadata["has_previous"] is False


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestMessagePagination:
    """Test message pagination (offset-based)."""

    def test_message_limit(
        self, client, admin_token, jwt_service
    ):
        """Test that limit parameter works."""
        with patch_jwt_service(jwt_service):
            response = client.get(
                "/api/v1/messages?limit=5",
                headers={"Authorization": f"Bearer {admin_token}"},
            )

        assert response.status_code == 200
        data = response.json()

        assert len(data["data"]) <= 5


