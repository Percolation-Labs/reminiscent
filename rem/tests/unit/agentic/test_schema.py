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
    MCPServerConfig,
    validate_agent_schema,
    create_agent_schema,
    schema_to_dict,
    schema_from_dict,
    schema_to_yaml,
    schema_from_yaml,
    get_system_prompt,
    get_metadata,
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
        name="TestAgent"
    )

    assert metadata.name == "TestAgent"
    assert metadata.kind is None
    assert metadata.version is None
    assert metadata.tools == []
    assert metadata.resources == []


def test_agent_schema_metadata_complete():
    """Test AgentSchemaMetadata with all fields."""
    metadata = AgentSchemaMetadata(
        name="QueryAgent",
        kind="agent",
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

    assert metadata.name == "QueryAgent"
    assert metadata.kind == "agent"
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
            name="test-agent"
        )
    )

    assert schema.type == "object"
    assert schema.description == "You are a test agent."
    assert "answer" in schema.properties
    assert schema.required == ["answer"]
    assert schema.json_schema_extra.name == "test-agent"


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
            name="query-agent", # Adjusted to match new metadata structure
            kind="agent", # Added kind as it was in the metadata, but not passed here
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
            "name": "test-agent"
        }
    }

    validated = validate_agent_schema(schema_dict)

    assert isinstance(validated, AgentSchema)
    assert validated.description == "Test agent"
    assert validated.json_schema_extra.name == "test-agent"


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
        name="Assistant", # Changed from fully_qualified_name
        kind="agent", # Added for completeness as it was implied
        tools=[{"name": "search", "mcp_server": "rem"}],
        resources=[{"uri_pattern": "rem://.*", "mcp_server": "rem"}],
        version="1.0.0"
    )

    assert isinstance(schema, AgentSchema)
    assert schema.description == "You are a helpful assistant."
    assert len(schema.properties) == 2
    assert schema.required == ["answer"]
    assert schema.json_schema_extra.name == "Assistant" # Changed to name
    assert schema.json_schema_extra.version == "1.0.0"
    assert len(schema.json_schema_extra.tools) == 1
    assert len(schema.json_schema_extra.resources) == 1


def test_create_agent_schema_with_extra_fields():
    """Test create_agent_schema with additional JSON Schema fields."""
    schema = create_agent_schema(
        description="Test agent",
        properties={"result": {"type": "string"}},
        required=["result"],
        name="Test", # Changed from fully_qualified_name
        title="Test Agent",
        definitions={"EntityKey": {"type": "string", "pattern": "^[a-z0-9-]+$"}}
    )

    assert schema.json_schema_extra.name == "Test" # Added assertion
    assert schema.title == "Test Agent"
    assert schema.definitions == {"EntityKey": {"type": "string", "pattern": "^[a-z0-9-]+$"}}


def test_agent_schema_serialization():
    """Test serializing AgentSchema to dict."""
    schema = create_agent_schema(
        description="Test agent",
        properties={"answer": {"type": "string"}},
        required=["answer"],
        name="Test", # Changed from fully_qualified_name
        version="1.0.0"
    )

    # Serialize to dict
    schema_dict = schema.model_dump(exclude_none=True)

    assert schema_dict["type"] == "object"
    assert schema_dict["description"] == "Test agent"
    assert "answer" in schema_dict["properties"]
    assert schema_dict["json_schema_extra"]["name"] == "Test" # Changed from fully_qualified_name
    assert schema_dict["json_schema_extra"]["version"] == "1.0.0"

    # Should be able to validate it back
    roundtrip = validate_agent_schema(schema_dict)
    assert roundtrip.description == schema.description


# =============================================================================
# New tests for system_prompt, mcp_servers, and serialization helpers
# =============================================================================


class TestMCPServerConfig:
    """Tests for MCPServerConfig model."""

    def test_local_server_config(self):
        """Test MCPServerConfig for local/in-process server."""
        config = MCPServerConfig(
            type="local",
            module="rem.mcp_server",
            id="rem-local"
        )

        assert config.type == "local"
        assert config.module == "rem.mcp_server"
        assert config.id == "rem-local"

    def test_server_config_serialization(self):
        """Test MCPServerConfig serializes and deserializes correctly."""
        config = MCPServerConfig(
            type="local",
            module="myapp.mcp",
            id="custom-server"
        )

        # Serialize to dict
        config_dict = config.model_dump()
        assert config_dict["type"] == "local"
        assert config_dict["module"] == "myapp.mcp"

        # Deserialize back
        restored = MCPServerConfig.model_validate(config_dict)
        assert restored.module == config.module


class TestAgentSchemaMetadataNewFields:
    """Tests for new AgentSchemaMetadata fields: system_prompt, structured_output, mcp_servers."""

    def test_system_prompt_field(self):
        """Test system_prompt field in metadata."""
        metadata = AgentSchemaMetadata(
            name="test-agent",
            system_prompt="You are a helpful assistant."
        )

        assert metadata.system_prompt == "You are a helpful assistant."
        assert metadata.structured_output is None  # default is None (auto-detect)

    def test_structured_output_disabled(self):
        """Test structured_output can be disabled."""
        metadata = AgentSchemaMetadata(
            name="free-text-agent",
            structured_output=False
        )

        assert metadata.structured_output is False

    def test_mcp_servers_config(self):
        """Test mcp_servers field for dynamic tool loading."""
        metadata = AgentSchemaMetadata(
            name="agent-with-mcp",
            mcp_servers=[
                MCPServerConfig(type="local", module="rem.mcp_server", id="rem-local"),
            ]
        )

        assert len(metadata.mcp_servers) == 1
        assert metadata.mcp_servers[0].module == "rem.mcp_server"

    def test_full_metadata_with_new_fields(self):
        """Test full metadata with all new fields."""
        metadata = AgentSchemaMetadata(
            name="test-agent",
            kind="agent",
            version="1.0.0",
            system_prompt="Extended instructions here...",
            structured_output=False,
            mcp_servers=[
                {"type": "local", "module": "rem.mcp_server", "id": "rem"}
            ],
            tools=[{"name": "search_rem", "mcp_server": "rem"}],
            override_temperature=0.7,
        )

        assert metadata.system_prompt == "Extended instructions here..."
        assert metadata.structured_output is False
        assert len(metadata.mcp_servers) == 1
        assert metadata.override_temperature == 0.7


class TestGetSystemPrompt:
    """Tests for get_system_prompt helper function."""

    def test_description_only(self):
        """Test with only description (no custom system_prompt)."""
        schema = AgentSchema(
            description="Base description.",
            properties={"answer": {"type": "string"}},
            json_schema_extra={"name": "test"}
        )

        prompt = get_system_prompt(schema)
        assert prompt == "Base description."

    def test_custom_system_prompt(self):
        """Test with custom system_prompt that extends description."""
        schema = AgentSchema(
            description="Short description.",
            properties={"answer": {"type": "string"}},
            json_schema_extra={
                "name": "test",
                "system_prompt": "Extended detailed instructions."
            }
        )

        prompt = get_system_prompt(schema)
        assert "Short description." in prompt
        assert "Extended detailed instructions." in prompt
        # Should be combined with newline separator
        assert prompt == "Short description.\n\nExtended detailed instructions."

    def test_system_prompt_only(self):
        """Test with empty description but custom system_prompt."""
        schema = AgentSchema(
            description="",
            properties={},
            json_schema_extra={
                "name": "test",
                "system_prompt": "Only the custom prompt."
            }
        )

        prompt = get_system_prompt(schema)
        assert prompt == "Only the custom prompt."

    def test_dict_input(self):
        """Test get_system_prompt works with raw dict input."""
        schema_dict = {
            "description": "Base desc.",
            "json_schema_extra": {
                "name": "test",
                "system_prompt": "Custom prompt."
            }
        }

        prompt = get_system_prompt(schema_dict)
        assert "Base desc." in prompt
        assert "Custom prompt." in prompt


class TestGetMetadata:
    """Tests for get_metadata helper function."""

    def test_dict_input(self):
        """Test extracting metadata from dict."""
        schema_dict = {
            "json_schema_extra": {
                "name": "test-agent",
                "system_prompt": "Custom prompt",
                "structured_output": False
            }
        }

        meta = get_metadata(schema_dict)
        assert meta.name == "test-agent"
        assert meta.system_prompt == "Custom prompt"
        assert meta.structured_output is False

    def test_schema_input(self):
        """Test extracting metadata from AgentSchema."""
        schema = AgentSchema(
            description="Test",
            properties={},
            json_schema_extra={
                "name": "schema-agent",
                "mcp_servers": [{"type": "local", "module": "test.mcp", "id": "test"}]
            }
        )

        meta = get_metadata(schema)
        assert meta.name == "schema-agent"
        assert len(meta.mcp_servers) == 1

    def test_already_metadata_object(self):
        """Test when json_schema_extra is already AgentSchemaMetadata."""
        original_meta = AgentSchemaMetadata(
            name="pre-built",
            system_prompt="Already built"
        )
        schema = AgentSchema(
            description="Test",
            properties={},
            json_schema_extra=original_meta
        )

        meta = get_metadata(schema)
        assert meta.name == "pre-built"
        assert meta.system_prompt == "Already built"


class TestSchemaYAMLSerialization:
    """Tests for YAML serialization functions."""

    def test_schema_to_yaml_and_back(self):
        """Test round-trip YAML serialization."""
        schema = create_agent_schema(
            description="Test agent for YAML serialization.",
            properties={
                "answer": {"type": "string", "description": "The answer"},
                "confidence": {"type": "number"}
            },
            required=["answer"],
            name="yaml-test",
            version="1.0.0"
        )

        # Serialize to YAML
        yaml_str = schema_to_yaml(schema)
        assert "yaml-test" in yaml_str
        assert "Test agent for YAML serialization." in yaml_str

        # Deserialize back
        restored = schema_from_yaml(yaml_str)
        assert restored.description == schema.description
        assert get_metadata(restored).name == "yaml-test"

    def test_yaml_preserves_system_prompt(self):
        """Test that system_prompt is preserved in YAML round-trip."""
        schema = AgentSchema(
            description="Base description",
            properties={"answer": {"type": "string"}},
            json_schema_extra={
                "name": "prompt-test",
                "system_prompt": "Extended instructions with\nmultiple lines."
            }
        )

        yaml_str = schema_to_yaml(schema)
        restored = schema_from_yaml(yaml_str)

        meta = get_metadata(restored)
        assert "multiple lines" in meta.system_prompt
        assert get_system_prompt(restored) == get_system_prompt(schema)


class TestSchemaDictSerialization:
    """Tests for dict serialization functions."""

    def test_schema_to_dict_and_from_dict(self):
        """Test round-trip dict serialization."""
        schema = AgentSchema(
            description="Dict test",
            properties={"result": {"type": "string"}},
            json_schema_extra={
                "name": "dict-agent",
                "structured_output": False,
                "mcp_servers": [{"type": "local", "module": "test.mcp", "id": "test"}]
            }
        )

        # To dict
        d = schema_to_dict(schema)
        assert d["description"] == "Dict test"
        assert d["json_schema_extra"]["name"] == "dict-agent"
        assert d["json_schema_extra"]["structured_output"] is False

        # From dict
        restored = schema_from_dict(d)
        assert restored.description == schema.description

    def test_exclude_none(self):
        """Test that exclude_none removes None values."""
        schema = AgentSchema(
            description="Test",
            properties={},
            json_schema_extra={"name": "test"}
        )

        d = schema_to_dict(schema, exclude_none=True)

        # Optional fields like title should not be in output if None
        assert "title" not in d or d.get("title") is not None

    def test_database_compatible_format(self):
        """Test that output is compatible with database spec column."""
        schema = create_agent_schema(
            description="DB test",
            properties={"answer": {"type": "string"}},
            required=["answer"],
            name="db-agent",
            kind="agent",
            version="2.0.0"
        )

        # This is what goes into the database spec column
        spec = schema_to_dict(schema)

        # Verify it can be loaded back (simulating DB retrieval)
        loaded = schema_from_dict(spec)

        assert loaded.description == schema.description
        meta = get_metadata(loaded)
        assert meta.name == "db-agent"
        assert meta.kind == "agent"
        assert meta.version == "2.0.0"


class TestComplexAgentSchema:
    """Integration tests using complex agent schema structure with MCP tools."""

    def test_complex_agent_schema_structure(self):
        """Test complex agent schema with MCP tools, resources, and custom system prompt."""
        schema = AgentSchema(
            type="object",
            description="Support agent with risk assessment and tool usage",
            properties={
                "answer": {"type": "string", "description": "Natural language response"},
                "analysis": {
                    "type": "object",
                    "properties": {
                        "risk-level": {"type": "string", "enum": ["green", "orange", "red"]},
                        "risk-reasoning": {"type": "string"}
                    }
                }
            },
            required=["answer"],
            json_schema_extra={
                "structured_output": False,  # Free-form text output
                "tools": [
                    {"name": "register_metadata", "mcp_server": "rem"}
                ],
                "resources": [
                    {"uri_pattern": "rem://resources?category=drug.*", "mcp_server": "rem"}
                ],
                "system_prompt": """You are a caring assistant.

## ALWAYS call register_metadata FIRST
Before every response, call register_metadata with risk assessment.

## Output
After calling register_metadata, write ONLY natural text.
NEVER include JSON or structured data in your response.""",
                "name": "support-agent",
                "kind": "agent",
                "version": "1.0.0"
            }
        )

        # Verify structure
        meta = get_metadata(schema)
        assert meta.name == "support-agent"
        assert meta.structured_output is False
        assert len(meta.tools) == 1
        assert meta.tools[0].name == "register_metadata"

        # Verify system prompt extraction
        prompt = get_system_prompt(schema)
        assert "Support agent with risk assessment" in prompt
        assert "ALWAYS call register_metadata FIRST" in prompt
        assert "NEVER include JSON" in prompt

        # Verify YAML round-trip preserves everything
        yaml_str = schema_to_yaml(schema)
        restored = schema_from_yaml(yaml_str)

        restored_meta = get_metadata(restored)
        assert restored_meta.name == "support-agent"
        assert restored_meta.structured_output is False
        assert get_system_prompt(restored) == get_system_prompt(schema)
