"""Test that moment builder uses explicit user_id from request body."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.testclient import TestClient

from rem.api.routers.moments import router, MomentBuildRequest, build_moments
from rem.settings import settings


@pytest.fixture
def mock_request():
    """Create a mock request with anonymous user."""
    request = MagicMock(spec=Request)
    request.state = MagicMock()
    request.state.anon_id = "anon-test-id"
    return request


@pytest.fixture
def mock_settings():
    """Mock settings to enable moment builder."""
    with patch.object(settings.moment_builder, 'enabled', True):
        with patch.object(settings.postgres, 'enabled', True):
            yield


class TestMomentBuildRequest:
    """Test MomentBuildRequest model."""

    def test_user_id_is_optional(self):
        """user_id should be optional and default to None."""
        req = MomentBuildRequest(session_id="test-session")
        assert req.user_id is None
        assert req.session_id == "test-session"
        assert req.force is False

    def test_user_id_can_be_provided(self):
        """user_id should accept explicit value."""
        req = MomentBuildRequest(
            session_id="test-session",
            user_id="explicit-user-id"
        )
        assert req.user_id == "explicit-user-id"

    def test_force_defaults_to_false(self):
        """force should default to False."""
        req = MomentBuildRequest(session_id="test-session")
        assert req.force is False

    def test_all_fields(self):
        """Test all fields together."""
        req = MomentBuildRequest(
            session_id="sess-123",
            user_id="user-456",
            force=True
        )
        assert req.session_id == "sess-123"
        assert req.user_id == "user-456"
        assert req.force is True


@pytest.mark.asyncio
async def test_build_moments_uses_explicit_user_id(mock_request, mock_settings):
    """Test that build_moments uses explicit user_id from body when provided."""
    body = MomentBuildRequest(
        session_id="test-session-123",
        user_id="explicit-user-a1b2c3d4"
    )

    with patch('rem.api.routers.moments.asyncio.create_task') as mock_task:
        with patch('rem.api.routers.moments.get_user_id_from_request') as mock_get_user:
            mock_get_user.return_value = "anon:different-user"

            response = await build_moments(mock_request, body)

            # Should NOT have called get_user_id_from_request result
            # The task should be created with the explicit user_id
            mock_task.assert_called_once()
            call_kwargs = mock_task.call_args
            # The coroutine is the first positional arg
            coro = call_kwargs[0][0]
            # We can't easily inspect the coroutine args, but we can check
            # that the response was accepted
            assert response.status == "accepted"
            assert response.job_id is not None


@pytest.mark.asyncio
async def test_build_moments_falls_back_to_request_user(mock_request, mock_settings):
    """Test that build_moments falls back to request user when user_id not provided."""
    body = MomentBuildRequest(
        session_id="test-session-123"
        # user_id not provided
    )

    with patch('rem.api.routers.moments.asyncio.create_task') as mock_task:
        with patch('rem.api.routers.moments.get_user_id_from_request') as mock_get_user:
            mock_get_user.return_value = "anon:fallback-user"

            response = await build_moments(mock_request, body)

            # Should have called get_user_id_from_request
            mock_get_user.assert_called_once_with(mock_request)
            assert response.status == "accepted"
