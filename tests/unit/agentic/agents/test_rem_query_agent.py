"""
Unit tests for REM Query Agent.

Tests the natural language to REM query conversion.
"""

import pytest

from rem.agentic.agents import REMQueryOutput, REM_QUERY_AGENT_SCHEMA
from rem.models.core import QueryType


class TestREMQueryAgentSchema:
    """Test REM Query Agent schema structure."""

    def test_schema_structure(self):
        """Test that schema has required fields."""
        assert "type" in REM_QUERY_AGENT_SCHEMA
        assert REM_QUERY_AGENT_SCHEMA["type"] == "object"
        assert "description" in REM_QUERY_AGENT_SCHEMA
        assert "properties" in REM_QUERY_AGENT_SCHEMA
        assert "required" in REM_QUERY_AGENT_SCHEMA

    def test_schema_properties(self):
        """Test schema output properties."""
        props = REM_QUERY_AGENT_SCHEMA["properties"]
        assert "query_type" in props
        assert "parameters" in props
        assert "confidence" in props
        assert "reasoning" in props
        assert "multi_step" in props

    def test_query_type_enum(self):
        """Test query type enum values."""
        query_type_prop = REM_QUERY_AGENT_SCHEMA["properties"]["query_type"]
        assert "enum" in query_type_prop
        expected_types = ["LOOKUP", "FUZZY", "SEARCH", "SQL", "TRAVERSE"]
        assert query_type_prop["enum"] == expected_types

    def test_no_tools_required(self):
        """Test that REM Query Agent is a pure reasoning agent (no tools)."""
        json_extra = REM_QUERY_AGENT_SCHEMA.get("json_schema_extra", {})
        assert json_extra.get("tools") == []
        assert json_extra.get("resources") == []


class TestREMQueryOutput:
    """Test REMQueryOutput Pydantic model."""

    def test_lookup_output(self):
        """Test creating LOOKUP query output."""
        output = REMQueryOutput(
            query_type=QueryType.LOOKUP,
            parameters={"entity_key": "sarah-chen"},
            confidence=1.0,
        )

        assert output.query_type == QueryType.LOOKUP
        assert output.parameters == {"entity_key": "sarah-chen"}
        assert output.confidence == 1.0
        assert output.reasoning is None
        assert output.multi_step is None

    def test_fuzzy_output(self):
        """Test creating FUZZY query output."""
        output = REMQueryOutput(
            query_type=QueryType.FUZZY,
            parameters={
                "query_text": "Sara",
                "threshold": 0.3,
                "limit": 10,
            },
            confidence=0.9,
        )

        assert output.query_type == QueryType.FUZZY
        assert output.parameters["query_text"] == "Sara"
        assert output.confidence == 0.9

    def test_search_output(self):
        """Test creating SEARCH query output."""
        output = REMQueryOutput(
            query_type=QueryType.SEARCH,
            parameters={
                "query_text": "database migration",
                "table_name": "resources",
                "field_name": "content",
                "limit": 10,
            },
            confidence=0.95,
        )

        assert output.query_type == QueryType.SEARCH
        assert output.parameters["table_name"] == "resources"
        assert output.parameters["field_name"] == "content"

    def test_sql_output(self):
        """Test creating SQL query output."""
        output = REMQueryOutput(
            query_type=QueryType.SQL,
            parameters={
                "table_name": "moments",
                "where_clause": "moment_type='meeting' AND created_at >= '2024-10-01'",
                "limit": 100,
            },
            confidence=0.9,
        )

        assert output.query_type == QueryType.SQL
        assert "where_clause" in output.parameters

    def test_traverse_output_with_reasoning(self):
        """Test creating TRAVERSE query output with reasoning."""
        output = REMQueryOutput(
            query_type=QueryType.TRAVERSE,
            parameters={
                "start_key": "sarah-chen",
                "max_depth": 1,
                "rel_type": "manages",
            },
            confidence=0.85,
            reasoning="TRAVERSE query to find entities Sarah manages via graph edges",
        )

        assert output.query_type == QueryType.TRAVERSE
        assert output.reasoning is not None
        assert "TRAVERSE" in output.reasoning

    def test_multi_step_output(self):
        """Test creating multi-step query output."""
        output = REMQueryOutput(
            query_type=QueryType.SEARCH,
            parameters={
                "query_text": "database",
                "table_name": "resources",
                "limit": 10,
            },
            confidence=0.6,
            reasoning="Complex query requiring multiple steps",
            multi_step=[
                {
                    "query_type": "LOOKUP",
                    "parameters": {"entity_key": "sarah-chen"},
                    "description": "Find Sarah's entity",
                },
                {
                    "query_type": "SQL",
                    "parameters": {
                        "table_name": "resources",
                        "where_clause": "user_id='sarah-chen-uuid'",
                    },
                    "description": "Get Sarah's resources",
                },
            ],
        )

        assert output.multi_step is not None
        assert len(output.multi_step) == 2
        assert output.multi_step[0]["query_type"] == "LOOKUP"

    def test_confidence_validation(self):
        """Test confidence score validation."""
        # Valid confidence
        output = REMQueryOutput(
            query_type=QueryType.LOOKUP,
            parameters={"entity_key": "test"},
            confidence=0.5,
        )
        assert output.confidence == 0.5

        # Invalid confidence (too high) should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            REMQueryOutput(
                query_type=QueryType.LOOKUP,
                parameters={"entity_key": "test"},
                confidence=1.5,
            )

        # Invalid confidence (too low) should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            REMQueryOutput(
                query_type=QueryType.LOOKUP,
                parameters={"entity_key": "test"},
                confidence=-0.1,
            )

    def test_model_dump(self):
        """Test serializing output to dict."""
        output = REMQueryOutput(
            query_type=QueryType.LOOKUP,
            parameters={"entity_key": "sarah-chen"},
            confidence=1.0,
        )

        data = output.model_dump()
        assert data["query_type"] == "LOOKUP"
        assert data["parameters"] == {"entity_key": "sarah-chen"}
        assert data["confidence"] == 1.0
        assert data["reasoning"] is None


# Integration tests with actual agent execution would require:
# - Mock LLM provider
# - AgentContext setup
# - Environment variables for API keys
# These are better suited for integration tests rather than unit tests
