"""
Unit tests for REM Query Agent.

Tests the natural language to REM query conversion.
"""

import pytest

from rem.agentic.agents import REMQueryOutput, REM_QUERY_AGENT_SCHEMA


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
        assert "query" in props
        assert "confidence" in props
        assert "reasoning" in props
        # New simplified schema has only 3 fields
        assert len(props) == 3

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
            query="LOOKUP sarah-chen",
            confidence=1.0,
        )

        assert output.query == "LOOKUP sarah-chen"
        assert output.confidence == 1.0
        assert output.reasoning == ""

    def test_fuzzy_output(self):
        """Test creating FUZZY query output."""
        output = REMQueryOutput(
            query="FUZZY Sara threshold=0.3 limit=10",
            confidence=0.9,
        )

        assert output.query == "FUZZY Sara threshold=0.3 limit=10"
        assert output.confidence == 0.9
        assert output.reasoning == ""

    def test_search_output(self):
        """Test creating SEARCH query output."""
        output = REMQueryOutput(
            query="SEARCH database migration table=resources limit=10",
            confidence=0.95,
        )

        assert output.query == "SEARCH database migration table=resources limit=10"
        assert "SEARCH" in output.query
        assert "resources" in output.query

    def test_sql_output(self):
        """Test creating SQL query output."""
        output = REMQueryOutput(
            query="SQL table=moments where=\"moment_type='meeting' AND created_at>='2024-10-01'\" limit=100",
            confidence=0.9,
        )

        assert output.query.startswith("SQL")
        assert "moments" in output.query

    def test_traverse_output_with_reasoning(self):
        """Test creating TRAVERSE query output with reasoning."""
        output = REMQueryOutput(
            query="TRAVERSE sarah-chen rel_type=manages depth=1",
            confidence=0.65,
            reasoning="Low confidence - user may want different traversal depth",
        )

        assert output.query.startswith("TRAVERSE")
        assert output.reasoning != ""
        assert "confidence" in output.reasoning.lower() or "depth" in output.reasoning.lower()

    def test_confidence_validation(self):
        """Test confidence score validation."""
        # Valid confidence
        output = REMQueryOutput(
            query="LOOKUP test",
            confidence=0.5,
        )
        assert output.confidence == 0.5

        # Invalid confidence (too high) should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            REMQueryOutput(
                query="LOOKUP test",
                confidence=1.5,
            )

        # Invalid confidence (too low) should raise validation error
        with pytest.raises(Exception):  # Pydantic ValidationError
            REMQueryOutput(
                query="LOOKUP test",
                confidence=-0.1,
            )

    def test_model_dump(self):
        """Test serializing output to dict."""
        output = REMQueryOutput(
            query="LOOKUP sarah-chen",
            confidence=1.0,
        )

        data = output.model_dump()
        assert data["query"] == "LOOKUP sarah-chen"
        assert data["confidence"] == 1.0
        assert data["reasoning"] == ""


# Integration tests with actual agent execution would require:
# - Mock LLM provider
# - AgentContext setup
# - Environment variables for API keys
# These are better suited for integration tests rather than unit tests
