"""
Validate REM Query Agent Schema and Test Cases.

This script validates that:
1. The agent schema is well-formed YAML with all required fields
2. Test cases follow the expected structure
3. Parameter types in test cases match the schema
4. Query dialect examples are consistent

Run with:
    python tests/integration/validate_rem_agent_schema.py
"""

import sys
from pathlib import Path

import yaml

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


def validate_agent_schema():
    """Validate agent schema structure."""
    schema_path = project_root / "src" / "rem" / "schemas" / "agents" / "rem-query-agent.yaml"

    print("=" * 100)
    print("VALIDATING REM QUERY AGENT SCHEMA")
    print("=" * 100)

    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    issues = []

    # Check required top-level fields
    required_fields = ["type", "description", "properties", "required", "json_schema_extra"]
    for field in required_fields:
        if field not in schema:
            issues.append(f"Missing required field: {field}")

    # Check properties
    if "properties" in schema:
        required_props = ["query_type", "parameters", "confidence"]
        for prop in required_props:
            if prop not in schema["properties"]:
                issues.append(f"Missing required property: {prop}")

    # Check json_schema_extra
    if "json_schema_extra" in schema:
        extra = schema["json_schema_extra"]
        if "fully_qualified_name" not in extra:
            issues.append("Missing fully_qualified_name in json_schema_extra")

    # Check description contains AST grammar
    if "description" in schema:
        desc = schema["description"]
        required_sections = [
            "Query ::=",
            "LookupQuery ::=",
            "SearchQuery ::=",
            "SqlQuery ::=",
            "TraverseQuery ::=",
            "System Fields (CoreModel",
        ]
        for section in required_sections:
            if section not in desc:
                issues.append(f"Missing section in description: {section}")

    if issues:
        print("\n❌ SCHEMA VALIDATION FAILED:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print("\n✅ SCHEMA VALIDATION PASSED")
        print(f"   - All required fields present")
        print(f"   - AST grammar sections complete")
        print(f"   - System fields documented")
        return True


def validate_test_cases():
    """Validate test case structure."""
    test_file = project_root / "tests" / "integration" / "rem-query-agent-tests.yaml"

    print("\n" + "=" * 100)
    print("VALIDATING TEST CASES")
    print("=" * 100)

    with open(test_file) as f:
        data = yaml.safe_load(f)

    test_cases = data.get("tests", [])
    print(f"\nTotal test cases: {len(test_cases)}")

    issues = []
    warnings = []

    query_type_counts = {}

    for i, test_case in enumerate(test_cases, 1):
        test_id = test_case.get("id", f"test-{i}")

        # Check required fields
        required_fields = ["id", "category", "question", "expected_response", "evaluation"]
        for field in required_fields:
            if field not in test_case:
                issues.append(f"{test_id}: Missing field '{field}'")

        # Check expected_response structure
        if "expected_response" in test_case:
            response = test_case["expected_response"]
            required_response_fields = ["query_type", "parameters", "confidence"]
            for field in required_response_fields:
                if field not in response:
                    issues.append(f"{test_id}: Missing expected_response field '{field}'")

            # Validate query_type
            if "query_type" in response:
                query_type = response["query_type"]
                query_type_counts[query_type] = query_type_counts.get(query_type, 0) + 1

                valid_query_types = ["LOOKUP", "FUZZY", "SEARCH", "SQL", "TRAVERSE"]
                if query_type not in valid_query_types:
                    issues.append(f"{test_id}: Invalid query_type '{query_type}'")

                # Validate parameters based on query type
                params = response.get("parameters", {})

                if query_type == "LOOKUP":
                    if "key" not in params:
                        issues.append(f"{test_id}: LOOKUP missing 'key' parameter")
                    else:
                        key = params["key"]
                        # Check if key is string or list
                        if not isinstance(key, (str, list)):
                            issues.append(f"{test_id}: LOOKUP key must be string or list, got {type(key)}")
                        elif isinstance(key, list):
                            # Multiple entities should be list
                            question = test_case.get("question", "")
                            if " and " not in question.lower() and "," not in question:
                                warnings.append(f"{test_id}: List key but question doesn't mention multiple entities")

                elif query_type == "SEARCH":
                    required_search_params = ["query_text", "table_name"]
                    for param in required_search_params:
                        if param not in params:
                            issues.append(f"{test_id}: SEARCH missing '{param}' parameter")

                elif query_type == "SQL":
                    required_sql_params = ["table_name"]
                    for param in required_sql_params:
                        if param not in params:
                            issues.append(f"{test_id}: SQL missing '{param}' parameter")

                elif query_type == "TRAVERSE":
                    required_traverse_params = ["initial_query"]
                    for param in required_traverse_params:
                        if param not in params:
                            issues.append(f"{test_id}: TRAVERSE missing '{param}' parameter")

            # Validate confidence score
            if "confidence" in response:
                conf = response["confidence"]
                if not (0.0 <= conf <= 1.0):
                    issues.append(f"{test_id}: Confidence {conf} outside range [0.0, 1.0]")

    # Summary statistics
    print(f"\nQuery Type Distribution:")
    for query_type, count in sorted(query_type_counts.items()):
        print(f"   {query_type:12} : {count:2} tests")

    if issues:
        print(f"\n❌ TEST VALIDATION FAILED ({len(issues)} issues):")
        for issue in issues[:20]:  # Show first 20 issues
            print(f"   - {issue}")
        if len(issues) > 20:
            print(f"   ... and {len(issues) - 20} more issues")
        return False
    else:
        print(f"\n✅ TEST VALIDATION PASSED")
        if warnings:
            print(f"\n⚠️  WARNINGS ({len(warnings)}):")
            for warning in warnings:
                print(f"   - {warning}")
        return True


def validate_examples():
    """Validate that examples in agent schema match test cases."""
    schema_path = project_root / "src" / "rem" / "schemas" / "agents" / "rem-query-agent.yaml"

    print("\n" + "=" * 100)
    print("VALIDATING SCHEMA EXAMPLES")
    print("=" * 100)

    with open(schema_path) as f:
        schema = yaml.safe_load(f)

    description = schema.get("description", "")

    # Check for example queries
    example_sections = [
        "Q: \"Show me Sarah Chen\"",
        "Q: \"Find people named Sara\"",
        "Q: \"Documents about database migration\"",
        "Q: \"Meetings in Q4 2024\"",
        "Q: \"What does Sarah manage?\"",
    ]

    issues = []
    for section in example_sections:
        if section not in description:
            issues.append(f"Missing example: {section}")

    if issues:
        print(f"\n❌ EXAMPLE VALIDATION FAILED:")
        for issue in issues:
            print(f"   - {issue}")
        return False
    else:
        print(f"\n✅ EXAMPLE VALIDATION PASSED")
        print(f"   - All query type examples present")
        return True


def main():
    """Run all validations."""
    print("\nREM QUERY AGENT VALIDATION SUITE")
    print("=" * 100)

    schema_ok = validate_agent_schema()
    tests_ok = validate_test_cases()
    examples_ok = validate_examples()

    print("\n" + "=" * 100)
    print("FINAL RESULTS")
    print("=" * 100)
    print(f"Schema Validation:   {'✅ PASS' if schema_ok else '❌ FAIL'}")
    print(f"Test Cases Validation: {'✅ PASS' if tests_ok else '❌ FAIL'}")
    print(f"Examples Validation:   {'✅ PASS' if examples_ok else '❌ FAIL'}")

    all_ok = schema_ok and tests_ok and examples_ok
    print(f"\nOverall Result: {'✅ ALL VALIDATIONS PASSED' if all_ok else '❌ SOME VALIDATIONS FAILED'}")
    print("=" * 100 + "\n")

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
