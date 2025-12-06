"""
Tests for agent_manager module.

Run with: uv run pytest tests/test_agent_manager.py -v
"""

import pytest
from rem.agentic.agents.agent_manager import (
    build_agent_spec,
    save_agent,
    get_agent,
    list_agents,
    delete_agent,
    DEFAULT_TOOLS,
)


class TestBuildAgentSpec:
    """Test build_agent_spec function."""

    def test_minimal_spec(self):
        """Build spec with minimal args."""
        spec = build_agent_spec(
            name="test-agent",
            description="A test agent.",
        )

        assert spec["type"] == "object"
        assert spec["description"] == "A test agent."
        assert "answer" in spec["properties"]
        assert spec["required"] == ["answer"]
        assert spec["json_schema_extra"]["kind"] == "agent"
        assert spec["json_schema_extra"]["name"] == "test-agent"
        assert spec["json_schema_extra"]["version"] == "1.0.0"

    def test_default_tools(self):
        """Default tools should include search_rem and register_metadata."""
        spec = build_agent_spec(
            name="test-agent",
            description="A test agent.",
        )

        tool_names = [t["name"] for t in spec["json_schema_extra"]["tools"]]
        assert "search_rem" in tool_names
        assert "register_metadata" in tool_names

    def test_custom_properties(self):
        """Build spec with custom properties."""
        spec = build_agent_spec(
            name="sentiment-bot",
            description="Analyze sentiment.",
            properties={
                "answer": {"type": "string"},
                "sentiment": {"type": "string", "enum": ["positive", "negative"]},
            },
            required=["answer", "sentiment"],
        )

        assert "sentiment" in spec["properties"]
        assert spec["required"] == ["answer", "sentiment"]

    def test_custom_tools(self):
        """Build spec with custom tools."""
        spec = build_agent_spec(
            name="custom-agent",
            description="Custom agent.",
            tools=["search_rem", "my_custom_tool"],
        )

        tool_names = [t["name"] for t in spec["json_schema_extra"]["tools"]]
        assert "my_custom_tool" in tool_names

    def test_tags(self):
        """Build spec with tags."""
        spec = build_agent_spec(
            name="tagged-agent",
            description="Agent with tags.",
            tags=["nlp", "analysis"],
        )

        assert spec["json_schema_extra"]["tags"] == ["nlp", "analysis"]


class TestDefaultTools:
    """Test DEFAULT_TOOLS constant."""

    def test_default_tools_content(self):
        """DEFAULT_TOOLS should have required tools."""
        assert "search_rem" in DEFAULT_TOOLS
        assert "register_metadata" in DEFAULT_TOOLS


# Integration tests (require database)
@pytest.mark.asyncio
@pytest.mark.integration
class TestAgentManagerIntegration:
    """Integration tests requiring database."""

    async def test_save_and_get_agent(self):
        """Save an agent and retrieve it."""
        user_id = "test-user-123"

        # Save
        result = await save_agent(
            name="test-save-get-agent",
            description="Test agent for save/get.",
            user_id=user_id,
        )
        assert result["status"] == "success"
        assert result["agent_name"] == "test-save-get-agent"

        # Get
        spec = await get_agent("test-save-get-agent", user_id=user_id)
        assert spec is not None
        assert spec["description"] == "Test agent for save/get."

        # Cleanup
        await delete_agent("test-save-get-agent", user_id=user_id)

    async def test_list_agents(self):
        """List user's agents."""
        user_id = "test-user-list"

        # Save a test agent
        await save_agent(
            name="test-list-agent",
            description="Test agent for listing.",
            user_id=user_id,
        )

        # List
        agents = await list_agents(user_id=user_id, include_system=False)
        agent_names = [a["name"] for a in agents]
        assert "test-list-agent" in agent_names

        # Cleanup
        await delete_agent("test-list-agent", user_id=user_id)

    async def test_delete_agent(self):
        """Delete an agent."""
        user_id = "test-user-delete"

        # Save
        await save_agent(
            name="test-delete-agent",
            description="Test agent for deletion.",
            user_id=user_id,
        )

        # Delete
        result = await delete_agent("test-delete-agent", user_id=user_id)
        assert result["status"] == "success"

        # Verify deleted
        spec = await get_agent("test-delete-agent", user_id=user_id)
        assert spec is None

    async def test_cannot_delete_other_users_agent(self):
        """Cannot delete another user's agent."""
        user1 = "test-user-1"
        user2 = "test-user-2"

        # User1 saves agent
        await save_agent(
            name="user1-private-agent",
            description="User1's agent.",
            user_id=user1,
        )

        # User2 tries to delete it
        result = await delete_agent("user1-private-agent", user_id=user2)
        assert result["status"] == "error"

        # Cleanup
        await delete_agent("user1-private-agent", user_id=user1)
