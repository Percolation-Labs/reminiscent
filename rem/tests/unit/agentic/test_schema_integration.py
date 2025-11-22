"""
Integration tests for agent schema protocol with real agent schemas.
"""

import yaml
import pytest
from pathlib import Path

from rem.agentic.schema import validate_agent_schema


@pytest.fixture
def query_agent_schema_path():
    """Path to query agent schema."""
    return Path(__file__).parent.parent.parent / "data" / "schemas" / "agents" / "query_agent.yaml"


@pytest.fixture
def summarization_agent_schema_path():
    """Path to summarization agent schema."""
    return Path(__file__).parent.parent.parent / "data" / "schemas" / "agents" / "summarization_agent.yaml"


def test_validate_query_agent_schema(query_agent_schema_path):
    """Test validating real query agent schema."""
    with open(query_agent_schema_path) as f:
        schema_dict = yaml.safe_load(f)

    # Validate schema structure
    validated = validate_agent_schema(schema_dict)

    # Check core fields
    assert validated.type == "object"
    assert "REM Query Agent" in validated.description
    assert validated.json_schema_extra.name == "query"

    # Check output properties
    assert "answer" in validated.properties
    assert "confidence" in validated.properties
    assert "sources" in validated.properties
    assert "reasoning" in validated.properties

    # Check required fields
    assert "answer" in validated.required
    assert "confidence" in validated.required
    assert "sources" in validated.required

    # Check tools
    assert len(validated.json_schema_extra.tools) == 4
    tool_names = [t.name for t in validated.json_schema_extra.tools]
    assert "lookup_entity" in tool_names
    assert "fuzzy_search" in tool_names
    assert "semantic_search" in tool_names
    assert "traverse_graph" in tool_names

    # All tools should use rem MCP server
    for tool in validated.json_schema_extra.tools:
        assert tool.mcp_server == "rem"

    # Check resources
    assert len(validated.json_schema_extra.resources) == 2
    resource_patterns = [r.uri_pattern for r in validated.json_schema_extra.resources]
    assert "rem://resources/.*" in resource_patterns
    assert "rem://moments/.*" in resource_patterns


def test_validate_summarization_agent_schema(summarization_agent_schema_path):
    """Test validating real summarization agent schema."""
    with open(summarization_agent_schema_path) as f:
        schema_dict = yaml.safe_load(f)

    # Validate schema structure
    validated = validate_agent_schema(schema_dict)

    # Check core fields
    assert validated.type == "object"
    assert "Summarization Agent" in validated.description
    assert validated.json_schema_extra.name == "summarization"

    # Check output properties
    assert "summary" in validated.properties
    assert "key_points" in validated.properties
    assert "action_items" in validated.properties
    assert "related_entities" in validated.properties

    # Check required fields
    assert "summary" in validated.required
    assert "key_points" in validated.required
    assert "related_entities" in validated.required

    # Check tools
    assert len(validated.json_schema_extra.tools) == 2
    tool_names = [t.name for t in validated.json_schema_extra.tools]
    assert "lookup_entity" in tool_names
    assert "traverse_graph" in tool_names

    # Check resources
    assert len(validated.json_schema_extra.resources) == 1
    assert validated.json_schema_extra.resources[0].uri_pattern == "rem://.*"


def test_schema_roundtrip(query_agent_schema_path):
    """Test loading, validating, and serializing schema."""
    # Load original
    with open(query_agent_schema_path) as f:
        original = yaml.safe_load(f)

    # Validate
    validated = validate_agent_schema(original)

    # Serialize back to dict
    serialized = validated.model_dump(exclude_none=True)

    # Key fields should match
    assert serialized["type"] == original["type"]
    assert serialized["description"] == original["description"]
    assert serialized["properties"] == original["properties"]
    assert serialized["required"] == original["required"]

    # Metadata should be preserved
    assert serialized["json_schema_extra"]["name"] == original["json_schema_extra"]["name"]
    assert len(serialized["json_schema_extra"]["tools"]) == len(
        original["json_schema_extra"]["tools"]
    )
    assert len(serialized["json_schema_extra"]["resources"]) == len(
        original["json_schema_extra"]["resources"]
    )


def test_schema_metadata_access(query_agent_schema_path):
    """Test accessing schema metadata through Pydantic models."""
    with open(query_agent_schema_path) as f:
        schema_dict = yaml.safe_load(f)

    validated = validate_agent_schema(schema_dict)

    # Access via dot notation (Pydantic)
    assert validated.json_schema_extra.name == "query"

    # Access tools
    first_tool = validated.json_schema_extra.tools[0]
    assert first_tool.name == "lookup_entity"
    assert first_tool.mcp_server == "rem"
    assert first_tool.description == "Lookup entities by exact key with O(1) performance"

    # Access resources
    first_resource = validated.json_schema_extra.resources[0]
    assert first_resource.uri_pattern == "rem://resources/.*"
    assert first_resource.mcp_server == "rem"


def test_schema_type_validation(query_agent_schema_path):
    """Test that schema validation catches type errors."""
    with open(query_agent_schema_path) as f:
        schema_dict = yaml.safe_load(f)

    # Validate valid schema
    validated = validate_agent_schema(schema_dict)

    # Properties should be a dict
    assert isinstance(validated.properties, dict)

    # Required should be a list
    assert isinstance(validated.required, list)

    # Tools should be list of MCPToolReference
    from rem.agentic.schema import MCPToolReference

    for tool in validated.json_schema_extra.tools:
        assert isinstance(tool, MCPToolReference)
        assert isinstance(tool.name, str)
        assert isinstance(tool.mcp_server, str)
