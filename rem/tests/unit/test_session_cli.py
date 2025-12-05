"""Unit tests for session CLI command."""

import pytest
from click.testing import CliRunner

from rem.cli.main import cli
from rem.cli.commands.session import (
    _format_user_yaml,
    _format_messages_yaml,
    _format_conversation_for_llm,
    SIMULATOR_PROMPT,
)
from rem.models.entities.user import User
from rem.models.entities.message import Message
from datetime import datetime
from uuid import uuid4


class TestSessionCLI:
    """Tests for session CLI command."""

    def test_session_command_registered(self):
        """Test that session command is registered."""
        runner = CliRunner()
        result = runner.invoke(cli, ["session", "--help"])
        assert result.exit_code == 0
        assert "Session viewing and simulation commands" in result.output

    def test_session_show_help(self):
        """Test session show help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["session", "show", "--help"])
        assert result.exit_code == 0
        assert "--role" in result.output
        assert "--simulate-next" in result.output
        assert "--save" in result.output
        assert "--custom-sim-prompt" in result.output


class TestFormatFunctions:
    """Tests for formatting functions."""

    def test_format_user_yaml_none(self):
        """Test formatting None user."""
        result = _format_user_yaml(None)
        assert result == "# No user found"

    def test_format_user_yaml(self):
        """Test formatting user as YAML."""
        user = User(
            id=uuid4(),
            name="Test User",
            summary="Test summary",
            interests=["coding", "music"],
            preferred_topics=["python", "ai"],
            metadata={"key": "value"},
        )
        result = _format_user_yaml(user)
        assert "name: Test User" in result
        assert "summary: Test summary" in result
        assert "coding" in result
        assert "python" in result

    def test_format_messages_yaml_empty(self):
        """Test formatting empty messages."""
        result = _format_messages_yaml([])
        assert result == "# No messages found"

    def test_format_messages_yaml(self):
        """Test formatting messages as YAML."""
        messages = [
            Message(
                id=uuid4(),
                content="Hello",
                message_type="user",
                session_id="sess-1",
                created_at=datetime.now(),
            ),
            Message(
                id=uuid4(),
                content="Hi there",
                message_type="assistant",
                session_id="sess-1",
                created_at=datetime.now(),
            ),
        ]
        result = _format_messages_yaml(messages)
        assert "role: user" in result
        assert "content: Hello" in result
        assert "role: assistant" in result
        assert "content: Hi there" in result

    def test_format_conversation_for_llm_empty(self):
        """Test formatting empty conversation."""
        result = _format_conversation_for_llm([])
        assert result == "(No previous messages)"

    def test_format_conversation_for_llm(self):
        """Test formatting conversation for LLM."""
        messages = [
            Message(id=uuid4(), content="Hello", message_type="user"),
            Message(id=uuid4(), content="Hi!", message_type="assistant"),
        ]
        result = _format_conversation_for_llm(messages)
        assert "[USER]: Hello" in result
        assert "[ASSISTANT]: Hi!" in result


class TestSimulatorPrompt:
    """Tests for simulator prompt."""

    def test_simulator_prompt_has_placeholders(self):
        """Test that simulator prompt has required placeholders."""
        assert "{user_profile}" in SIMULATOR_PROMPT
        assert "{conversation_history}" in SIMULATOR_PROMPT

    def test_simulator_prompt_format(self):
        """Test that simulator prompt can be formatted."""
        formatted = SIMULATOR_PROMPT.format(
            user_profile="Test user",
            conversation_history="[USER]: Hello",
        )
        assert "Test user" in formatted
        assert "[USER]: Hello" in formatted
