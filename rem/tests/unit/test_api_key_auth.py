"""
Unit tests for X-API-Key authentication middleware.
"""

import pytest
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from fastapi import FastAPI


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    settings = MagicMock()
    settings.environment = "development"
    settings.api.api_key_enabled = False
    settings.api.api_key = None
    return settings


@pytest.fixture
def app_with_middleware(mock_settings):
    """Create a test app with AuthMiddleware."""
    from rem.auth.middleware import AuthMiddleware
    from starlette.middleware.sessions import SessionMiddleware

    app = FastAPI()

    # Add a simple test endpoint
    @app.get("/api/v1/test")
    async def test_endpoint():
        return {"status": "ok"}

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    # Patch settings before adding middleware
    with patch("rem.auth.middleware.settings", mock_settings):
        app.add_middleware(
            AuthMiddleware,
            protected_paths=["/api/v1"],
            excluded_paths=["/health"],
            allow_anonymous=True,
            mcp_requires_auth=False,
        )

    # Add SessionMiddleware (required by AuthMiddleware for session check)
    app.add_middleware(SessionMiddleware, secret_key="test-secret")

    return app, mock_settings


class TestApiKeyAuth:
    """Test X-API-Key authentication."""

    def test_api_key_disabled_allows_anonymous(self, app_with_middleware):
        """When API key auth is disabled, anonymous requests should pass through."""
        app, mock_settings = app_with_middleware
        mock_settings.api.api_key_enabled = False

        with patch("rem.auth.middleware.settings", mock_settings):
            client = TestClient(app)
            response = client.get("/api/v1/test")
            # Should allow anonymous when api_key_enabled=False
            assert response.status_code == 200

    def test_api_key_enabled_requires_key(self, app_with_middleware):
        """When API key auth is enabled, requests without key should be rejected."""
        app, mock_settings = app_with_middleware
        mock_settings.api.api_key_enabled = True
        mock_settings.api.api_key = "test-secret-key"

        with patch("rem.auth.middleware.settings", mock_settings):
            client = TestClient(app)
            response = client.get("/api/v1/test")
            assert response.status_code == 401
            assert "API key required" in response.json()["detail"]

    def test_api_key_enabled_valid_key_passes(self, app_with_middleware):
        """When API key auth is enabled, valid key should authenticate."""
        app, mock_settings = app_with_middleware
        mock_settings.api.api_key_enabled = True
        mock_settings.api.api_key = "test-secret-key"

        with patch("rem.auth.middleware.settings", mock_settings):
            client = TestClient(app)
            response = client.get(
                "/api/v1/test",
                headers={"X-API-Key": "test-secret-key"}
            )
            assert response.status_code == 200

    def test_api_key_enabled_invalid_key_rejected(self, app_with_middleware):
        """When API key auth is enabled, invalid key should be rejected."""
        app, mock_settings = app_with_middleware
        mock_settings.api.api_key_enabled = True
        mock_settings.api.api_key = "test-secret-key"

        with patch("rem.auth.middleware.settings", mock_settings):
            client = TestClient(app)
            response = client.get(
                "/api/v1/test",
                headers={"X-API-Key": "wrong-key"}
            )
            assert response.status_code == 401
            assert "Invalid API key" in response.json()["detail"]

    def test_excluded_paths_bypass_api_key(self, app_with_middleware):
        """Excluded paths should not require API key."""
        app, mock_settings = app_with_middleware
        mock_settings.api.api_key_enabled = True
        mock_settings.api.api_key = "test-secret-key"

        with patch("rem.auth.middleware.settings", mock_settings):
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200

    def test_api_key_case_insensitive_header(self, app_with_middleware):
        """X-API-Key header should work case-insensitively."""
        app, mock_settings = app_with_middleware
        mock_settings.api.api_key_enabled = True
        mock_settings.api.api_key = "test-secret-key"

        with patch("rem.auth.middleware.settings", mock_settings):
            client = TestClient(app)
            # Lowercase header name
            response = client.get(
                "/api/v1/test",
                headers={"x-api-key": "test-secret-key"}
            )
            assert response.status_code == 200
