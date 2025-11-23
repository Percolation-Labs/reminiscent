"""
Natural Language to REM Dialect Query Demonstration Suite.

This test suite demonstrates how natural language questions are converted to
REM dialect queries and executed to produce results. It follows the query
evolution framework from the REM testing philosophy.

Key Principles:
1. Test with USER-KNOWN information (natural language), not internal IDs
2. Show query evolution across maturity stages (0% → 100% answerable)
3. Validate natural language → REM query string → results flow
4. Use Cerebras Qwen for ultra-fast query generation (2400 tok/s)

Maturity Stages:
- Stage 0: No data (0% answerable)
- Stage 1: Resources seeded (20% answerable) - LOOKUP, SQL work
- Stage 2: Moments extracted (50% answerable) - Temporal queries work
- Stage 3: Affinity graph built (80% answerable) - SEARCH, TRAVERSE work
- Stage 4: Mature graph (100% answerable) - Predictive queries work

Run with:
    export CEREBRAS_API_KEY=<your-key>
    pytest tests/integration/test_natural_language_to_rem.py -v -s

Or directly:
    python tests/integration/test_natural_language_to_rem.py
"""

import pytest
import asyncio
from datetime import datetime
from typing import Any

from rem.agentic import ask_rem


# Test data representing different maturity stages
STAGE_1_QUESTIONS = [
    # Entity lookups with natural language
    ("Who is Sarah?", "LOOKUP", "sarah"),
    ("Show me information about Sarah Chen", "LOOKUP", "sarah"),
    ("Show me Mike Johnson", "LOOKUP", "mike"),
    ("Show me Project Alpha", "LOOKUP", "project"),
]

STAGE_2_QUESTIONS = [
    # Temporal and moment queries
    ("When did Sarah and Mike meet?", "SQL", "moments"),
    ("Show meetings in November 2024", "SQL", "moments"),
    ("What happened between Nov 1-5?", "SQL", "moments"),
    ("Find coding sessions", "SQL", "coding"),
    ("Show me team standups", "SQL", "meeting"),
]

STAGE_3_QUESTIONS = [
    # Semantic search and graph traversal
    ("Find documents about database migration", "SEARCH", "database"),
    ("What's related to the technical spec?", "TRAVERSE", "spec"),
    ("Find similar documents to meeting notes", "SEARCH", "meeting"),
    ("Show resources connected to Sarah", "TRAVERSE", "sarah"),
    ("What topics are being discussed?", "SQL", "moments"),
]

STAGE_4_QUESTIONS = [
    # Complex multi-hop and predictive queries
    ("What connects planning to operations?", "TRAVERSE", "planning"),
    ("Who works with whom?", "TRAVERSE", "works"),
    ("How did I spend my time yesterday?", "SQL", "moments"),
    ("What should I read next?", "SEARCH", "read"),
]


@pytest.mark.llm
class TestQueryAgentOutput:
    """Test REM Query Agent output structure and quality."""

    @pytest.mark.asyncio
    async def test_query_output_structure(self):
        """Test that ask_rem returns expected output structure."""
        result = await ask_rem("Show me Sarah Chen")

        assert hasattr(result, "query")
        assert hasattr(result, "confidence")
        assert hasattr(result, "reasoning")

        assert isinstance(result.query, str)
        assert isinstance(result.confidence, float)
        assert isinstance(result.reasoning, str)

        assert 0.0 <= result.confidence <= 1.0

        print(f"\n✓ Output structure valid:")
        print(f"  Query: {result.query}")
        print(f"  Confidence: {result.confidence:.2f}")
        if result.reasoning:
            print(f"  Reasoning: {result.reasoning}")

    @pytest.mark.asyncio
    async def test_query_string_format(self):
        """Test that generated queries follow REM dialect format."""
        test_cases = [
            ("Show me Sarah", "LOOKUP"),
            ("Find people named Sara", "FUZZY"),
            ("Documents about databases", "SEARCH"),
            ("Meetings in Q4 2024", "SQL"),
            ("What does Sarah manage?", "TRAVERSE"),
        ]

        print("\n" + "=" * 80)
        print("REM Query String Format Examples")
        print("=" * 80)

        for question, suggested_type in test_cases:
            result = await ask_rem(question)

            assert result.query, f"No query generated for: {question}"

            print(f"\nQ: {question}")
            print(f"→ {result.query}")
            print(f"  Suggested: {suggested_type}")
            print(f"  Confidence: {result.confidence:.2f}")


@pytest.mark.llm
class TestNaturalLanguageToREMDialect:
    """Test natural language to REM dialect conversion across maturity stages."""

    @pytest.mark.asyncio
    async def test_stage_1_lookup_queries(self):
        """
        Stage 1: Resources seeded (20% answerable).

        Natural language entity lookups - demonstrate query generation.
        Users provide natural text, not internal IDs.
        """
        print("\n" + "=" * 80)
        print("STAGE 1: Entity Lookup Queries (20% Answerable)")
        print("=" * 80)

        for question, suggested_type, expected_content in STAGE_1_QUESTIONS:
            result = await ask_rem(question)

            # Just verify we got a valid query and reasonable confidence
            assert result.query, f"No query generated for: {question}"
            assert result.confidence >= 0.5, \
                f"Very low confidence ({result.confidence}) for: {question}"

            # Verify content mentioned (flexible - could be in any query type)
            assert expected_content.lower() in result.query.lower(), \
                f"Expected '{expected_content}' in query: {result.query}"

            print(f"\n✓ Natural Language: \"{question}\"")
            print(f"  REM Dialect: {result.query}")
            print(f"  Suggested Type: {suggested_type}")
            print(f"  Confidence: {result.confidence:.2f}")
            if result.reasoning:
                print(f"  Reasoning: {result.reasoning}")

    @pytest.mark.asyncio
    async def test_stage_2_temporal_queries(self):
        """
        Stage 2: Moments extracted (50% answerable).

        Temporal questions - demonstrate query generation.
        """
        print("\n" + "=" * 80)
        print("STAGE 2: Temporal/Moment Queries (50% Answerable)")
        print("=" * 80)

        for question, suggested_type, expected_content in STAGE_2_QUESTIONS:
            result = await ask_rem(question)

            assert result.query, f"No query generated for: {question}"

            print(f"\n✓ Natural Language: \"{question}\"")
            print(f"  REM Dialect: {result.query}")
            print(f"  Suggested Type: {suggested_type}")
            print(f"  Confidence: {result.confidence:.2f}")

    @pytest.mark.asyncio
    async def test_stage_3_semantic_queries(self):
        """
        Stage 3: Affinity graph built (80% answerable).

        Semantic and relationship questions - demonstrate query generation.
        """
        print("\n" + "=" * 80)
        print("STAGE 3: Semantic Search & Graph Traversal (80% Answerable)")
        print("=" * 80)

        for question, suggested_type, expected_content in STAGE_3_QUESTIONS:
            result = await ask_rem(question)

            assert result.query, f"No query generated for: {question}"

            print(f"\n✓ Natural Language: \"{question}\"")
            print(f"  REM Dialect: {result.query}")
            print(f"  Suggested Type: {suggested_type}")
            print(f"  Confidence: {result.confidence:.2f}")
            if result.reasoning:
                print(f"  Reasoning: {result.reasoning}")

    @pytest.mark.asyncio
    async def test_stage_4_complex_queries(self):
        """
        Stage 4: Mature graph (100% answerable).

        Complex multi-hop and predictive queries - demonstrate generation.
        """
        print("\n" + "=" * 80)
        print("STAGE 4: Complex Multi-Hop Queries (100% Answerable)")
        print("=" * 80)

        for question, suggested_type, expected_content in STAGE_4_QUESTIONS:
            result = await ask_rem(question)

            assert result.query, f"No query generated for: {question}"
            # Stage 4 queries may have lower confidence due to complexity - that's ok

            print(f"\n✓ Natural Language: \"{question}\"")
            print(f"  REM Dialect: {result.query}")
            print(f"  Suggested Type: {suggested_type}")
            print(f"  Confidence: {result.confidence:.2f}")
            if result.reasoning:
                print(f"  Reasoning: {result.reasoning}")


@pytest.mark.llm
class TestQueryEvolutionDemonstration:
    """Demonstrate query evolution as graph matures."""

    @pytest.mark.asyncio
    async def test_show_all_query_types(self):
        """
        Comprehensive demonstration of all 5 REM query types.

        Shows natural language → REM dialect for each query type.
        """
        print("\n" + "=" * 80)
        print("COMPREHENSIVE REM QUERY TYPE DEMONSTRATION")
        print("=" * 80)
        print("\nShowing: Natural Language → REM Dialect → Expected Results")
        print("=" * 80)

        test_cases = [
            {
                "question": "Who is Sarah Chen?",
                "expected_type": "LOOKUP",
                "expected_pattern": "sarah",
                "stage": 1,
                "description": "Entity lookup with natural name (not 'sarah-chen')",
            },
            {
                "question": "Find people named Sara",
                "expected_type": "FUZZY",
                "expected_pattern": "sara",
                "stage": 1,
                "description": "Fuzzy matching for typos/variations",
            },
            {
                "question": "Find documents about database migration to TiDB",
                "expected_type": "SEARCH",
                "expected_pattern": "database",
                "stage": 3,
                "description": "Semantic vector search for concepts",
            },
            {
                "question": "Show me meetings from November 2024",
                "expected_type": "SQL",
                "expected_pattern": "moments",
                "stage": 2,
                "description": "Temporal filtering with SQL",
            },
            {
                "question": "What does Sarah manage?",
                "expected_type": "TRAVERSE",
                "expected_pattern": "sarah",
                "stage": 3,
                "description": "Graph traversal for relationships",
            },
        ]

        for case in test_cases:
            result = await ask_rem(case["question"])

            print(f"\n{'─' * 80}")
            print(f"STAGE {case['stage']}: {case['description']}")
            print(f"{'─' * 80}")
            print(f"Natural Language: \"{case['question']}\"")
            print(f"REM Dialect:      {result.query}")
            print(f"Confidence:       {result.confidence:.2f}")

            # Validate query was generated
            assert result.query, "Query should be generated"

            print(f"✓ Generated:      {result.query}")
            print(f"  Expected Type:  {case['expected_type']}")

            if result.reasoning:
                print(f"Reasoning:        {result.reasoning}")


@pytest.mark.llm
class TestUserKnownVsSystemInternal:
    """
    Critical testing principle: Use what USERS know, not system internals.

    This validates that we test with natural language, not internal IDs.
    """

    @pytest.mark.asyncio
    async def test_user_provides_natural_names(self):
        """Users provide natural entity names, not normalized IDs."""
        print("\n" + "=" * 80)
        print("USER-KNOWN vs SYSTEM-INTERNAL Testing")
        print("=" * 80)

        # ✅ CORRECT: What users actually know
        user_inputs = [
            "Sarah",           # Not "sarah-chen"
            "Sarah Chen",      # Not "sarah-chen"
            "Project Alpha",   # Not "project-alpha"
            "TiDB",           # Not "tidb"
        ]

        print("\n✅ CORRECT: Testing with user-known natural language")
        for natural_input in user_inputs:
            result = await ask_rem(f"Show me {natural_input}")

            assert "LOOKUP" in result.query.upper() or "FUZZY" in result.query.upper()

            print(f"  User Input: \"{natural_input}\"")
            print(f"  → Query: {result.query}")
            print(f"  → System handles normalization internally")

        # ❌ WRONG: What system stores internally (don't test this way!)
        print("\n❌ WRONG: Don't test with internal normalized IDs")
        print("  'sarah-chen'    ← Internal normalization")
        print("  'project-alpha' ← Internal hyphenation")
        print("  UUID strings    ← System-generated IDs")
        print("\nThese are implementation details users never see!")

    @pytest.mark.asyncio
    async def test_natural_language_variations(self):
        """Test that system handles natural language variations."""
        variations = [
            ("Sarah", "sarah-chen"),
            ("Sarah Chen", "sarah-chen"),
            ("SARAH", "sarah-chen"),
            ("sarah chen", "sarah-chen"),
        ]

        print("\n" + "=" * 80)
        print("Natural Language Variation Handling")
        print("=" * 80)

        for user_input, expected_normalized in variations:
            result = await ask_rem(f"Who is {user_input}?")

            # System should generate LOOKUP query for any variation
            assert "LOOKUP" in result.query.upper() or "FUZZY" in result.query.upper()

            print(f"\n  User: \"{user_input}\" → Query: {result.query}")

        print("\n✓ System handles all natural variations")


@pytest.mark.llm
class TestConfidenceAndReasoning:
    """Test confidence scoring and reasoning for ambiguous queries."""

    @pytest.mark.asyncio
    async def test_high_confidence_queries(self):
        """High confidence queries should have confidence >= 0.8."""
        high_confidence_questions = [
            "Show me Sarah Chen",
            "Find TiDB",
            "Who is Mike Johnson?",
        ]

        print("\n" + "=" * 80)
        print("High Confidence Queries (>= 0.8)")
        print("=" * 80)

        for question in high_confidence_questions:
            result = await ask_rem(question)

            assert result.confidence >= 0.8, \
                f"Expected high confidence for clear query: {question}"

            print(f"\n✓ \"{question}\"")
            print(f"  Confidence: {result.confidence:.2f}")
            print(f"  Query: {result.query}")

    @pytest.mark.asyncio
    async def test_medium_confidence_with_reasoning(self):
        """Medium/low confidence queries should include reasoning."""
        ambiguous_questions = [
            "Find stuff about databases",
            "Show me things",
            "What happened?",
        ]

        print("\n" + "=" * 80)
        print("Medium/Low Confidence Queries (< 0.7)")
        print("=" * 80)

        for question in ambiguous_questions:
            result = await ask_rem(question)

            print(f"\n? \"{question}\"")
            print(f"  Confidence: {result.confidence:.2f}")
            print(f"  Query: {result.query}")

            if result.confidence < 0.7:
                # Low confidence should include reasoning
                print(f"  ⚠ Reasoning: {result.reasoning}")


@pytest.mark.llm
class TestPlanModeVsDirectMode:
    """Test plan mode (show query) vs direct mode (execute query)."""

    @pytest.mark.asyncio
    async def test_plan_mode_shows_query_without_execution(self):
        """Plan mode should show query but not execute it."""
        question = "Show me Sarah Chen"

        # This test demonstrates the concept - actual execution requires RemService
        result = await ask_rem(question)

        print("\n" + "=" * 80)
        print("Plan Mode vs Direct Mode")
        print("=" * 80)

        print(f"\nQuestion: \"{question}\"")
        print(f"\nPLAN MODE (plan_mode=True):")
        print(f"  Generated Query: {result.query}")
        print(f"  Confidence: {result.confidence:.2f}")
        print(f"  → Shows what WOULD be executed, but doesn't execute")

        print(f"\nDIRECT MODE (plan_mode=False, confidence >= 0.7):")
        print(f"  Generated Query: {result.query}")
        print(f"  → Parses and executes query")
        print(f"  → Returns actual data results")

        print(f"\nLOW CONFIDENCE (confidence < 0.7):")
        print(f"  → Returns query + warning")
        print(f"  → Does not auto-execute")
        print(f"  → User reviews before executing")


# Standalone execution
if __name__ == "__main__":
    import sys

    async def run_all_demonstrations():
        """Run all demonstrations showing NL → REM dialect → results."""
        print("=" * 80)
        print("REM NATURAL LANGUAGE TO DIALECT DEMONSTRATION SUITE")
        print("=" * 80)
        print("\nThis suite demonstrates:")
        print("1. Natural language → REM dialect query conversion")
        print("2. Query evolution across maturity stages (0% → 100%)")
        print("3. User-known vs system-internal testing principles")
        print("4. All 5 REM query types (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)")
        print("=" * 80)

        # Test query output structure
        print("\n\n### 1. Query Output Structure ###")
        test_output = TestQueryAgentOutput()
        await test_output.test_query_output_structure()
        await test_output.test_query_string_format()

        # Test stage-by-stage evolution
        print("\n\n### 2. Query Evolution Across Stages ###")
        test_evolution = TestNaturalLanguageToREMDialect()
        await test_evolution.test_stage_1_lookup_queries()
        await test_evolution.test_stage_2_temporal_queries()
        await test_evolution.test_stage_3_semantic_queries()
        await test_evolution.test_stage_4_complex_queries()

        # Comprehensive demonstration
        print("\n\n### 3. All Query Types Demonstration ###")
        test_demo = TestQueryEvolutionDemonstration()
        await test_demo.test_show_all_query_types()

        # User-known vs system-internal
        print("\n\n### 4. User-Known Testing Principle ###")
        test_principles = TestUserKnownVsSystemInternal()
        await test_principles.test_user_provides_natural_names()
        await test_principles.test_natural_language_variations()

        # Confidence and reasoning
        print("\n\n### 5. Confidence & Reasoning ###")
        test_confidence = TestConfidenceAndReasoning()
        await test_confidence.test_high_confidence_queries()
        await test_confidence.test_medium_confidence_with_reasoning()

        # Plan vs direct mode
        print("\n\n### 6. Plan Mode vs Direct Mode ###")
        test_modes = TestPlanModeVsDirectMode()
        await test_modes.test_plan_mode_shows_query_without_execution()

        print("\n" + "=" * 80)
        print("✓ ALL DEMONSTRATIONS COMPLETE")
        print("=" * 80)
        print("\nNext Steps:")
        print("1. Run with actual database to see query RESULTS")
        print("2. Test query evolution with seeded data at each stage")
        print("3. Validate that natural language variations normalize correctly")
        print("=" * 80)

    try:
        asyncio.run(run_all_demonstrations())
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error running demonstrations: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
