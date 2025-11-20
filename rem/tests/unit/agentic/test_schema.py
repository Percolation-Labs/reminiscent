"""
Tests for agent schema protocol.
"""

import pytest
from pydantic import ValidationError

from rem.agentic.schema import (
    AgentSchema,
    AgentSchemaMetadata,
    MCPToolReference,
    MCPResourceReference,
    validate_agent_schema,
    create_agent_schema,
)


def test_mcp_tool_reference():
    """Test MCPToolReference model."""
    tool = MCPToolReference(
        name="lookup_entity",
        mcp_server="rem",
        description="Lookup entities by key"
    )

    assert tool.name == "lookup_entity"
    assert tool.mcp_server == "rem"
    assert tool.description == "Lookup entities by key"


def test_mcp_tool_reference_without_description():
    """Test MCPToolReference with optional description."""
    tool = MCPToolReference(
        name="search",
        mcp_server="rem"
    )

    assert tool.name == "search"
    assert tool.mcp_server == "rem"
    assert tool.description is None


def test_mcp_resource_reference():
    """Test MCPResourceReference model."""
    resource = MCPResourceReference(
        uri_pattern="rem://resources/.*",
        mcp_server="rem"
    )

    assert resource.uri_pattern == "rem://resources/.*"
    assert resource.mcp_server == "rem"


def test_agent_schema_metadata_minimal():
    """Test AgentSchemaMetadata with minimal fields."""
    metadata = AgentSchemaMetadata(
        fully_qualified_name="rem.agents.TestAgent"
    )

    assert metadata.fully_qualified_name == "rem.agents.TestAgent"
    assert metadata.name is None
    assert metadata.version is None
    assert metadata.tools == []
    assert metadata.resources == []


def test_agent_schema_metadata_complete():
    """Test AgentSchemaMetadata with all fields."""
    metadata = AgentSchemaMetadata(
        fully_qualified_name="rem.agents.QueryAgent",
        name="Query Agent",
        short_name="query-agent",
        version="1.0.0",
        tools=[
            {"name": "lookup", "mcp_server": "rem"},
            {"name": "search", "mcp_server": "rem", "description": "Semantic search"}
        ],
        resources=[
            {"uri_pattern": "rem://.*", "mcp_server": "rem"}
        ],
        tags=["query", "knowledge-graph"],
        author="REM Team"
    )

    assert metadata.fully_qualified_name == "rem.agents.QueryAgent"
    assert metadata.name == "Query Agent"
    assert metadata.short_name == "query-agent"
    assert metadata.version == "1.0.0"
    assert len(metadata.tools) == 2
    assert len(metadata.resources) == 1
    assert metadata.tags == ["query", "knowledge-graph"]
    assert metadata.author == "REM Team"


def test_agent_schema_minimal():
    """Test AgentSchema with minimal required fields."""
    schema = AgentSchema(
        description="You are a test agent.",
        properties={
            "answer": {"type": "string", "description": "The answer"}
        },
        required=["answer"],
        json_schema_extra=AgentSchemaMetadata(
            fully_qualified_name="rem.agents.TestAgent"
        )
    )

    assert schema.type == "object"
    assert schema.description == "You are a test agent."
    assert "answer" in schema.properties
    assert schema.required == ["answer"]
    assert schema.json_schema_extra.fully_qualified_name == "rem.agents.TestAgent"


def test_agent_schema_complete():
    """Test AgentSchema with all fields."""
    schema = AgentSchema(
        type="object",
        title="Query Agent",
        description="You are a query agent that answers questions.",
        properties={
            "answer": {"type": "string", "description": "Answer"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        required=["answer", "confidence"],
        json_schema_extra=AgentSchemaMetadata(
            fully_qualified_name="rem.agents.QueryAgent",
            version="1.0.0",
            tools=[{"name": "lookup", "mcp_server": "rem"}]
        ),
        additionalProperties=False
    )

    assert schema.type == "object"
    assert schema.title == "Query Agent"
    assert len(schema.properties) == 2
    assert schema.required == ["answer", "confidence"]
    assert schema.json_schema_extra.version == "1.0.0"
    assert len(schema.json_schema_extra.tools) == 1
    assert schema.additionalProperties is False


def test_validate_agent_schema():
    """Test validate_agent_schema function."""
    schema_dict = {
        "type": "object",
        "description": "Test agent",
        "properties": {
            "result": {"type": "string"}
        },
        "required": ["result"],
        "json_schema_extra": {
            "fully_qualified_name": "rem.agents.Test"
        }
    }

    validated = validate_agent_schema(schema_dict)

    assert isinstance(validated, AgentSchema)
    assert validated.description == "Test agent"
    assert validated.json_schema_extra.fully_qualified_name == "rem.agents.Test"


def test_validate_agent_schema_invalid():
    """Test validate_agent_schema with invalid schema."""
    # Missing required fields
    invalid_schema = {
        "type": "object"
        # Missing description, properties, json_schema_extra
    }

    with pytest.raises(ValidationError):
        validate_agent_schema(invalid_schema)


def test_create_agent_schema():
    """Test create_agent_schema helper function."""
    schema = create_agent_schema(
        description="You are a helpful assistant.",
        properties={
            "answer": {"type": "string", "description": "Answer"},
            "sources": {"type": "array", "items": {"type": "string"}}
        },
        required=["answer"],
        fully_qualified_name="rem.agents.Assistant",
        tools=[{"name": "search", "mcp_server": "rem"}],
        resources=[{"uri_pattern": "rem://.*", "mcp_server": "rem"}],
        version="1.0.0"
    )

    assert isinstance(schema, AgentSchema)
    assert schema.description == "You are a helpful assistant."
    assert len(schema.properties) == 2
    assert schema.required == ["answer"]
    assert schema.json_schema_extra.fully_qualified_name == "rem.agents.Assistant"
    assert schema.json_schema_extra.version == "1.0.0"
    assert len(schema.json_schema_extra.tools) == 1
    assert len(schema.json_schema_extra.resources) == 1


def test_create_agent_schema_with_extra_fields():
    """Test create_agent_schema with additional JSON Schema fields."""
    schema = create_agent_schema(
        description="Test agent",
        properties={"result": {"type": "string"}},
        required=["result"],
        fully_qualified_name="rem.agents.Test",
        title="Test Agent",
        definitions={"EntityKey": {"type": "string", "pattern": "^[a-z0-9-]+$"}}
    )

    assert schema.title == "Test Agent"
    assert schema.definitions == {"EntityKey": {"type": "string", "pattern": "^[a-z0-9-]+$"}}


def test_agent_schema_serialization():
    """Test serializing AgentSchema to dict."""
    schema = create_agent_schema(
        description="Test agent",
        properties={"answer": {"type": "string"}},
        required=["answer"],
        fully_qualified_name="rem.agents.Test",
        version="1.0.0"
    )

    # Serialize to dict
    schema_dict = schema.model_dump(exclude_none=True)

    assert schema_dict["type"] == "object"
    assert schema_dict["description"] == "Test agent"
    assert "answer" in schema_dict["properties"]
    assert schema_dict["json_schema_extra"]["fully_qualified_name"] == "rem.agents.Test"
    assert schema_dict["json_schema_extra"]["version"] == "1.0.0"

    # Should be able to validate it back
    roundtrip = validate_agent_schema(schema_dict)
    assert roundtrip.description == schema.description
