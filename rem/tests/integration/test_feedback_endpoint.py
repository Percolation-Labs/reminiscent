"""
Integration tests for feedback endpoints.

Tests the /feedback API endpoints including submission and retrieval.
"""

import pytest
from fastapi.testclient import TestClient

from rem.api.main import app
from rem.settings import settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestFeedbackCategoriesEndpoint:
    """Tests for GET /api/v1/feedback/categories endpoint."""

    def test_list_categories(self, client):
        """Should return all predefined categories."""
        response = client.get("/api/v1/feedback/categories")
        assert response.status_code == 200

        data = response.json()
        assert "categories" in data
        assert len(data["categories"]) > 0

        # Check category structure
        category = data["categories"][0]
        assert "value" in category
        assert "label" in category
        assert "description" in category
        assert "sentiment" in category

    def test_categories_include_sentiments(self, client):
        """Categories should have positive, negative, and neutral sentiments."""
        response = client.get("/api/v1/feedback/categories")
        data = response.json()

        sentiments = {c["sentiment"] for c in data["categories"]}
        assert "positive" in sentiments
        assert "negative" in sentiments
        assert "neutral" in sentiments


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestFeedbackSubmissionEndpoint:
    """Tests for POST /api/v1/feedback endpoint."""

    def test_submit_session_feedback(self, client):
        """Should submit feedback for a session."""
        response = client.post(
            "/api/v1/feedback",
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
            "/api/v1/feedback",
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
            "/api/v1/feedback",
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
            "/api/v1/feedback",
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
            "/api/v1/feedback",
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


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestFeedbackListEndpoint:
    """Tests for GET /api/v1/feedback endpoint."""

    def test_list_feedback_empty(self, client):
        """Should return empty list when no feedback."""
        response = client.get(
            "/api/v1/feedback",
            headers={
                "X-User-Id": "unique-test-user",
                "X-Tenant-Id": "unique-test-tenant",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert data["object"] == "list"
        assert isinstance(data["data"], list)

    def test_list_feedback_with_filters(self, client):
        """Should filter feedback by session_id."""
        # First submit some feedback
        client.post(
            "/api/v1/feedback",
            json={
                "session_id": "filter-test-session",
                "rating": 5,
            },
            headers={
                "X-User-Id": "filter-test-user",
                "X-Tenant-Id": "filter-test-tenant",
            },
        )

        # Then filter by session
        response = client.get(
            "/api/v1/feedback?session_id=filter-test-session",
            headers={
                "X-User-Id": "filter-test-user",
                "X-Tenant-Id": "filter-test-tenant",
            },
        )
        assert response.status_code == 200

        data = response.json()
        for feedback in data["data"]:
            assert feedback["session_id"] == "filter-test-session"


@pytest.mark.skipif(
    not settings.postgres.enabled,
    reason="Database not enabled (POSTGRES__ENABLED=false)"
)
class TestFeedbackGetEndpoint:
    """Tests for GET /api/v1/feedback/{id} endpoint."""

    def test_get_nonexistent_feedback(self, client):
        """Should return 404 for unknown feedback."""
        response = client.get(
            "/api/v1/feedback/00000000-0000-0000-0000-000000000000",
            headers={"X-Tenant-Id": "test-tenant"},
        )
        assert response.status_code == 404
