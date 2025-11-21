"""Demo script showing the three merge strategies with sample datasets."""

import json
from rem.utils.agentic_chunking import merge_results, MergeStrategy


def print_section(title: str):
    """Print section header."""
    print(f"\n{'=' * 80}")
    print(f"{title}")
    print('=' * 80)


def demo_concatenate_list():
    """Demonstrate CONCATENATE_LIST strategy (default)."""
    print_section("STRATEGY 1: CONCATENATE_LIST (Default)")

    print("\nUse Case: CV/Resume extraction from multiple chunks")
    print("\nInput: 3 chunks of CV data")

    chunk_results = [
        {
            "candidate_name": "Jane Smith",
            "email": "jane@example.com",
            "skills": [
                {"name": "Python", "level": "expert"},
                {"name": "SQL", "level": "advanced"},
            ],
            "experience": [
                {"company": "TechCorp", "years": 3, "role": "Senior Dev"}
            ],
            "total_years": 6,
        },
        {
            "candidate_name": "Jane Smith",
            "email": "jane@example.com",
            "skills": [
                {"name": "Docker", "level": "intermediate"},
                {"name": "React", "level": "advanced"},
            ],
            "experience": [
                {"company": "StartupXYZ", "years": 2, "role": "Tech Lead"}
            ],
            "total_years": 6,
        },
        {
            "candidate_name": "Jane Smith",
            "email": None,  # Missing in this chunk
            "skills": [
                {"name": "AWS", "level": "expert"},
            ],
            "experience": [
                {"company": "BigCorp", "years": 1, "role": "Engineer"}
            ],
            "total_years": None,  # Missing
        },
    ]

    for i, chunk in enumerate(chunk_results, 1):
        print(f"\nChunk {i}:")
        print(json.dumps(chunk, indent=2))

    merged = merge_results(chunk_results, MergeStrategy.CONCATENATE_LIST)

    print("\n" + "-" * 80)
    print("MERGED RESULT:")
    print(json.dumps(merged, indent=2))

    print("\n" + "-" * 80)
    print("KEY BEHAVIORS:")
    print(f"  ✓ Lists concatenated: {len(merged['skills'])} skills (2+2+1)")
    print(f"  ✓ Lists concatenated: {len(merged['experience'])} experiences (1+1+1)")
    print(f"  ✓ Scalar kept first: total_years = {merged['total_years']} (from chunk 1)")
    print(f"  ✓ None handled: email = '{merged['email']}' (chunk 1's value, not None)")


def demo_merge_json_deep():
    """Demonstrate MERGE_JSON strategy."""
    print_section("STRATEGY 2: MERGE_JSON (Deep Recursive Merge)")

    print("\nUse Case: Contract analysis with nested structure")
    print("\nInput: 2 chunks of contract data")

    chunk_results = [
        {
            "contract_title": "Software License Agreement",
            "parties": [
                {"name": "Acme Corp", "role": "licensor"},
            ],
            "terms": {
                "license": {
                    "type": "perpetual",
                    "scope": "worldwide",
                },
                "financial": {
                    "license_fee": 50000,
                    "currency": "USD",
                },
            },
            "obligations": [
                {"party": "Acme Corp", "duty": "Provide software updates"}
            ],
        },
        {
            "contract_title": "Software License Agreement",
            "parties": [
                {"name": "Beta Inc", "role": "licensee"},
            ],
            "terms": {
                "license": {
                    "duration": "unlimited",
                    "transferable": False,
                },
                "financial": {
                    "maintenance_fee": 10000,
                    "payment_schedule": "annual",
                },
                "support": {
                    "level": "enterprise",
                    "hours": "24/7",
                },
            },
            "obligations": [
                {"party": "Beta Inc", "duty": "Pay maintenance fees"}
            ],
        },
    ]

    for i, chunk in enumerate(chunk_results, 1):
        print(f"\nChunk {i}:")
        print(json.dumps(chunk, indent=2))

    merged = merge_results(chunk_results, MergeStrategy.MERGE_JSON)

    print("\n" + "-" * 80)
    print("MERGED RESULT:")
    print(json.dumps(merged, indent=2))

    print("\n" + "-" * 80)
    print("KEY BEHAVIORS:")
    print(f"  ✓ Lists merged: {len(merged['parties'])} parties (1+1)")
    print(f"  ✓ Deep merge: terms.license has {len(merged['terms']['license'])} fields (2+2)")
    print(f"  ✓ Deep merge: terms.financial has {len(merged['terms']['financial'])} fields (2+2)")
    print(f"  ✓ New keys added: terms.support appeared in chunk 2")
    print(f"  ✓ Nested preserved: Full hierarchy maintained")


def demo_comparison():
    """Compare CONCATENATE_LIST vs MERGE_JSON on same data."""
    print_section("COMPARISON: Same Data, Different Strategies")

    print("\nInput: Session analysis with nested topics")

    chunk_results = [
        {
            "interests": ["AI", "ML"],
            "sessions_count": 25,
            "topics": {
                "AI": {"count": 15, "sentiment": "positive"},
                "ML": {"count": 10, "sentiment": "neutral"},
            },
        },
        {
            "interests": ["Python", "Data"],
            "sessions_count": 15,
            "topics": {
                "Python": {"count": 12, "sentiment": "positive"},
                "Data": {"count": 3, "sentiment": "neutral"},
            },
        },
    ]

    print(json.dumps(chunk_results, indent=2))

    # Strategy 1: CONCATENATE_LIST
    merged_concat = merge_results(chunk_results, MergeStrategy.CONCATENATE_LIST)
    print("\n" + "-" * 80)
    print("CONCATENATE_LIST Result:")
    print(json.dumps(merged_concat, indent=2))
    print("\nBehavior:")
    print(f"  - interests: {merged_concat['interests']}")
    print(f"  - sessions_count: {merged_concat['sessions_count']} (first chunk)")
    print(f"  - topics keys: {list(merged_concat['topics'].keys())} (shallow update)")

    # Strategy 2: MERGE_JSON
    merged_deep = merge_results(chunk_results, MergeStrategy.MERGE_JSON)
    print("\n" + "-" * 80)
    print("MERGE_JSON Result:")
    print(json.dumps(merged_deep, indent=2))
    print("\nBehavior:")
    print(f"  - interests: {merged_deep['interests']}")
    print(f"  - sessions_count: {merged_deep['sessions_count']} (first chunk)")
    print(f"  - topics keys: {list(merged_deep['topics'].keys())} (deep merge)")
    print(f"  - AI details preserved: {merged_deep['topics']['AI']}")
    print(f"  - Python details preserved: {merged_deep['topics']['Python']}")


def main():
    """Run all demonstrations."""
    print("\n" + "=" * 80)
    print("AGENTIC CHUNKING: Merge Strategies Demonstration")
    print("=" * 80)

    demo_concatenate_list()
    demo_merge_json_deep()
    demo_comparison()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("""
Strategy 1: CONCATENATE_LIST (Default)
  Best for: List-heavy extractions (skills, entities, items)
  Behavior: Lists concatenate, dicts update (shallow), scalars keep first

Strategy 2: MERGE_JSON
  Best for: Nested hierarchies (contracts, configs, complex objects)
  Behavior: Lists concatenate, dicts deep merge recursively, scalars keep first

Strategy 3: LLM_MERGE (Future)
  Best for: Semantic merging requiring intelligence
  Behavior: TBD - will use LLM to intelligently combine results

Choose based on your data structure:
  - Flat lists of items? Use CONCATENATE_LIST
  - Deep nested JSON? Use MERGE_JSON
  - Complex semantic conflicts? Use LLM_MERGE (when implemented)
""")


if __name__ == "__main__":
    main()
