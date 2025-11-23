"""
Unit tests for Pydantic AI agent factory.

Tests the conversion of JSON Schema agent definitions to Pydantic AI agents,
including schema parsing, model creation, tool loading, and description stripping.
"""
from rem.settings import settings

import pytest
from pydantic import BaseModel
from pydantic_ai import Agent

from rem.agentic.context import AgentContext
from rem.agentic.providers.pydantic_ai import (
    _create_model_from_schema,
    _create_schema_wrapper,
    create_agent as create_ai_agent_provider,
)


class TestSchemaWrapper:
    """Test schema wrapper that strips descriptions from Pydantic models."""

    def test_schema_wrapper_strips_description(self):
        """Test that schema wrapper removes model-level description."""

        class TestModel(BaseModel):
            """This is a test model description."""

            field1: str
            field2: int

        # Create wrapper with stripping enabled
        wrapped = _create_schema_wrapper(TestModel, strip_description=True)

        # Get JSON schema
        schema = wrapped.model_json_schema()

        # Description should be removed
        assert "description" not in schema
        assert "properties" in schema
        assert "field1" in schema["properties"]
        assert "field2" in schema["properties"]

    def test_schema_wrapper_preserves_without_stripping(self):
        """Test that schema wrapper preserves description when stripping disabled."""

        class TestModel(BaseModel):
            """This is a test model description."""

            field1: str

        # Create wrapper with stripping disabled
        wrapped = _create_schema_wrapper(TestModel, strip_description=False)

        # Wrapper should be the original model
        assert wrapped is TestModel

    def test_schema_wrapper_preserves_field_descriptions(self):
        """Test that field descriptions are preserved even when model description is stripped."""

        class TestModel(BaseModel):
            """Model description."""

            field1: str = "Field 1 description"

        wrapped = _create_schema_wrapper(TestModel, strip_description=True)
        schema = wrapped.model_json_schema()

        # Model description removed
        assert "description" not in schema

        # Field descriptions preserved
        assert "properties" in schema
        # Note: Field descriptions are in properties, not at model level


class TestModelFromSchema:
    """Test dynamic Pydantic model creation from JSON Schema."""

    def test_create_simple_model(self):
        """Test creating a simple Pydantic model from JSON Schema."""
        pytest.importorskip("json_schema_to_pydantic")

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }

        model = _create_model_from_schema(schema)

        # Verify model structure
        assert issubclass(model, BaseModel)
        assert "name" in model.model_fields
        assert "age" in model.model_fields

        # Test instantiation
        instance = model(name="Test", age=25)
        assert instance.name == "Test"
        assert instance.age == 25

        # Test required field validation
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            model(age=25)  # Missing required 'name'

    def test_create_nested_model(self):
        """Test creating a nested Pydantic model from JSON Schema."""
        pytest.importorskip("json_schema_to_pydantic")

        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["name"],
                },
                "score": {"type": "number"},
            },
            "required": ["user"],
        }

        model = _create_model_from_schema(schema)

        # Test nested structure
        instance = model(user={"name": "Test", "email": "test@example.com"}, score=0.95)
        assert instance.user.name == "Test"
        assert instance.user.email == "test@example.com"
        assert instance.score == 0.95

    def test_create_array_model(self):
        """Test creating model with array fields from JSON Schema."""
        pytest.importorskip("json_schema_to_pydantic")

        schema = {
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}},
                "scores": {
                    "type": "array",
                    "items": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        }

        model = _create_model_from_schema(schema)

        instance = model(tags=["python", "pydantic"], scores=[0.8, 0.9])
        assert len(instance.tags) == 2
        assert instance.tags[0] == "python"


@pytest.mark.asyncio
class TestCreatePydanticAIAgent:
    """Test agent creation from JSON Schema."""

    async def test_create_agent_from_query_schema(self, query_agent_schema):
        """Test creating agent from query agent schema."""
        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema
        # )
        #
        # assert isinstance(agent, Agent)
        # assert agent.system_prompt == query_agent_schema["description"]
        # assert agent.instrument == False  # Default when settings.otel.enabled = False

    async def test_create_agent_with_context(self, query_agent_schema):
        """Test creating agent with context."""
        context = AgentContext(
            user_id=settings.test.effective_user_id,
            tenant_id="test-tenant",
            session_id="test-session",
            default_model="openai:gpt-4",
        )

        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     context=context,
        #     agent_schema_override=query_agent_schema
        # )
        #
        # assert isinstance(agent, Agent)
        # # Model should be from context
        # assert agent.model == context.default_model

    async def test_create_agent_with_model_override(self, query_agent_schema):
        """Test creating agent with model override."""
        context = AgentContext(default_model="openai:gpt-4")

        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     context=context,
        #     agent_schema_override=query_agent_schema,
        #     model_override="anthropic:claude-sonnet-4-5-20250929"
        # )
        #
        # # Model should be override, not context default
        # assert agent.model == "anthropic:claude-sonnet-4-5-20250929"

    async def test_agent_system_prompt_from_description(self, query_agent_schema):
        """Test that agent system prompt comes from schema description."""
        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema
        # )
        #
        # # System prompt should match schema description
        # expected_prompt = query_agent_schema["description"]
        # assert agent.system_prompt == expected_prompt
        # assert "REM Query Agent" in agent.system_prompt
        # assert "LOOKUP" in agent.system_prompt

    async def test_agent_output_schema_properties(self, query_agent_schema):
        """Test that agent output schema matches JSON Schema properties."""
        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema
        # )
        #
        # # Agent should have structured output type
        # assert agent.output_type is not None
        #
        # # Verify output type has expected fields from schema
        # output_fields = agent.output_type.model_fields
        # assert "answer" in output_fields
        # assert "confidence" in output_fields
        # assert "sources" in output_fields
        # assert "reasoning" in output_fields

    async def test_agent_tools_from_schema(self, query_agent_schema):
        """Test that agent tools are loaded from schema."""
        # TODO: Uncomment when MCP tool loading is implemented
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema
        # )
        #
        # # Agent should have tools from schema
        # assert len(agent.tools) > 0
        #
        # # Verify expected tools are loaded
        # tool_names = [tool.name for tool in agent.tools]
        # assert "lookup_entity" in tool_names
        # assert "fuzzy_search" in tool_names
        # assert "semantic_search" in tool_names
        # assert "traverse_graph" in tool_names

    async def test_agent_with_evaluator_schema(self, accuracy_evaluator_schema):
        """Test creating evaluator agent from schema."""
        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=accuracy_evaluator_schema
        # )
        #
        # assert isinstance(agent, Agent)
        # assert "Accuracy Evaluator" in agent.system_prompt
        #
        # # Evaluator output schema
        # output_fields = agent.output_type.model_fields
        # assert "accuracy_score" in output_fields
        # assert "completeness_score" in output_fields
        # assert "source_usage_score" in output_fields
        # assert "overall_score" in output_fields

    async def test_schema_description_stripping(self, query_agent_schema):
        """Test that model description is stripped from output schema."""
        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema,
        #     strip_model_description=True
        # )
        #
        # # Get the JSON schema sent to LLM
        # output_schema = agent.output_type.model_json_schema()
        #
        # # Model-level description should be removed (prevent duplication with system prompt)
        # assert "description" not in output_schema
        #
        # # But field descriptions should remain
        # assert "properties" in output_schema
        # for field_name, field_schema in output_schema["properties"].items():
        #     if field_name in query_agent_schema["properties"]:
        #         # Field descriptions are preserved
        #         assert "description" in field_schema or "type" in field_schema

    async def test_no_schema_description_stripping(self, query_agent_schema):
        """Test that model description is preserved when stripping disabled."""
        # TODO: Uncomment when implementation is complete
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema,
        #     strip_model_description=False
        # )
        #
        # # Get the JSON schema sent to LLM
        # output_schema = agent.output_type.model_json_schema()
        #
        # # Model description may be present (from Pydantic docstring conversion)
        # # This test ensures stripping can be disabled if needed


@pytest.mark.asyncio
class TestAgentExecution:
    """Test agent execution with structured output."""

    async def test_agent_run_simple_query(self, query_agent_schema):
        """Test running agent with simple query."""
        # TODO: Uncomment when implementation is complete and add mock MCP tools
        # agent = await create_ai_agent_provider(
        #     agent_schema_override=query_agent_schema
        # )
        #
        # # Run agent
        # result = await agent.run("Who manages Project Alpha?")
        #
        # # Verify structured output
        # assert hasattr(result.data, "answer")
        # assert hasattr(result.data, "confidence")
        # assert hasattr(result.data, "sources")
        # assert isinstance(result.data.answer, str)
        # assert 0 <= result.data.confidence <= 1
        # assert isinstance(result.data.sources, list)
