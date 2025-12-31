"""
Tests for resource-to-tool conversion.

Resources declared in agent YAML become callable tools automatically.
This eliminates the artificial MCP distinction between tools and resources.
"""

import pytest
from rem.agentic.mcp.tool_wrapper import create_resource_tool


class TestCreateResourceTool:
    """Test create_resource_tool function."""

    def test_concrete_uri_creates_no_param_tool(self):
        """Concrete URIs become tools with no parameters."""
        tool = create_resource_tool("rem://agents", "List all agents")

        assert tool.name == "get_rem_agents"
        assert "List all agents" in (tool.description or "")

    def test_template_uri_creates_parameterized_tool(self):
        """Template URIs become tools with extracted parameters."""
        tool = create_resource_tool(
            "patient-profile://field/{field_key}",
            "Get field definition"
        )

        # Clean tool name with _by_{params} suffix for parameterized tools
        assert tool.name == "get_patient_profile_field_by_field_key"
        assert "{" not in tool.name  # No template chars in name

        # Check function has annotations for parameters
        annotations = tool.function.__annotations__
        assert "field_key" in annotations

    def test_template_uri_multiple_params(self):
        """Template URIs with multiple variables create multi-param tools."""
        tool = create_resource_tool(
            "api://endpoint/{api_id}/{method}/{path}",
            "Get endpoint details"
        )

        assert tool.name == "get_api_endpoint_by_api_id_method_path"

        # Check function has annotations for all parameters
        annotations = tool.function.__annotations__
        assert "api_id" in annotations
        assert "method" in annotations
        assert "path" in annotations

    def test_query_param_uri_is_concrete(self):
        """URIs with query params (no templates) are concrete."""
        tool = create_resource_tool(
            "rem://resources?category=drug.psychotropic.*",
            "Psychotropic medications"
        )

        # Tool should be created successfully
        assert tool.name is not None
        # Description should include the usage
        assert "Psychotropic" in (tool.description or "")

    def test_tool_name_sanitization(self):
        """Tool names are sanitized for OpenAI compatibility."""
        tool = create_resource_tool(
            "patient-profile://field/{field_key}",
            "Get field"
        )

        # Name should only contain alphanumeric, underscore, hyphen
        import re
        assert re.match(r'^[a-zA-Z0-9_-]+$', tool.name)

    def test_description_includes_param_info(self):
        """Template tools include parameter info in description."""
        tool = create_resource_tool(
            "resource://{param1}/{param2}",
            "Base description"
        )

        desc = tool.description or ""
        assert "param1" in desc
        assert "param2" in desc


@pytest.mark.asyncio
class TestResourceToolExecution:
    """Test that resource tools actually work when called."""

    async def test_concrete_tool_calls_load_resource(self, mocker):
        """Concrete tools call load_resource with the URI."""
        mock_load = mocker.patch(
            "rem.api.mcp_router.resources.load_resource",
            return_value={"schemas": ["agent1", "agent2"]}
        )

        tool = create_resource_tool("rem://agents", "List agents")

        # Get the wrapper function and call it
        result = await tool.function()

        mock_load.assert_called_once_with("rem://agents")
        assert "agent1" in result

    async def test_template_tool_substitutes_params(self, mocker):
        """Template tools substitute parameters into URI."""
        mock_load = mocker.patch(
            "rem.api.mcp_router.resources.load_resource",
            return_value={"field": "safety.suicidality", "type": "enum"}
        )

        tool = create_resource_tool(
            "patient-profile://field/{field_key}",
            "Get field"
        )

        # Call with parameter
        result = await tool.function(field_key="safety.suicidality")

        # Should substitute the parameter
        mock_load.assert_called_once_with("patient-profile://field/safety.suicidality")
        assert "safety.suicidality" in result

    async def test_template_tool_missing_param_returns_error(self, mocker):
        """Template tools return error when required param is missing."""
        tool = create_resource_tool(
            "resource://{required_param}",
            "Needs param"
        )

        # Call without required parameter
        result = await tool.function()

        assert "error" in result
        assert "required_param" in result
