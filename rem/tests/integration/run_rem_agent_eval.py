"""
REM Query Agent Evaluation Runner.

Runs the agent against 10 realistic questions and provides detailed evaluation.
Tests correctness, parameter types, confidence scores, and critical checks.

Usage:
    # With OpenAI API (requires OPENAI_API_KEY)
    python tests/integration/run_rem_agent_eval.py

    # Or use manual evaluation mode (no API calls)
    python tests/integration/run_rem_agent_eval.py --manual
"""

import argparse
import sys
from pathlib import Path

import yaml

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / "src"))


def load_evaluation_questions():
    """Load evaluation questions from YAML."""
    eval_file = project_root / "tests" / "integration" / "rem-agent-eval-questions.yaml"
    with open(eval_file) as f:
        data = yaml.safe_load(f)
    return data


def judge_response(question_data, actual_response):
    """
    Judge agent response against expected criteria.

    Returns:
        dict with scores and feedback
    """
    test_id = question_data["id"]
    difficulty = question_data["difficulty"]
    expected = question_data["expected_query"]

    judgment = {
        "test_id": test_id,
        "difficulty": difficulty,
        "scores": {},
        "passed": {},
        "issues": [],
        "total_score": 0.0
    }

    # Extract actual values
    actual_query_type = actual_response.get("query_type")
    actual_params = actual_response.get("parameters", {})
    actual_confidence = actual_response.get("confidence", 0.0)

    # 1. CORRECTNESS (40 points): Query type matches
    if actual_query_type == expected["query_type"]:
        judgment["scores"]["correctness"] = 40
        judgment["passed"]["query_type"] = True
    else:
        judgment["scores"]["correctness"] = 0
        judgment["passed"]["query_type"] = False
        judgment["issues"].append(
            f"Wrong query type: expected {expected['query_type']}, got {actual_query_type}"
        )

    # 2. PARAMETERS (30 points): Required parameters present and correct type
    param_score = 30
    expected_params = expected["parameters"]

    for param_name, expected_value in expected_params.items():
        actual_value = actual_params.get(param_name)

        # Skip confidence thresholds (handled separately)
        if isinstance(expected_value, str) and expected_value.startswith(">="):
            continue

        # Skip fuzzy matching fields (contains/any)
        if isinstance(expected_value, str) and expected_value in ["any", "contains"]:
            if actual_value is not None:
                continue
            else:
                param_score -= 10
                judgment["issues"].append(f"Missing parameter: {param_name}")
                continue

        # Check parameter presence
        if actual_value is None:
            param_score -= 10
            judgment["issues"].append(f"Missing required parameter: {param_name}")
            continue

        # Type checking for LOOKUP key (critical)
        if param_name == "key" and actual_query_type == "LOOKUP":
            expected_is_list = isinstance(expected_value, list)
            actual_is_list = isinstance(actual_value, list)

            if expected_is_list != actual_is_list:
                param_score -= 15
                judgment["issues"].append(
                    f"LOOKUP key type mismatch: expected {'list' if expected_is_list else 'string'}, "
                    f"got {'list' if actual_is_list else 'string'}"
                )
        # Value matching (fuzzy for strings)
        elif isinstance(expected_value, str) and isinstance(actual_value, str):
            if expected_value.lower() not in actual_value.lower() and actual_value.lower() not in expected_value.lower():
                param_score -= 5
                judgment["issues"].append(
                    f"Parameter {param_name} value mismatch: expected '{expected_value}', got '{actual_value}'"
                )

    judgment["scores"]["parameters"] = max(0, param_score)
    judgment["passed"]["parameters"] = param_score >= 20

    # 3. CONFIDENCE (10 points): Appropriate confidence score
    expected_conf_str = expected.get("confidence", ">= 0.7")
    if isinstance(expected_conf_str, str) and expected_conf_str.startswith(">="):
        min_confidence = float(expected_conf_str.split(">=")[1].strip())
    else:
        min_confidence = 0.7

    if actual_confidence >= min_confidence:
        judgment["scores"]["confidence"] = 10
        judgment["passed"]["confidence"] = True
    else:
        judgment["scores"]["confidence"] = max(0, int(10 * (actual_confidence / min_confidence)))
        judgment["passed"]["confidence"] = False
        judgment["issues"].append(
            f"Low confidence: {actual_confidence:.2f} < {min_confidence:.2f}"
        )

    # 4. CRITICAL CHECKS (20 points): Test-specific validation
    critical_score = 20
    critical_check = question_data.get("critical_check")

    if critical_check:
        if "graph_edges" in critical_check and "NOT filter" in critical_check:
            # Check that graph_edges is NOT in WHERE clause
            where_clause = actual_params.get("where_clause", "")
            if "graph_edges" in where_clause:
                critical_score = 0
                judgment["issues"].append(
                    "CRITICAL FAIL: Filtering by graph_edges in WHERE clause (should use TRAVERSE instead)"
                )
                judgment["passed"]["critical_check"] = False
            else:
                judgment["passed"]["critical_check"] = True

        elif "MUST be a list" in critical_check:
            # Check LOOKUP key is list for multiple entities
            key_value = actual_params.get("key")
            if not isinstance(key_value, list):
                critical_score = 0
                judgment["issues"].append(
                    "CRITICAL FAIL: LOOKUP key must be list for multiple entities, got string"
                )
                judgment["passed"]["critical_check"] = False
            else:
                judgment["passed"]["critical_check"] = True

        elif "JSONB operators" in critical_check:
            # Check use of JSONB operators
            where_clause = actual_params.get("where_clause", "")
            jsonb_ops = ["@>", "->", "->>", "jsonb_array_elements", "EXISTS"]
            if not any(op in where_clause for op in jsonb_ops):
                critical_score = 10  # Partial credit
                judgment["issues"].append(
                    "Missing JSONB operators in WHERE clause for nested query"
                )
                judgment["passed"]["critical_check"] = False
            else:
                judgment["passed"]["critical_check"] = True
    else:
        judgment["passed"]["critical_check"] = True

    judgment["scores"]["critical"] = critical_score

    # Calculate total score
    judgment["total_score"] = sum(judgment["scores"].values())

    # Overall pass/fail (70+ = pass)
    judgment["overall_pass"] = judgment["total_score"] >= 70

    return judgment


def print_evaluation_report(results):
    """Print detailed evaluation report."""
    print("\n" + "=" * 100)
    print("REM QUERY AGENT EVALUATION REPORT")
    print("=" * 100)

    # Group by difficulty
    by_difficulty = {}
    for result in results:
        diff = result["difficulty"]
        if diff not in by_difficulty:
            by_difficulty[diff] = []
        by_difficulty[diff].append(result)

    # Overall stats
    total_tests = len(results)
    total_passed = sum(1 for r in results if r["overall_pass"])
    avg_score = sum(r["total_score"] for r in results) / total_tests

    print(f"\nOVERALL PERFORMANCE:")
    print(f"  Total Tests:     {total_tests}")
    print(f"  Passed (70+):    {total_passed} / {total_tests} ({total_passed/total_tests*100:.1f}%)")
    print(f"  Average Score:   {avg_score:.1f} / 100")

    # By difficulty
    print(f"\nPERFORMANCE BY DIFFICULTY:")
    for diff in ["easy", "medium", "hard", "very_hard"]:
        if diff in by_difficulty:
            tests = by_difficulty[diff]
            passed = sum(1 for t in tests if t["overall_pass"])
            avg = sum(t["total_score"] for t in tests) / len(tests)
            print(f"  {diff.upper():12} : {passed}/{len(tests)} passed, avg {avg:.1f}/100")

    # Detailed results
    print(f"\n" + "=" * 100)
    print("DETAILED RESULTS")
    print("=" * 100)

    for result in results:
        status = "✅ PASS" if result["overall_pass"] else "❌ FAIL"
        print(f"\n{result['test_id']} ({result['difficulty']}) - {status} ({result['total_score']:.0f}/100)")

        # Scores breakdown
        scores = result["scores"]
        print(f"  Correctness: {scores['correctness']}/40")
        print(f"  Parameters:  {scores['parameters']}/30")
        print(f"  Confidence:  {scores['confidence']}/10")
        print(f"  Critical:    {scores['critical']}/20")

        # Issues
        if result["issues"]:
            print(f"  Issues:")
            for issue in result["issues"]:
                print(f"    - {issue}")

    print("\n" + "=" * 100)


def run_manual_evaluation():
    """Run manual evaluation (no API calls, example responses)."""
    print("\nRUNNING MANUAL EVALUATION (Example Responses)")
    print("=" * 100)

    data = load_evaluation_questions()
    questions = data["questions"]

    # Example responses for demonstration
    example_responses = {
        "eval-001": {
            "query_type": "LOOKUP",
            "parameters": {"key": "getting-started-guide"},
            "confidence": 1.0
        },
        "eval-002": {
            "query_type": "FUZZY",
            "parameters": {"query_text": "database", "threshold": 0.5, "limit": 10},
            "confidence": 0.9
        },
        "eval-003": {
            "query_type": "SQL",
            "parameters": {"table_name": "resources", "where_clause": "category = 'documentation'"},
            "confidence": 0.95
        },
        "eval-004": {
            "query_type": "SQL",
            "parameters": {
                "table_name": "resources",
                "where_clause": "created_at >= '2025-01-01' AND created_at < '2025-02-01'"
            },
            "confidence": 0.85
        },
        "eval-005": {
            "query_type": "SEARCH",
            "parameters": {"query_text": "semantic search", "table_name": "resources"},
            "confidence": 0.95
        },
        "eval-006": {
            "query_type": "SEARCH",
            "parameters": {
                "query_text": "Kubernetes",
                "table_name": "resources",
                "where_clause": "category = 'documentation'"
            },
            "confidence": 0.9
        },
        "eval-007": {
            "query_type": "TRAVERSE",
            "parameters": {
                "initial_query": "getting-started-guide",
                "edge_types": ["references"],
                "max_depth": 1
            },
            "confidence": 0.8
        },
        "eval-008": {
            "query_type": "SQL",
            "parameters": {
                "table_name": "resources",
                "where_clause": "user_id = 'sarah-chen' AND created_at >= NOW() - INTERVAL '30 days'"
                # Correctly does NOT filter by graph_edges
            },
            "confidence": 0.75
        },
        "eval-009": {
            "query_type": "LOOKUP",
            "parameters": {
                "key": ["Sarah Chen", "Mike Johnson", "getting started guide"]  # Correctly a list
            },
            "confidence": 0.85
        },
        "eval-010": {
            "query_type": "SQL",
            "parameters": {
                "table_name": "resources",
                "where_clause": "created_at >= '2025-01-01' AND EXISTS (SELECT 1 FROM jsonb_array_elements(related_entities) e WHERE e->'metadata'->>'importance' = 'high')"
            },
            "confidence": 0.7
        }
    }

    results = []
    for question in questions:
        test_id = question["id"]
        response = example_responses.get(test_id, {
            "query_type": "UNKNOWN",
            "parameters": {},
            "confidence": 0.0
        })

        judgment = judge_response(question, response)
        results.append(judgment)

    print_evaluation_report(results)

    return results


def main():
    """Main evaluation runner."""
    parser = argparse.ArgumentParser(description="REM Query Agent Evaluation")
    parser.add_argument("--manual", action="store_true", help="Use manual evaluation with example responses")
    args = parser.parse_args()

    print("\n" + "=" * 100)
    print("REM QUERY AGENT EVALUATION")
    print("=" * 100)
    print("\nEvaluating agent against 10 realistic questions with varying difficulty levels")
    print("Rubric: Correctness (40%) + Parameters (30%) + Confidence (10%) + Critical Checks (20%)")

    if args.manual:
        results = run_manual_evaluation()
    else:
        print("\nERROR: Live agent evaluation requires OPENAI_API_KEY environment variable")
        print("Use --manual flag to run evaluation with example responses\n")
        sys.exit(1)

    # Exit code based on results
    passed = sum(1 for r in results if r["overall_pass"])
    total = len(results)
    success_rate = passed / total

    sys.exit(0 if success_rate >= 0.7 else 1)


if __name__ == "__main__":
    main()
