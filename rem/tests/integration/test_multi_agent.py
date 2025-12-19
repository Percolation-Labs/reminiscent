"""
Integration tests for multi-agent context propagation and ask_agent tool.

Tests:
1. Context propagation via ContextVar
2. ask_agent tool with context inheritance
3. Nested agent calls (agent calling another agent)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from rem.agentic.context import (
    AgentContext,
    get_current_context,
    set_current_context,
    agent_context_scope,
)


class TestContextPropagation:
    """Test ContextVar-based context propagation."""

    def test_get_current_context_returns_none_when_not_set(self):
        """When no context is set, get_current_context returns None."""
        # Clear any existing context
        set_current_context(None)
        assert get_current_context() is None

    def test_set_and_get_current_context(self):
        """Can set and retrieve context via ContextVar."""
        context = AgentContext(
            user_id="test-user-123",
            tenant_id="test-tenant",
            session_id="session-456",
        )

        set_current_context(context)
        try:
            retrieved = get_current_context()
            assert retrieved is not None
            assert retrieved.user_id == "test-user-123"
            assert retrieved.tenant_id == "test-tenant"
            assert retrieved.session_id == "session-456"
        finally:
            set_current_context(None)

    def test_agent_context_scope_sets_and_restores(self):
        """agent_context_scope context manager properly sets and restores context."""
        # Set initial context
        initial_context = AgentContext(user_id="initial-user")
        set_current_context(initial_context)

        try:
            # Use scope with new context
            new_context = AgentContext(
                user_id="scoped-user",
                session_id="scoped-session",
            )

            with agent_context_scope(new_context):
                current = get_current_context()
                assert current is not None
                assert current.user_id == "scoped-user"
                assert current.session_id == "scoped-session"

            # After scope, original context should be restored
            restored = get_current_context()
            assert restored is not None
            assert restored.user_id == "initial-user"
        finally:
            set_current_context(None)

    def test_nested_context_scopes(self):
        """Nested context scopes properly stack and unstack."""
        set_current_context(None)

        ctx1 = AgentContext(user_id="level-1")
        ctx2 = AgentContext(user_id="level-2")
        ctx3 = AgentContext(user_id="level-3")

        with agent_context_scope(ctx1):
            assert get_current_context().user_id == "level-1"

            with agent_context_scope(ctx2):
                assert get_current_context().user_id == "level-2"

                with agent_context_scope(ctx3):
                    assert get_current_context().user_id == "level-3"

                # Back to level 2
                assert get_current_context().user_id == "level-2"

            # Back to level 1
            assert get_current_context().user_id == "level-1"

        # Back to None
        assert get_current_context() is None


class TestChildContext:
    """Test AgentContext.child_context() method."""

    def test_child_context_inherits_fields(self):
        """child_context inherits user_id, tenant_id, session_id, is_eval."""
        parent = AgentContext(
            user_id="parent-user",
            tenant_id="parent-tenant",
            session_id="parent-session",
            default_model="gpt-4",
            is_eval=True,
            agent_schema_uri="parent-agent",
        )

        child = parent.child_context(agent_schema_uri="child-agent")

        assert child.user_id == "parent-user"
        assert child.tenant_id == "parent-tenant"
        assert child.session_id == "parent-session"
        assert child.default_model == "gpt-4"
        assert child.is_eval is True
        assert child.agent_schema_uri == "child-agent"

    def test_child_context_can_override_model(self):
        """child_context can override default_model."""
        parent = AgentContext(
            user_id="user",
            default_model="gpt-4",
        )

        child = parent.child_context(
            agent_schema_uri="child",
            model_override="claude-3",
        )

        assert child.default_model == "claude-3"
        assert parent.default_model == "gpt-4"  # Parent unchanged


class TestAskAgentContextInheritance:
    """Test that ask_agent tool inherits context from parent."""

    @pytest.mark.asyncio
    async def test_ask_agent_inherits_parent_context(self):
        """ask_agent should inherit user_id, session_id from parent context."""
        from rem.api.mcp_router.tools import ask_agent

        # Set up parent context
        parent_context = AgentContext(
            user_id="parent-user-id",
            tenant_id="parent-tenant",
            session_id="parent-session-id",
            is_eval=True,
        )

        # Mock the agent creation and execution
        mock_result = MagicMock()
        mock_result.output = {"answer": "test response"}

        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=mock_result)

        with agent_context_scope(parent_context):
            # Patch where the imports happen (inside the function)
            with patch("rem.agentic.create_agent", new_callable=AsyncMock) as mock_create:
                with patch("rem.utils.schema_loader.load_agent_schema") as mock_load:
                    with patch("rem.agentic.agents.agent_manager.get_agent", new_callable=AsyncMock) as mock_get:
                        mock_create.return_value = mock_runtime
                        mock_get.return_value = None  # Not in database
                        mock_load.return_value = {
                            "type": "object",
                            "description": "Test agent",
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                        }

                        result = await ask_agent(
                            agent_name="test-agent",
                            input_text="Hello",
                        )

                        # Verify create_agent was called with inherited context
                        call_args = mock_create.call_args
                        child_context = call_args.kwargs.get("context")

                        assert child_context is not None
                        assert child_context.user_id == "parent-user-id"
                        assert child_context.tenant_id == "parent-tenant"
                        assert child_context.session_id == "parent-session-id"
                        assert child_context.is_eval is True
                        assert child_context.agent_schema_uri == "test-agent"

    @pytest.mark.asyncio
    async def test_ask_agent_without_parent_context(self):
        """ask_agent should work without parent context (backwards compatible)."""
        from rem.api.mcp_router.tools import ask_agent

        # Ensure no parent context
        set_current_context(None)

        mock_result = MagicMock()
        mock_result.output = {"answer": "test"}

        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=mock_result)

        with patch("rem.agentic.create_agent", new_callable=AsyncMock) as mock_create:
            with patch("rem.utils.schema_loader.load_agent_schema") as mock_load:
                with patch("rem.agentic.agents.agent_manager.get_agent", new_callable=AsyncMock) as mock_get:
                    mock_create.return_value = mock_runtime
                    mock_get.return_value = None  # Not in database
                    mock_load.return_value = {
                        "type": "object",
                        "description": "Test",
                        "properties": {"answer": {"type": "string"}},
                        "required": ["answer"],
                    }

                    result = await ask_agent(
                        agent_name="test-agent",
                        input_text="Hello",
                    )

                    assert result["status"] == "success"


class TestRegisterMetadataAgentSchema:
    """Test that register_metadata auto-populates agent_schema from context."""

    @pytest.mark.asyncio
    async def test_register_metadata_gets_agent_schema_from_context(self):
        """register_metadata should auto-populate agent_schema from context."""
        from rem.api.mcp_router.tools import register_metadata

        context = AgentContext(
            user_id="user",
            agent_schema_uri="my-custom-agent",
        )

        with agent_context_scope(context):
            result = await register_metadata(
                confidence=0.95,
                sources=["test-source"],
            )

            assert result["status"] == "success"
            assert result["agent_schema"] == "my-custom-agent"
            assert result["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_register_metadata_explicit_schema_overrides_context(self):
        """Explicit agent_schema parameter should override context."""
        from rem.api.mcp_router.tools import register_metadata

        context = AgentContext(
            user_id="user",
            agent_schema_uri="context-agent",
        )

        with agent_context_scope(context):
            result = await register_metadata(
                confidence=0.9,
                agent_schema="explicit-agent",
            )

            assert result["agent_schema"] == "explicit-agent"

    @pytest.mark.asyncio
    async def test_register_metadata_without_context(self):
        """register_metadata should work without context (agent_schema=None)."""
        from rem.api.mcp_router.tools import register_metadata

        set_current_context(None)

        result = await register_metadata(confidence=0.8)

        assert result["status"] == "success"
        assert result["agent_schema"] is None


class TestAskRemAgentContextInheritance:
    """Test that existing ask_rem_agent also inherits context."""

    @pytest.mark.asyncio
    async def test_ask_rem_agent_inherits_context(self):
        """ask_rem_agent should inherit parent context."""
        from rem.api.mcp_router.tools import ask_rem_agent

        parent_context = AgentContext(
            user_id="rem-parent-user",
            session_id="rem-session",
            tenant_id="rem-tenant",
        )

        mock_result = MagicMock()
        mock_result.output = "test output"

        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=mock_result)

        with agent_context_scope(parent_context):
            with patch("rem.agentic.create_agent", new_callable=AsyncMock) as mock_create:
                with patch("rem.utils.schema_loader.load_agent_schema") as mock_load:
                    mock_create.return_value = mock_runtime
                    mock_load.return_value = {
                        "type": "object",
                        "description": "Ask REM",
                        "properties": {},
                        "required": [],
                    }

                    await ask_rem_agent(query="test query")

                    call_args = mock_create.call_args
                    child_context = call_args.kwargs.get("context")

                    assert child_context.user_id == "rem-parent-user"
                    assert child_context.session_id == "rem-session"
                    assert child_context.tenant_id == "rem-tenant"
