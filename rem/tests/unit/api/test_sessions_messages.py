"""
Tests for the /sessions and /messages endpoints.

Note: Most tests require a database connection and are marked as integration tests.
These unit tests focus on model validation and basic endpoint structure.
"""

import pytest
from pydantic import ValidationError

from rem.models.entities import Message, Session, SessionMode


class TestSessionModel:
    """Tests for Session model validation."""

    def test_create_normal_session(self):
        """Should create a normal session with minimal fields."""
        session = Session(
            name="test-session",
            user_id="user-123",
            tenant_id="tenant-1",
        )
        assert session.name == "test-session"
        assert session.mode == SessionMode.NORMAL
        assert session.prompt is None
        assert session.settings_overrides is None

    def test_create_evaluation_session(self):
        """Should create an evaluation session with all fields."""
        session = Session(
            name="eval-session",
            mode=SessionMode.EVALUATION,
            description="Testing GPT-4.1 vs Claude",
            original_trace_id="original-session-123",
            settings_overrides={
                "model": "openai:gpt-4.1",
                "temperature": 0.3,
            },
            prompt="Custom evaluation prompt",
            user_id="user-123",
            tenant_id="tenant-1",
        )
        assert session.mode == SessionMode.EVALUATION
        assert session.original_trace_id == "original-session-123"
        assert session.settings_overrides["model"] == "openai:gpt-4.1"
        assert session.prompt == "Custom evaluation prompt"

    def test_session_mode_enum_values(self):
        """Should accept string mode values."""
        session = Session(
            name="test",
            mode="evaluation",  # String value
            tenant_id="t1",
        )
        # With use_enum_values=True, it stores as string
        assert session.mode == "evaluation"


class TestMessageModel:
    """Tests for Message model validation."""

    def test_create_basic_message(self):
        """Should create a basic message."""
        msg = Message(
            content="Hello, world!",
            message_type="user",
            session_id="session-123",
            tenant_id="tenant-1",
        )
        assert msg.content == "Hello, world!"
        assert msg.message_type == "user"
        assert msg.session_id == "session-123"

    def test_message_with_prompt_override(self):
        """Should store custom prompt on message."""
        msg = Message(
            content="Response to custom prompt",
            message_type="assistant",
            session_id="session-123",
            prompt="Custom system prompt",
            model="openai:gpt-4.1",
            token_count=150,
            tenant_id="tenant-1",
        )
        assert msg.prompt == "Custom system prompt"
        assert msg.model == "openai:gpt-4.1"
        assert msg.token_count == 150

    def test_message_requires_content(self):
        """Content field is required."""
        with pytest.raises(ValidationError):
            Message(tenant_id="t1")  # Missing content


class TestSessionModeEnum:
    """Tests for SessionMode enum."""

    def test_normal_mode(self):
        """Should have normal mode."""
        assert SessionMode.NORMAL.value == "normal"

    def test_evaluation_mode(self):
        """Should have evaluation mode."""
        assert SessionMode.EVALUATION.value == "evaluation"

    def test_mode_comparison(self):
        """Should compare modes correctly."""
        assert SessionMode.NORMAL == SessionMode.NORMAL
        assert SessionMode.NORMAL != SessionMode.EVALUATION
