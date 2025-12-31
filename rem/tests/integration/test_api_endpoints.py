"""
Integration tests for API endpoints.

Tests the /models, /sessions, and /messages endpoints.
Database tests are marked with @pytest.mark.slow and require POSTGRES__ENABLED=true.
"""

import pytest
import httpx
from fastapi.testclient import TestClient

from rem.api.main import app
from rem.settings import settings


@pytest.fixture
def client():
    """Create test client for sync tests (non-database)."""
    return TestClient(app)


@pytest.fixture
async def async_client():
    """Create async test client for database tests.

    Uses httpx.AsyncClient with ASGITransport to avoid event loop conflicts
    when testing endpoints that make async database calls.
    """
    from httpx import ASGITransport
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


class TestModelsEndpointIntegration:
    """Integration tests for /api/v1/models endpoint."""

    def test_models_endpoint_accessible(self, client):
        """Models endpoint should be accessible without auth."""
        response = client.get("/api/v1/models")
        assert response.status_code == 200

    def test_models_response_is_openai_compatible(self, client):
        """Response format should match OpenAI API."""
        response = client.get("/api/v1/models")
        data = response.json()

        # OpenAI format requirements
        assert "object" in data
        assert data["object"] == "list"
        assert "data" in data
        assert isinstance(data["data"], list)

        # Each model should have OpenAI-compatible fields
        if data["data"]:
            model = data["data"][0]
            assert "id" in model
            assert "object" in model
            assert model["object"] == "model"
            assert "created" in model
            assert isinstance(model["created"], int)
            assert "owned_by" in model

    def test_get_specific_model(self, client):
        """Should retrieve specific model by ID."""
        response = client.get("/api/v1/models/openai:gpt-4.1")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "openai:gpt-4.1"
        assert data["owned_by"] == "openai"


@pytest.mark.skip(
    reason="Session CRUD endpoints require admin authentication. "
    "Need to add admin auth mocking to enable these tests."
)
@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
@pytest.mark.slow
class TestSessionsEndpointIntegration:
    """Integration tests for /api/v1/sessions endpoint.

    Note: Requires sessions table to exist. Run migration:
        rem db apply --migration 004_sessions_and_messages.sql

    Note: Session creation requires admin authentication (require_admin dependency).
    These tests need admin auth mocking to run properly.
    TODO: Add fixture to mock authenticated admin user for these tests.
    """

    def test_create_normal_session(self, client):
        """Should create a normal session."""
        response = client.post(
            "/api/v1/sessions",
            json={
                "name": "test-normal-session",
                "description": "A test session",
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "test-normal-session"
        assert data["mode"] == "normal"
        assert data["user_id"] == "test-user"

    def test_create_evaluation_session(self, client):
        """Should create an evaluation session with overrides."""
        response = client.post(
            "/api/v1/sessions",
            json={
                "name": "test-eval-session",
                "mode": "evaluation",
                "original_trace_id": "original-123",
                "settings_overrides": {
                    "model": "openai:gpt-4.1",
                    "temperature": 0.2,
                },
                "prompt": "Custom evaluation prompt",
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201

        data = response.json()
        assert data["mode"] == "evaluation"
        assert data["original_trace_id"] == "original-123"
        assert data["settings_overrides"]["model"] == "openai:gpt-4.1"

    def test_list_sessions(self, client):
        """Should list sessions with pagination."""
        response = client.get(
            "/api/v1/sessions",
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["object"] == "list"
        assert "data" in data
        assert "total" in data
        assert "has_more" in data

    def test_filter_sessions_by_mode(self, client):
        """Should filter sessions by mode."""
        # Create sessions first
        client.post(
            "/api/v1/sessions",
            json={"name": "normal-session-filter-test", "mode": "normal"},
            headers={"X-User-Id": "test-user", "X-Tenant-Id": "test-tenant"},
        )
        client.post(
            "/api/v1/sessions",
            json={"name": "eval-session-filter-test", "mode": "evaluation"},
            headers={"X-User-Id": "test-user", "X-Tenant-Id": "test-tenant"},
        )

        # Filter by evaluation mode
        response = client.get(
            "/api/v1/sessions?mode=evaluation",
            headers={"X-User-Id": "test-user", "X-Tenant-Id": "test-tenant"},
        )
        assert response.status_code == 200

        data = response.json()
        for session in data["data"]:
            assert session["mode"] == "evaluation"


@pytest.mark.skip(
    reason="These tests require a running server (not TestClient) due to event loop conflicts. "
    "Run against a real API server with: pytest tests/integration/test_api_endpoints.py -k Messages --server"
)
@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestMessagesEndpointIntegration:
    """Integration tests for /api/v1/messages endpoint.

    NOTE: These tests are skipped in automated runs because TestClient creates its own
    event loop during app lifespan, which conflicts with asyncpg connections used by
    the async tests. Run these tests against a real server instead.

    Uses async_client to avoid event loop conflicts with asyncpg.
    """

    @pytest.mark.asyncio
    async def test_list_messages_empty(self, async_client):
        """Should return empty list when no messages."""
        response = await async_client.get(
            "/api/v1/messages",
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "unique-test-tenant",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)

    @pytest.mark.asyncio
    async def test_filter_messages_by_session(self, async_client):
        """Should filter messages by session_id."""
        response = await async_client.get(
            "/api/v1/messages?session_id=test-session-123",
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 200

        data = response.json()
        # All returned messages should have the filtered session_id
        for msg in data["data"]:
            assert msg["session_id"] == "test-session-123"

    @pytest.mark.asyncio
    async def test_filter_messages_by_user(self, async_client):
        """Should filter messages by user_id."""
        response = await async_client.get(
            "/api/v1/messages?user_id=specific-user",
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 200
        data = response.json()

        for msg in data["data"]:
            assert msg["user_id"] == "specific-user"

    @pytest.mark.asyncio
    async def test_messages_pagination(self, async_client):
        """Should support limit and offset pagination."""
        response = await async_client.get(
            "/api/v1/messages?limit=10&offset=0",
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data["data"]) <= 10
        assert "has_more" in data
        assert "total" in data


class TestEndpointErrorHandling:
    """Test error handling for endpoints."""

    def test_get_nonexistent_model(self, client):
        """Should return 404 for unknown model."""
        response = client.get("/api/v1/models/nonexistent:model")
        assert response.status_code == 404

    @pytest.mark.skip(reason="Event loop conflict with TestClient - run against real server")
    @pytest.mark.skipif(
        not settings.postgres.enabled,
        reason="Database not enabled"
    )
    def test_get_nonexistent_session(self, client):
        """Should return 404 for unknown session."""
        response = client.get(
            "/api/v1/sessions/00000000-0000-0000-0000-000000000000",
            headers={"X-Tenant-Id": "test-tenant"},
        )
        assert response.status_code == 404

    @pytest.mark.skip(reason="Event loop conflict with TestClient - run against real server")
    @pytest.mark.skipif(
        not settings.postgres.enabled,
        reason="Database not enabled"
    )
    def test_get_nonexistent_message(self, client):
        """Should return 404 for unknown message."""
        response = client.get(
            "/api/v1/messages/00000000-0000-0000-0000-000000000000",
            headers={"X-Tenant-Id": "test-tenant"},
        )
        assert response.status_code == 404
