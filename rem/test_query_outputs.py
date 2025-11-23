"""
Test script to demonstrate LOOKUP and TRAVERSE query outputs.
Shows the actual JSON returned with and without keys_only parameter.
"""
import asyncio
import json
from rem.services.postgres import get_postgres_service


async def main():
    db = get_postgres_service()
    await db.connect()

    try:
        # Use the test data from graph traversal test
        user_id = "test-graph-traversal"

        print("=" * 80)
        print("1. REM LOOKUP - Always returns full entity record")
        print("=" * 80)

        lookup_sql = """
            SELECT entity_record
            FROM rem_lookup($1, $2)
        """
        lookup_results = await db.fetch(lookup_sql, "Project Plan", user_id)

        if lookup_results:
            print(f"\nQuery: rem_lookup('Project Plan', '{user_id}')")
            print(f"\nResult count: {len(lookup_results)}")
            print("\nFull JSON output:")
            print(json.dumps(lookup_results[0]['entity_record'], indent=2))
        else:
            print("No results found for LOOKUP")

        print("\n" + "=" * 80)
        print("2. REM TRAVERSE with keys_only=TRUE (just graph structure)")
        print("=" * 80)

        traverse_keys_sql = """
            SELECT depth, entity_key, entity_type, entity_id, rel_type, rel_weight, path, entity_record
            FROM rem_traverse($1, $2, $3, $4, $5)
            ORDER BY depth, entity_key
        """
        traverse_keys_results = await db.fetch(
            traverse_keys_sql,
            "Project Plan",
            user_id,
            5,  # max_depth
            None,  # rel_type filter
            True  # keys_only=true
        )

        print(f"\nQuery: rem_traverse('Project Plan', '{user_id}', max_depth=5, rel_type=NULL, keys_only=TRUE)")
        print(f"\nResult count: {len(traverse_keys_results)}")
        print("\nFull JSON output (keys only):")
        for row in traverse_keys_results:
            print(json.dumps(dict(row), indent=2, default=str))
            print()

        print("=" * 80)
        print("3. REM TRAVERSE with keys_only=FALSE (full entity records)")
        print("=" * 80)

        traverse_full_sql = """
            SELECT depth, entity_key, entity_type, entity_id, rel_type, rel_weight, path, entity_record
            FROM rem_traverse($1, $2, $3, $4, $5)
            ORDER BY entity_key
        """
        traverse_full_results = await db.fetch(
            traverse_full_sql,
            "Project Plan",
            user_id,
            5,  # max_depth
            None,  # rel_type filter
            False  # keys_only=false
        )

        print(f"\nQuery: rem_traverse('Project Plan', '{user_id}', max_depth=5, rel_type=NULL, keys_only=FALSE)")
        print(f"\nResult count: {len(traverse_full_results)}")
        print("\nFull JSON output (with entity records):")
        for row in traverse_full_results:
            row_dict = dict(row)
            print(json.dumps(row_dict, indent=2, default=str))
            print()

    finally:
        await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
