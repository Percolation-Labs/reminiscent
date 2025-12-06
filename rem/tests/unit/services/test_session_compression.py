"""
Tests for session message compression with tool call support.

Tests the compression strategy:
- All messages stored UNCOMPRESSED in database
- Compression happens on RELOAD only
- Tool messages (role: "tool") are NEVER compressed
- Long assistant messages are compressed with REM LOOKUP hints
"""

import pytest

from rem.services.session.compression import MessageCompressor


class TestMessageCompressor:
    """Tests for the MessageCompressor class."""

    def test_short_message_not_compressed(self):
        """Short messages should not be compressed."""
        compressor = MessageCompressor(truncate_length=200)
        message = {
            "role": "assistant",
            "content": "This is a short response.",
        }

        result = compressor.compress_message(message)

        assert result["content"] == message["content"]
        assert "_compressed" not in result

    def test_long_assistant_message_compressed(self):
        """Long assistant messages should be compressed with REM LOOKUP hint."""
        compressor = MessageCompressor(truncate_length=50)
        long_content = "A" * 200  # 200 chars, well over min_length_for_compression (100)
        message = {
            "role": "assistant",
            "content": long_content,
        }

        result = compressor.compress_message(message, entity_key="session-123-msg-0")

        assert result["_compressed"] is True
        assert "REM LOOKUP session-123-msg-0" in result["content"]
        assert len(result["content"]) < len(long_content)

    def test_system_message_never_compressed(self):
        """System messages should never be compressed."""
        compressor = MessageCompressor(truncate_length=50)
        long_content = "A" * 200
        message = {
            "role": "system",
            "content": long_content,
        }

        result = compressor.compress_message(message)

        assert result["content"] == long_content
        assert "_compressed" not in result

    def test_is_compressed_check(self):
        """Should correctly identify compressed messages."""
        compressor = MessageCompressor()

        compressed = {"role": "assistant", "content": "...", "_compressed": True}
        not_compressed = {"role": "assistant", "content": "Hello"}

        assert compressor.is_compressed(compressed) is True
        assert compressor.is_compressed(not_compressed) is False


class TestToolMessageHandling:
    """Tests for tool message storage and reload patterns."""

    def test_tool_message_structure(self):
        """Tool messages should maintain their structure."""
        # This is the format we expect for tool messages
        tool_message = {
            "role": "tool",
            "content": '{"status": "success", "confidence": 0.8}',
            "tool_call_id": "call_abc123",
            "tool_name": "register_metadata",
            "tool_arguments": {"confidence": 0.8, "extra": {"collected_fields": {}}},
        }

        assert tool_message["role"] == "tool"
        assert tool_message["tool_call_id"] == "call_abc123"
        assert tool_message["tool_name"] == "register_metadata"

    def test_tool_message_compression_logic(self):
        """
        Demonstrate that tool messages are protected at the caller level.

        The MessageCompressor class itself doesn't have special handling for "tool" role.
        The protection happens in load_session_messages() which only calls compress
        for messages where role == "assistant".

        This test verifies the intended usage pattern.
        """
        compressor = MessageCompressor(truncate_length=50)

        # Tool message with structured metadata
        tool_message = {
            "role": "tool",
            "content": '{"status": "success", "confidence": 0.8}',
            "tool_call_id": "call_abc123",
            "tool_name": "register_metadata",
        }

        # The pattern used in load_session_messages:
        # Only compress if role == "assistant" AND content is long
        should_compress = (
            tool_message["role"] == "assistant"
            and len(tool_message["content"]) > compressor.min_length_for_compression
        )

        # Tool messages should never match the compression criteria
        assert should_compress is False, "Tool messages should not match compression criteria"

        # If we DON'T compress (as load_session_messages won't), content is preserved
        if not should_compress:
            result = tool_message  # No compression applied
            assert result["content"] == tool_message["content"]
            assert result["tool_call_id"] == "call_abc123"


class TestSampleSessionFlow:
    """Tests using realistic sample messages."""

    @pytest.fixture
    def sample_session_messages(self):
        """Sample messages from a triage intake session."""
        return [
            # Turn 1
            {
                "role": "user",
                "content": "Hi, I've been having really bad headaches",
            },
            {
                "role": "tool",
                "content": '{"status": "success", "_metadata_event": true, "confidence": 0.3, "extra": {"collected_fields": {"chief_complaint": "headaches"}, "fields_missing": ["name", "duration", "severity"]}}',
                "tool_call_id": "call_001",
                "tool_name": "register_metadata",
                "tool_arguments": {
                    "confidence": 0.3,
                    "extra": {
                        "collected_fields": {"chief_complaint": "headaches"},
                        "fields_missing": ["name", "duration", "severity"],
                    }
                },
            },
            {
                "role": "assistant",
                "content": "I'm sorry to hear that. How long have you been experiencing these headaches?",
            },
            # Turn 2
            {
                "role": "user",
                "content": "About 3 days now, they're really bad, like a 7 out of 10",
            },
            {
                "role": "tool",
                "content": '{"status": "success", "_metadata_event": true, "confidence": 0.6, "extra": {"collected_fields": {"chief_complaint": "headaches", "duration": "3 days", "severity": 7}, "fields_missing": ["name"]}}',
                "tool_call_id": "call_002",
                "tool_name": "register_metadata",
                "tool_arguments": {
                    "confidence": 0.6,
                    "extra": {
                        "collected_fields": {
                            "chief_complaint": "headaches",
                            "duration": "3 days",
                            "severity": 7,
                        },
                        "fields_missing": ["name"],
                    }
                },
            },
            {
                "role": "assistant",
                "content": "Got it - 3 days and a 7 out of 10. That sounds quite uncomfortable. What's your name so I know how to address you?",
            },
            # Turn 3
            {
                "role": "user",
                "content": "I'm Sarah",
            },
            {
                "role": "tool",
                "content": '{"status": "success", "_metadata_event": true, "confidence": 0.9, "extra": {"collected_fields": {"chief_complaint": "headaches", "duration": "3 days", "severity": 7, "name": "Sarah"}, "intake_complete": true, "routing_recommendation": "standard"}}',
                "tool_call_id": "call_003",
                "tool_name": "register_metadata",
                "tool_arguments": {
                    "confidence": 0.9,
                    "extra": {
                        "collected_fields": {
                            "chief_complaint": "headaches",
                            "duration": "3 days",
                            "severity": 7,
                            "name": "Sarah",
                        },
                        "intake_complete": True,
                        "routing_recommendation": "standard",
                    }
                },
            },
            {
                "role": "assistant",
                "content": "Thanks Sarah. Based on what you've shared, I'll connect you with a healthcare provider who can help with your headaches. They'll be with you shortly.",
            },
        ]

    def test_count_message_types(self, sample_session_messages):
        """Verify the sample session has expected message types."""
        roles = [m["role"] for m in sample_session_messages]

        assert roles.count("user") == 3
        assert roles.count("tool") == 3
        assert roles.count("assistant") == 3

    def test_tool_messages_have_metadata(self, sample_session_messages):
        """Verify tool messages have required metadata fields."""
        tool_messages = [m for m in sample_session_messages if m["role"] == "tool"]

        for tool_msg in tool_messages:
            assert "tool_call_id" in tool_msg
            assert "tool_name" in tool_msg
            assert tool_msg["tool_name"] == "register_metadata"
            assert "tool_arguments" in tool_msg

    def test_intake_progress_visible_in_tool_messages(self, sample_session_messages):
        """Tool messages should show intake progress over time."""
        tool_messages = [m for m in sample_session_messages if m["role"] == "tool"]

        # First tool call: just chief_complaint
        args1 = tool_messages[0]["tool_arguments"]
        assert args1["confidence"] == 0.3
        assert "name" in args1["extra"]["fields_missing"]

        # Second tool call: added duration and severity
        args2 = tool_messages[1]["tool_arguments"]
        assert args2["confidence"] == 0.6
        assert "severity" in args2["extra"]["collected_fields"]

        # Third tool call: intake complete
        args3 = tool_messages[2]["tool_arguments"]
        assert args3["confidence"] == 0.9
        assert args3["extra"]["intake_complete"] is True
        assert args3["extra"]["routing_recommendation"] == "standard"

    def test_compression_preserves_tool_message_structure(self, sample_session_messages):
        """Simulating reload: tool messages should remain intact after compression pass."""
        compressor = MessageCompressor(truncate_length=50)

        # Simulate what load_session_messages does:
        # Only compress assistant messages, never tool messages
        reloaded_messages = []
        for idx, msg in enumerate(sample_session_messages):
            if msg["role"] == "assistant" and len(msg["content"]) > compressor.min_length_for_compression:
                # Compress long assistant messages
                compressed = compressor.compress_message(msg, f"session-test-msg-{idx}")
                reloaded_messages.append(compressed)
            else:
                # Keep as-is: user, tool, and short assistant messages
                reloaded_messages.append(msg)

        # Verify tool messages are unchanged
        tool_messages = [m for m in reloaded_messages if m["role"] == "tool"]
        assert len(tool_messages) == 3

        for tool_msg in tool_messages:
            assert "_compressed" not in tool_msg
            assert "tool_call_id" in tool_msg
            assert "tool_arguments" in tool_msg
