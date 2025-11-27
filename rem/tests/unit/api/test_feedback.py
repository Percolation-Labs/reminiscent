"""
Tests for feedback endpoints and models.
"""

import pytest
from pydantic import ValidationError

from rem.models.entities import Feedback, FeedbackCategory


class TestFeedbackModel:
    """Tests for Feedback model validation."""

    def test_create_basic_feedback(self):
        """Should create feedback with minimal fields."""
        feedback = Feedback(
            session_id="session-123",
            rating=4,
            tenant_id="tenant-1",
        )
        assert feedback.session_id == "session-123"
        assert feedback.rating == 4
        assert feedback.message_id is None
        assert feedback.categories == []
        assert feedback.phoenix_synced is False

    def test_create_feedback_with_message(self):
        """Should create feedback attached to a message."""
        feedback = Feedback(
            session_id="session-123",
            message_id="msg-456",
            rating=5,
            categories=["helpful", "accurate"],
            comment="Great response!",
            tenant_id="tenant-1",
        )
        assert feedback.message_id == "msg-456"
        assert "helpful" in feedback.categories
        assert feedback.comment == "Great response!"

    def test_create_feedback_with_trace(self):
        """Should create feedback with trace info."""
        feedback = Feedback(
            session_id="session-123",
            trace_id="trace-abc",
            span_id="span-xyz",
            rating=3,
            tenant_id="tenant-1",
        )
        assert feedback.trace_id == "trace-abc"
        assert feedback.span_id == "span-xyz"

    def test_rating_thumbs_down(self):
        """Should accept -1 for thumbs down."""
        feedback = Feedback(
            session_id="session-123",
            rating=-1,
            tenant_id="tenant-1",
        )
        assert feedback.rating == -1

    def test_rating_range_validation(self):
        """Should reject ratings outside valid range."""
        with pytest.raises(ValidationError):
            Feedback(
                session_id="session-123",
                rating=6,  # Invalid: max is 5
                tenant_id="tenant-1",
            )

        with pytest.raises(ValidationError):
            Feedback(
                session_id="session-123",
                rating=-2,  # Invalid: min is -1
                tenant_id="tenant-1",
            )

    def test_feedback_requires_session_id(self):
        """Session ID is required."""
        with pytest.raises(ValidationError):
            Feedback(tenant_id="t1")  # Missing session_id

    def test_feedback_with_all_categories(self):
        """Should accept all predefined categories."""
        categories = [c.value for c in FeedbackCategory]
        feedback = Feedback(
            session_id="session-123",
            categories=categories,
            tenant_id="tenant-1",
        )
        assert len(feedback.categories) == len(FeedbackCategory)


class TestFeedbackCategory:
    """Tests for FeedbackCategory enum."""

    def test_negative_categories(self):
        """Should have negative feedback categories."""
        assert FeedbackCategory.INCOMPLETE.value == "incomplete"
        assert FeedbackCategory.INACCURATE.value == "inaccurate"
        assert FeedbackCategory.POOR_TONE.value == "poor_tone"

    def test_positive_categories(self):
        """Should have positive feedback categories."""
        assert FeedbackCategory.HELPFUL.value == "helpful"
        assert FeedbackCategory.EXCELLENT.value == "excellent"
        assert FeedbackCategory.ACCURATE.value == "accurate"

    def test_other_category(self):
        """Should have 'other' catch-all category."""
        assert FeedbackCategory.OTHER.value == "other"
