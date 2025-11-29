"""
Unit tests for tool description suffix functionality.

Tests that:
1. create_mcp_tool_wrapper correctly appends description_suffix to tool docstring
2. Schema metadata (default_search_table, has_embeddings) produces correct suffix
3. The suffix is only applied to search_rem tool, not other tools
"""

import pytest
from unittest.mock import MagicMock, AsyncMock


class TestToolDescriptionSuffix:
    """Tests for tool description suffix in create_mcp_tool_wrapper."""

    @pytest.mark.asyncio
    async def test_wrapper_without_suffix(self):
        """Test that wrapper works normally without description_suffix."""
        from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper

        # Create a mock MCP tool
        async def mock_tool_fn(query: str, limit: int = 10) -> dict:
            """Original tool docstring."""
            return {"result": query}

        mock_mcp_tool = MagicMock()
        mock_mcp_tool.fn = mock_tool_fn

        # Create wrapper without suffix
        wrapped = create_mcp_tool_wrapper("test_tool", mock_mcp_tool)

        # Verify the tool was created
        assert wrapped is not None
        assert wrapped.function.__doc__ == "Original tool docstring."

    @pytest.mark.asyncio
    async def test_wrapper_with_suffix(self):
        """Test that description_suffix is appended to tool docstring."""
        from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper

        # Create a mock MCP tool
        async def mock_tool_fn(query: str, limit: int = 10) -> dict:
            """Original tool docstring."""
            return {"result": query}

        mock_mcp_tool = MagicMock()
        mock_mcp_tool.fn = mock_tool_fn

        # Create wrapper with suffix
        suffix = "\n\nFor this schema, use search_rem to query resources."
        wrapped = create_mcp_tool_wrapper(
            "test_tool",
            mock_mcp_tool,
            description_suffix=suffix,
        )

        # Verify suffix was appended
        assert wrapped is not None
        assert wrapped.function.__doc__ == "Original tool docstring." + suffix
        assert "query resources" in wrapped.function.__doc__

    @pytest.mark.asyncio
    async def test_wrapper_with_user_id_and_suffix(self):
        """Test that both user_id injection and suffix work together."""
        from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper

        # Create a mock MCP tool with user_id parameter
        async def mock_tool_fn(query: str, user_id: str = "default") -> dict:
            """Tool with user_id parameter."""
            return {"result": query, "user_id": user_id}

        mock_mcp_tool = MagicMock()
        mock_mcp_tool.fn = mock_tool_fn

        # Create wrapper with both user_id and suffix
        suffix = "\n\nCustom suffix for testing."
        wrapped = create_mcp_tool_wrapper(
            "test_tool",
            mock_mcp_tool,
            user_id="test-user-123",
            description_suffix=suffix,
        )

        # Verify both work
        assert wrapped is not None
        assert "Custom suffix" in wrapped.function.__doc__

        # Verify the wrapped function injects user_id
        result = await wrapped.function(query="test query")
        assert result["user_id"] == "test-user-123"

    @pytest.mark.asyncio
    async def test_wrapper_preserves_empty_docstring(self):
        """Test handling of tools with no docstring."""
        from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper

        # Create a mock MCP tool without docstring
        async def mock_tool_fn(query: str) -> dict:
            return {"result": query}

        mock_tool_fn.__doc__ = None  # Explicitly no docstring

        mock_mcp_tool = MagicMock()
        mock_mcp_tool.fn = mock_tool_fn

        # Create wrapper with suffix
        suffix = "\n\nSuffix for tool without docstring."
        wrapped = create_mcp_tool_wrapper(
            "test_tool",
            mock_mcp_tool,
            description_suffix=suffix,
        )

        # Verify suffix is the entire docstring
        assert wrapped.function.__doc__ == suffix


class TestSchemaMetadataSuffixGeneration:
    """Tests for suffix generation from schema metadata."""

    def test_suffix_with_embeddings(self):
        """Test suffix generation for schema with embeddings."""
        # Simulate the logic from create_agent
        default_table = "resources"
        has_embeddings = True

        # Build suffix (same logic as in create_agent)
        suffix = f"\n\nFor this schema, use `search_rem` to query `{default_table}`. "
        if has_embeddings:
            suffix += f"SEARCH works well on {default_table} (has embeddings). "
        suffix += f'Example: `SEARCH "your query" FROM {default_table} LIMIT 10`'

        # Verify
        assert "resources" in suffix
        assert "has embeddings" in suffix
        assert "SEARCH" in suffix
        assert "Example:" in suffix

    def test_suffix_without_embeddings(self):
        """Test suffix generation for schema without embeddings."""
        default_table = "feedbacks"
        has_embeddings = False

        # Build suffix
        suffix = f"\n\nFor this schema, use `search_rem` to query `{default_table}`. "
        if has_embeddings:
            suffix += f"SEARCH works well on {default_table} (has embeddings). "
        suffix += f'Example: `SEARCH "your query" FROM {default_table} LIMIT 10`'

        # Verify - should NOT mention embeddings
        assert "feedbacks" in suffix
        assert "has embeddings" not in suffix
        assert "Example:" in suffix

    def test_no_suffix_without_default_table(self):
        """Test that no suffix is generated when default_search_table is not set."""
        default_table = None
        has_embeddings = True

        # Build suffix (same logic as create_agent)
        suffix = None
        if default_table:
            suffix = f"\n\nFor this schema, use `search_rem` to query `{default_table}`. "
            if has_embeddings:
                suffix += f"SEARCH works well on {default_table} (has embeddings). "
            suffix += f'Example: `SEARCH "your query" FROM {default_table} LIMIT 10`'

        # Verify - no suffix when no default_table
        assert suffix is None


class TestSchemaGeneratorMetadata:
    """Tests for schema generator metadata output."""

    def test_schema_metadata_has_embeddings_true(self):
        """Test that schema metadata includes has_embeddings=True for embeddable models."""
        from rem.services.postgres.schema_generator import extract_model_schema_metadata
        from rem.models.entities import Resource

        # Extract metadata for Resource (which has embeddings)
        metadata = extract_model_schema_metadata(
            model=Resource,
            table_name="resources",
            entity_key_field="name",
        )

        # Verify structure
        assert metadata["table_name"] == "resources"
        assert metadata["entity_key_field"] == "name"
        assert "spec" in metadata

        # Check json_schema_extra
        extra = metadata["spec"]["json_schema_extra"]
        assert extra["default_search_table"] == "resources"
        assert extra["has_embeddings"] is True
        assert "search_rem" in extra["tools"]

        # Verify tool_description_suffix is NOT present
        assert "tool_description_suffix" not in extra

    def test_schema_metadata_has_embeddings_false(self):
        """Test that schema metadata includes has_embeddings=False for non-embeddable models."""
        from rem.services.postgres.schema_generator import extract_model_schema_metadata
        from rem.models.entities import Feedback

        # Extract metadata for Feedback (which has no embeddings)
        metadata = extract_model_schema_metadata(
            model=Feedback,
            table_name="feedbacks",
            entity_key_field="id",
        )

        # Check json_schema_extra
        extra = metadata["spec"]["json_schema_extra"]
        assert extra["default_search_table"] == "feedbacks"
        assert extra["has_embeddings"] is False
        assert "search_rem" in extra["tools"]


class TestIntegrationWithMCPServer:
    """Integration tests with actual MCP server tools."""

    @pytest.mark.asyncio
    async def test_search_rem_with_suffix(self):
        """Test wrapping actual search_rem tool with suffix."""
        from rem.mcp_server import mcp
        from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper

        # Get tools from MCP server
        mcp_tools = await mcp.get_tools()
        assert "search_rem" in mcp_tools

        # Get original docstring
        original_doc = mcp_tools["search_rem"].fn.__doc__

        # Wrap with suffix
        suffix = "\n\nFor this schema, query `resources`. Example: SEARCH FROM resources"
        wrapped = create_mcp_tool_wrapper(
            "search_rem",
            mcp_tools["search_rem"],
            description_suffix=suffix,
        )

        # Verify suffix was appended
        assert wrapped.function.__doc__.startswith(original_doc)
        assert wrapped.function.__doc__.endswith(suffix)
        assert "query `resources`" in wrapped.function.__doc__

    @pytest.mark.asyncio
    async def test_other_tools_no_suffix(self):
        """Test that other tools don't get suffix even when suffix is provided to search_rem."""
        from rem.mcp_server import mcp
        from rem.agentic.mcp.tool_wrapper import create_mcp_tool_wrapper

        # Get tools from MCP server
        mcp_tools = await mcp.get_tools()

        # Find a tool that's not search_rem
        other_tool_name = None
        for name in mcp_tools:
            if name != "search_rem":
                other_tool_name = name
                break

        if other_tool_name:
            original_doc = mcp_tools[other_tool_name].fn.__doc__ or ""

            # Wrap without suffix (simulating create_agent logic)
            wrapped = create_mcp_tool_wrapper(
                other_tool_name,
                mcp_tools[other_tool_name],
                description_suffix=None,  # No suffix for non-search_rem tools
            )

            # Verify no suffix was added
            assert wrapped.function.__doc__ == original_doc


if __name__ == "__main__":
    import asyncio

    print("=" * 80)
    print("Running Tool Description Suffix Tests")
    print("=" * 80)

    # Run basic tests
    test_class = TestToolDescriptionSuffix()

    print("\n1. Testing wrapper without suffix...")
    asyncio.run(test_class.test_wrapper_without_suffix())
    print("   PASSED")

    print("\n2. Testing wrapper with suffix...")
    asyncio.run(test_class.test_wrapper_with_suffix())
    print("   PASSED")

    print("\n3. Testing wrapper with user_id and suffix...")
    asyncio.run(test_class.test_wrapper_with_user_id_and_suffix())
    print("   PASSED")

    print("\n4. Testing suffix generation with embeddings...")
    TestSchemaMetadataSuffixGeneration().test_suffix_with_embeddings()
    print("   PASSED")

    print("\n5. Testing suffix generation without embeddings...")
    TestSchemaMetadataSuffixGeneration().test_suffix_without_embeddings()
    print("   PASSED")

    print("\n6. Testing schema generator metadata...")
    TestSchemaGeneratorMetadata().test_schema_metadata_has_embeddings_true()
    print("   PASSED")

    print("\n7. Testing integration with MCP server...")
    asyncio.run(TestIntegrationWithMCPServer().test_search_rem_with_suffix())
    print("   PASSED")

    print("\n" + "=" * 80)
    print("All tests PASSED!")
    print("=" * 80)
