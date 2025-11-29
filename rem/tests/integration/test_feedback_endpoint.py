"""
Integration tests for feedback endpoint.

Tests the /api/v1/messages/feedback API endpoint for submitting feedback.
"""

import pytest
from fastapi.testclient import TestClient

from rem.api.main import app
from rem.settings import settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestFeedbackSubmissionEndpoint:
    """Tests for POST /api/v1/messages/feedback endpoint."""

    def test_submit_session_feedback(self, client):
        """Should submit feedback for a session."""
        response = client.post(
            "/api/v1/messages/feedback",
            json={
                "session_id": "test-session-123",
                "rating": 4,
                "categories": ["helpful"],
                "comment": "Good session overall",
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201

        data = response.json()
        assert data["session_id"] == "test-session-123"
        assert data["rating"] == 4
        assert "helpful" in data["categories"]
        assert data["comment"] == "Good session overall"
        assert data["phoenix_synced"] is False

    def test_submit_message_feedback(self, client):
        """Should submit feedback for a specific message."""
        # Use a valid UUID format for message_id
        message_id = "00000000-0000-0000-0000-000000000456"
        response = client.post(
            "/api/v1/messages/feedback",
            json={
                "session_id": "test-session-123",
                "message_id": message_id,
                "rating": 5,
                "categories": ["excellent", "accurate"],
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201

        data = response.json()
        assert data["message_id"] == message_id
        assert data["rating"] == 5

    def test_submit_thumbs_down(self, client):
        """Should accept thumbs down rating (-1)."""
        response = client.post(
            "/api/v1/messages/feedback",
            json={
                "session_id": "test-session-123",
                "rating": -1,
                "categories": ["inaccurate"],
                "comment": "Response was wrong",
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201
        assert response.json()["rating"] == -1

    def test_submit_feedback_with_trace(self, client):
        """Should accept explicit trace info."""
        response = client.post(
            "/api/v1/messages/feedback",
            json={
                "session_id": "test-session-123",
                "rating": 4,
                "trace_id": "trace-abc-123",
                "span_id": "span-xyz-789",
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201

        data = response.json()
        assert data["trace_id"] == "trace-abc-123"
        assert data["span_id"] == "span-xyz-789"

    def test_submit_feedback_comment_only(self, client):
        """Should accept feedback with only comment (no rating)."""
        response = client.post(
            "/api/v1/messages/feedback",
            json={
                "session_id": "test-session-123",
                "comment": "Just a note about this session",
            },
            headers={
                "X-User-Id": "test-user",
                "X-Tenant-Id": "test-tenant",
            },
        )
        assert response.status_code == 201
        assert response.json()["rating"] is None
