#!/usr/bin/env python3
"""
Quick verification script for integration test setup.

Checks:
1. PostgreSQL is running and accessible
2. All required tables exist
3. Migrations are applied
4. Sample seed data files exist
5. Engram processor is importable

Usage:
    python tests/integration/verify_setup.py
"""

import asyncio
import sys
from pathlib import Path

# Check imports
try:
    from rem.services.postgres import PostgresService
    from rem.workers.engram_processor import EngramProcessor
    from rem.models.entities import Resource, Moment, User

    print("✓ REM imports successful")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    print("  Run: uv sync")
    sys.exit(1)


async def verify_database():
    """Verify database connection and schema."""
    try:
        pg = PostgresService("postgresql://rem:rem@localhost:5050/rem")
        await pg.connect()
        print("✓ PostgreSQL connection successful")

        # Check required tables
        required_tables = [
            "users",
            "resources",
            "moments",
            "messages",
            "files",
            "schemas",
            "kv_store",
        ]

        result = await pg.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = ANY($1)
            ORDER BY table_name
            """,
            (required_tables,),
        )

        found_tables = {row["table_name"] for row in result}
        missing_tables = set(required_tables) - found_tables

        if missing_tables:
            print(f"✗ Missing tables: {', '.join(missing_tables)}")
            print("  Run migrations: sql/migrations/*.sql")
            await pg.disconnect()
            return False

        print(f"✓ All {len(required_tables)} required tables exist")

        # Check embeddings tables
        embeddings_tables = [f"embeddings_{t}" for t in ["users", "resources", "moments", "messages", "files", "schemas"]]
        result = await pg.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_name = ANY($1)
            """,
            (embeddings_tables,),
        )

        found_embeddings = len(result)
        print(f"✓ Found {found_embeddings}/{len(embeddings_tables)} embeddings tables")

        # Check triggers (verify KV store auto-population)
        result = await pg.execute(
            """
            SELECT DISTINCT trigger_name
            FROM information_schema.triggers
            WHERE trigger_schema = 'public'
            AND trigger_name LIKE '%kv_store%'
            """
        )

        if result:
            print(f"✓ KV store triggers exist ({len(result)} triggers)")
        else:
            print("⚠ No KV store triggers found - KV store may not auto-populate")

        await pg.disconnect()
        return True

    except Exception as e:
        print(f"✗ Database verification failed: {e}")
        print("  Check: docker compose up -d postgres")
        return False


def verify_test_data():
    """Verify test data files exist."""
    test_data_dir = Path(__file__).parent.parent / "data" / "seed"

    # Check seed data files
    seed_files = [
        "001_sample_data.yaml",
        "resources.yaml",
    ]

    missing_files = []
    for filename in seed_files:
        file_path = test_data_dir / filename
        if not file_path.exists():
            missing_files.append(filename)

    if missing_files:
        print(f"✗ Missing seed data files: {', '.join(missing_files)}")
        return False

    print(f"✓ All {len(seed_files)} seed data files exist")

    # Check engram files
    engrams_dir = test_data_dir / "files" / "engrams"
    if not engrams_dir.exists():
        print(f"✗ Engrams directory not found: {engrams_dir}")
        return False

    engram_files = list(engrams_dir.glob("*.yaml"))
    if not engram_files:
        print(f"✗ No engram files found in {engrams_dir}")
        return False

    print(f"✓ Found {len(engram_files)} engram files")

    # Check document files
    docs_dir = test_data_dir / "files" / "documents"
    if docs_dir.exists():
        doc_files = list(docs_dir.glob("*"))
        print(f"✓ Found {len(doc_files)} document files")

    return True


async def main():
    """Run all verification checks."""
    print("=" * 60)
    print("REM Integration Test Setup Verification")
    print("=" * 60)
    print()

    # Check imports
    print("Checking imports...")
    # Already done at top of file

    # Check database
    print("\nChecking database...")
    db_ok = await verify_database()

    # Check test data
    print("\nChecking test data...")
    data_ok = verify_test_data()

    # Summary
    print("\n" + "=" * 60)
    if db_ok and data_ok:
        print("✓ ALL CHECKS PASSED")
        print("\nReady to run integration tests:")
        print("  pytest tests/integration/test_seed_data_population.py -v --log-cli-level=INFO")
        print("=" * 60)
        return 0
    else:
        print("✗ SOME CHECKS FAILED")
        print("\nFix issues above before running integration tests.")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
