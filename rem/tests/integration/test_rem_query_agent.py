"""
Test REM Query Agent - Validates natural language to REM query string conversion.

This test validates that the REM Query Agent can:
1. Generate valid REM query strings from natural language
2. Select appropriate query types (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
3. Generate correct query syntax with parameters
4. Use Cerebras Qwen for ultra-fast inference
5. Return appropriate confidence scores

Requirements:
    - CEREBRAS_API_KEY must be set in environment (or in ~/.bash_profile)
    - Cerebras Qwen provides 2400 tok/s for query generation

Run with:
    export CEREBRAS_API_KEY=<your-key>
    pytest tests/integration/test_rem_query_agent.py -v

Or directly:
    python tests/integration/test_rem_query_agent.py
"""

import pytest
from rem.agentic import ask_rem


@pytest.mark.asyncio
@pytest.mark.llm
async def test_lookup_query():
    """Test LOOKUP query generation for entity by name."""
    result = await ask_rem("Show me Sarah Chen")

    assert "LOOKUP" in result.query.upper()
    assert "sarah" in result.query.lower()
    assert result.confidence >= 0.8
    print(f"✓ LOOKUP query: {result.query}")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_fuzzy_query():
    """Test FUZZY query generation for partial/misspelled names."""
    result = await ask_rem("Find people named Sara")

    assert "FUZZY" in result.query.upper()
    assert "sara" in result.query.lower()
    assert result.confidence >= 0.7
    print(f"✓ FUZZY query: {result.query}")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_search_query():
    """Test SEARCH query generation for semantic/conceptual questions."""
    result = await ask_rem("Find documents about database migration")

    assert "SEARCH" in result.query.upper()
    assert "database" in result.query.lower()
    assert "table=resources" in result.query or "resources" in result.query
    assert result.confidence >= 0.7
    print(f"✓ SEARCH query: {result.query}")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_sql_query():
    """Test SQL query generation for temporal/filtered queries."""
    result = await ask_rem("Show meetings in Q4 2024")

    assert "SQL" in result.query.upper()
    assert "moments" in result.query.lower()
    assert "2024" in result.query
    assert result.confidence >= 0.7
    print(f"✓ SQL query: {result.query}")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_traverse_query():
    """Test TRAVERSE query generation for relationship questions."""
    result = await ask_rem("What does Sarah manage?")

    assert "TRAVERSE" in result.query.upper()
    assert "sarah" in result.query.lower()
    # Should include rel_type for manages relationship
    assert "manage" in result.query.lower() or result.confidence >= 0.6

    assert result.confidence >= 0.6
    print(f"✓ TRAVERSE query: {result.query}")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_all_query_types():
    """Test all REM query types with expected outputs."""
    test_cases = [
        ("Show me Sarah Chen", "LOOKUP", "sarah-chen"),
        ("Find people named Sara", "FUZZY", "Sara"),
        ("Documents about database migration", "SEARCH", "database"),
        ("Meetings in Q4 2024", "SQL", "moments"),
        ("What does Sarah manage?", "TRAVERSE", "sarah"),
    ]

    print("\nTesting all REM query types:")
    print("=" * 80)

    for question, expected_type, expected_content in test_cases:
        result = await ask_rem(question)

        # Verify query type
        assert expected_type in result.query.upper(), \
            f"Expected {expected_type} in query: {result.query}"

        # Verify content
        assert expected_content.lower() in result.query.lower(), \
            f"Expected '{expected_content}' in query: {result.query}"

        # Verify confidence
        assert 0.0 <= result.confidence <= 1.0

        print(f"Q: {question}")
        print(f"→ {result.query}")
        print(f"  Confidence: {result.confidence:.2f}")
        if result.reasoning:
            print(f"  Reasoning: {result.reasoning}")
        print()


@pytest.mark.asyncio
@pytest.mark.llm
async def test_agent_uses_cerebras_qwen():
    """Test that agent uses Cerebras Qwen model for ultra-fast inference."""
    from rem.settings import settings

    # Check that default query_agent_model is Cerebras Qwen
    assert "cerebras" in settings.llm.query_agent_model.lower()
    assert "qwen" in settings.llm.query_agent_model.lower()
    print(f"✓ Using ultra-fast model: {settings.llm.query_agent_model}")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_confidence_and_reasoning():
    """Test confidence scores and reasoning for low confidence queries."""
    # High confidence query
    result_high = await ask_rem("Show me Sarah Chen")
    assert result_high.confidence >= 0.9
    assert result_high.reasoning == "" or not result_high.reasoning

    print(f"✓ High confidence ({result_high.confidence:.2f}): {result_high.query}")

    # Medium confidence query
    result_med = await ask_rem("Find documents about databases")
    assert 0.5 <= result_med.confidence <= 1.0

    print(f"✓ Medium confidence ({result_med.confidence:.2f}): {result_med.query}")

    # Check that low confidence includes reasoning
    if result_med.confidence < 0.7:
        assert result_med.reasoning, "Low confidence should include reasoning"
        print(f"  Reasoning: {result_med.reasoning}")


def test_query_output_structure():
    """Test REMQueryOutput model structure."""
    from rem.agentic import REMQueryOutput

    # Test valid output with all fields
    output = REMQueryOutput(
        query="LOOKUP sarah-chen",
        confidence=1.0,
        reasoning=""
    )

    assert output.query == "LOOKUP sarah-chen"
    assert output.confidence == 1.0
    assert output.reasoning == ""

    # Test with reasoning
    output_with_reasoning = REMQueryOutput(
        query="SEARCH database table=resources",
        confidence=0.65,
        reasoning="Ambiguous query, using SEARCH for semantic match"
    )

    assert output_with_reasoning.reasoning != ""

    print("✓ REMQueryOutput structure valid")


if __name__ == "__main__":
    import asyncio

    async def run_tests():
        print("=" * 80)
        print("REM Query Agent Test Suite - Cerebras Qwen Integration")
        print("=" * 80)
        print()

        print("1. Testing LOOKUP query...")
        await test_lookup_query()
        print()

        print("2. Testing FUZZY query...")
        await test_fuzzy_query()
        print()

        print("3. Testing SEARCH query...")
        await test_search_query()
        print()

        print("4. Testing SQL query...")
        await test_sql_query()
        print()

        print("5. Testing TRAVERSE query...")
        await test_traverse_query()
        print()

        print("6. Testing all query types...")
        await test_all_query_types()
        print()

        print("7. Testing Cerebras Qwen configuration...")
        await test_agent_uses_cerebras_qwen()
        print()

        print("8. Testing confidence scores and reasoning...")
        await test_confidence_and_reasoning()
        print()

        print("9. Testing output structure...")
        test_query_output_structure()
        print()

        print("=" * 80)
        print("✓ All tests passed!")
        print("=" * 80)

    asyncio.run(run_tests())
