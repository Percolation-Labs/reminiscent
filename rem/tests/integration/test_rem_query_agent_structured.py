"""
Test REM Query Agent - Structured Pydantic Output Validation.

Tests that the REM Query Agent produces valid structured RemQuery objects
(not string queries) with proper parameter types and values.

This validates:
1. Correct query_type selection (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
2. Proper parameter types (Union[str, list[str]] for LOOKUP, etc.)
3. Appropriate confidence scores
4. Hybrid query support (SEARCH with WHERE clause)
5. PostgreSQL dialect awareness
6. System field knowledge (CoreModel fields)

Run with:
    pytest tests/integration/test_rem_query_agent_structured.py -v -s

Or directly:
    python tests/integration/test_rem_query_agent_structured.py
"""
from rem.settings import settings

import asyncio
import os
import sys
from pathlib import Path

import yaml

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from rem.agentic.providers.pydantic_ai import create_agent as create_ai_agent_provider
from rem.models.core.rem_query import QueryType


async def load_test_suite():
    """Load test cases from YAML file."""
    test_file = project_root / "tests" / "integration" / "rem-query-agent-tests.yaml"
    with open(test_file) as f:
        data = yaml.safe_load(f)
    return data


async def create_agent():
    """Create REM query agent from schema."""
    from rem.agentic.context import AgentContext

    schema_path = project_root / "src" / "rem" / "schemas" / "agents" / "rem-query-agent.yaml"

    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    # Create agent context (minimal)
    context = AgentContext(
        agent_schema_uri="rem-query-agent.yaml",  # Will be loaded from schema override
        tenant_id="test-tenant",
        user_id=settings.test.effective_user_id
    )

    # Create agent with schema override
    agent = await create_ai_agent_provider(
        context=context,
        agent_schema_override=schema,
        model_override="openai:gpt-4o-mini",  # Fast, cheap model for testing
    )

    return agent


def evaluate_response(test_case, actual_response):
    """
    Evaluate agent response against expected response.

    Returns:
        tuple: (passed: bool, notes: str)
    """
    test_id = test_case["id"]
    expected = test_case["expected_response"]

    # Extract actual values
    actual_query_type = actual_response.get("query_type")
    actual_params = actual_response.get("parameters", {})
    actual_confidence = actual_response.get("confidence", 0.0)

    issues = []

    # Check query type
    if actual_query_type != expected["query_type"]:
        issues.append(f"Wrong query type: got {actual_query_type}, expected {expected['query_type']}")

    # Check parameters (type-aware comparison)
    expected_params = expected["parameters"]
    for param_name, expected_value in expected_params.items():
        actual_value = actual_params.get(param_name)

        # Special handling for LOOKUP key parameter (Union[str, list[str]])
        if param_name == "key" and actual_query_type == "LOOKUP":
            # Normalize both to lists for comparison if one is a list
            expected_is_list = isinstance(expected_value, list)
            actual_is_list = isinstance(actual_value, list)

            if expected_is_list != actual_is_list:
                issues.append(
                    f"LOOKUP key type mismatch: expected {'list' if expected_is_list else 'string'}, "
                    f"got {'list' if actual_is_list else 'string'}"
                )
            elif expected_is_list and set(expected_value) != set(actual_value or []):
                issues.append(f"LOOKUP keys mismatch: expected {expected_value}, got {actual_value}")
            elif not expected_is_list and expected_value.lower() not in (actual_value or "").lower():
                issues.append(f"LOOKUP key mismatch: expected '{expected_value}', got '{actual_value}'")

        elif actual_value != expected_value:
            # Fuzzy match for strings (case-insensitive contains)
            if isinstance(expected_value, str) and isinstance(actual_value, str):
                if expected_value.lower() not in actual_value.lower():
                    issues.append(f"Parameter {param_name} mismatch: expected '{expected_value}', got '{actual_value}'")
            else:
                issues.append(f"Parameter {param_name} mismatch: expected {expected_value}, got {actual_value}")

    # Check confidence threshold
    min_confidence = expected.get("confidence", 0.7) - 0.1  # Allow 10% tolerance
    if actual_confidence < min_confidence:
        issues.append(f"Low confidence: {actual_confidence:.2f} < {min_confidence:.2f}")

    passed = len(issues) == 0
    notes = "; ".join(issues) if issues else "PASS"

    return passed, notes


async def run_tests():
    """Run all test cases from YAML file."""
    print("=" * 100)
    print("REM QUERY AGENT STRUCTURED TEST SUITE")
    print("=" * 100)

    # Load test suite
    test_data = await load_test_suite()
    test_cases = test_data["tests"]

    # Create agent
    print(f"\n📦 Creating REM Query Agent from schema: {test_data['test_suite']['agent_schema']}")
    agent = await create_agent()
    print(f"✅ Agent created successfully\n")

    # Run tests
    results = {
        "passed": 0,
        "failed": 0,
        "total": len(test_cases),
        "failures": []
    }

    for i, test_case in enumerate(test_cases, 1):
        test_id = test_case["id"]
        category = test_case["category"]
        question = test_case["question"]

        print(f"\n[{i}/{results['total']}] Test {test_id} ({category})")
        print(f"Question: \"{question}\"")

        try:
            # Run agent
            result = await agent.run(question)

            # Extract response (handle both dict and Pydantic model)
            if hasattr(result.data, "model_dump"):
                actual_response = result.data.model_dump()
            elif hasattr(result.data, "dict"):
                actual_response = result.data.dict()
            else:
                actual_response = result.data

            # Evaluate
            passed, notes = evaluate_response(test_case, actual_response)

            # Display results
            if passed:
                print(f"✅ PASS")
                print(f"   Query Type: {actual_response.get('query_type')}")
                print(f"   Parameters: {actual_response.get('parameters')}")
                print(f"   Confidence: {actual_response.get('confidence', 0.0):.2f}")
                results["passed"] += 1
            else:
                print(f"❌ FAIL: {notes}")
                print(f"   Expected: {test_case['expected_response']}")
                print(f"   Actual:   {actual_response}")
                results["failed"] += 1
                results["failures"].append({
                    "test_id": test_id,
                    "question": question,
                    "notes": notes,
                    "expected": test_case['expected_response'],
                    "actual": actual_response
                })

        except Exception as e:
            print(f"❌ ERROR: {e}")
            results["failed"] += 1
            results["failures"].append({
                "test_id": test_id,
                "question": question,
                "notes": f"Exception: {str(e)}",
                "expected": test_case['expected_response'],
                "actual": None
            })

    # Summary
    print("\n" + "=" * 100)
    print("TEST SUMMARY")
    print("=" * 100)
    print(f"Total Tests: {results['total']}")
    print(f"Passed:      {results['passed']} ({results['passed']/results['total']*100:.1f}%)")
    print(f"Failed:      {results['failed']} ({results['failed']/results['total']*100:.1f}%)")

    if results["failures"]:
        print("\n" + "=" * 100)
        print("FAILURES DETAIL")
        print("=" * 100)
        for failure in results["failures"]:
            print(f"\n❌ {failure['test_id']}: {failure['question']}")
            print(f"   Issue: {failure['notes']}")
            if failure['actual']:
                print(f"   Expected: {failure['expected']}")
                print(f"   Actual:   {failure['actual']}")

    print("\n" + "=" * 100)

    return results["failed"] == 0


async def main():
    """Main test runner."""
    success = await run_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
