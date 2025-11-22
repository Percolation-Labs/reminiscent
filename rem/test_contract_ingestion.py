#!/usr/bin/env python3
"""
Test contract ingestion and verify three side effects:
1. Structured response output
2. Parsed markdown file on filesystem
3. Files and resources inserted into database
"""
import asyncio
import json
from pathlib import Path

from rem.services.content import ContentService
from rem.services.postgres import PostgresService
from rem.services.postgres.repository import Repository
from rem.models.entities import File, Resource
from rem.settings import settings


async def main():
    # Disable S3, use local filesystem
    original_bucket = settings.s3.bucket_name
    settings.s3.bucket_name = ""
    # Test parameters
    user_id = "contract-test-user"
    contract_file = Path("tests/data/content-examples/pdf/service_contract.pdf")

    if not contract_file.exists():
        print(f"❌ Contract file not found: {contract_file}")
        return

    print(f"🔍 Testing contract ingestion: {contract_file}")
    print("=" * 80)

    # Connect to PostgreSQL
    postgres_service = PostgresService()
    await postgres_service.connect()

    try:
        # Clean up any existing data
        print(f"\n🧹 Cleaning up existing data for user: {user_id}")
        await postgres_service.execute(
            "DELETE FROM resources WHERE user_id = $1",
            params=(user_id,)
        )
        await postgres_service.execute(
            "DELETE FROM files WHERE user_id = $1",
            params=(user_id,)
        )

        # Create ContentService with repositories
        file_repo = Repository(File, db=postgres_service)
        resource_repo = Repository(Resource, db=postgres_service)
        content_service = ContentService(file_repo=file_repo, resource_repo=resource_repo)

        # Run ingestion
        print(f"\n📥 Ingesting contract file...")
        result = await content_service.ingest_file(
            file_uri=str(contract_file),
            tenant_id=user_id,
            user_id=user_id,
            category="legal-contract",
            tags=["contract", "test"],
            is_local_server=True,
        )

        # SIDE EFFECT 1: Structured response output
        print("\n" + "=" * 80)
        print("✅ SIDE EFFECT 1: Structured Response Output")
        print("=" * 80)
        print(json.dumps({
            "file_id": result["file_id"],
            "file_name": result["file_name"],
            "storage_uri": result["storage_uri"],
            "size_bytes": result["size_bytes"],
            "content_type": result["content_type"],
            "processing_status": result["processing_status"],
            "resources_created": result["resources_created"],
            "message": result["message"],
        }, indent=2))

        # SIDE EFFECT 2: Parsed data on filesystem (markdown)
        print("\n" + "=" * 80)
        print("✅ SIDE EFFECT 2: Parsed Data on Filesystem")
        print("=" * 80)

        storage_path = result["storage_uri"].replace("file://", "")
        storage_file = Path(storage_path)

        if storage_file.exists():
            file_size = storage_file.stat().st_size
            print(f"📁 Storage location: {storage_path}")
            print(f"📊 File size: {file_size:,} bytes")
            print(f"✅ File exists on filesystem: {storage_file.exists()}")

            # Check if markdown content was generated
            if result.get("content"):
                content_preview = result["content"][:500]
                print(f"\n📄 Content preview (first 500 chars):")
                print("-" * 80)
                print(content_preview)
                print("-" * 80)
        else:
            print(f"❌ File not found at: {storage_path}")

        # SIDE EFFECT 3: Database records
        print("\n" + "=" * 80)
        print("✅ SIDE EFFECT 3: Database Records")
        print("=" * 80)

        # Check Files table
        files = await postgres_service.fetch(
            "SELECT id, name, uri, size_bytes, mime_type, processing_status, user_id FROM files WHERE user_id = $1",
            user_id
        )
        print(f"\n📋 Files table: {len(files)} record(s)")
        for file_row in files:
            print(f"  - ID: {file_row['id']}")
            print(f"    Name: {file_row['name']}")
            print(f"    URI: {file_row['uri']}")
            print(f"    Size: {file_row['size_bytes']:,} bytes")
            print(f"    Status: {file_row['processing_status']}")

        # Check Resources table
        resources = await postgres_service.fetch(
            "SELECT id, name, user_id, category, ordinal, LENGTH(content) as content_length FROM resources WHERE user_id = $1 ORDER BY ordinal",
            user_id
        )
        print(f"\n📦 Resources table: {len(resources)} record(s)")
        for resource_row in resources:
            print(f"  - Name: {resource_row['name']}")
            print(f"    Category: {resource_row['category']}")
            print(f"    Ordinal: {resource_row['ordinal']}")
            print(f"    Content length: {resource_row['content_length']:,} chars")

        # Summary
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print(f"✅ Structured response: {result['processing_status']}")
        print(f"✅ File on filesystem: {storage_file.exists()}")
        print(f"✅ Database - Files: {len(files)} record(s)")
        print(f"✅ Database - Resources: {len(resources)} chunk(s)")

        if result["processing_status"] == "completed" and storage_file.exists() and len(files) > 0 and len(resources) > 0:
            print("\n🎉 ALL THREE SIDE EFFECTS VERIFIED!")
        else:
            print("\n⚠️  Some side effects missing")

    finally:
        await postgres_service.disconnect()
        settings.s3.bucket_name = original_bucket


if __name__ == "__main__":
    asyncio.run(main())
