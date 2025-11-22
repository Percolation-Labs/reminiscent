#!/usr/bin/env python3
"""
Test contract ingestion + agent analysis workflow with three side effects:
1. Agent structured response (analyzing the contract)
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
from rem.agentic.context import AgentContext
from rem.agentic.providers.pydantic_ai import create_agent


async def main():
    # Disable S3, use local filesystem
    original_bucket = settings.s3.bucket_name
    settings.s3.bucket_name = ""

    # Test parameters
    user_id = "contract-analysis-user"
    contract_file = Path("tests/data/content-examples/pdf/service_contract.pdf")

    if not contract_file.exists():
        print(f"❌ Contract file not found: {contract_file}")
        return

    print(f"🔍 Testing contract analysis workflow: {contract_file}")
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
        print(f"\n📥 Step 1: Ingesting contract file...")
        ingest_result = await content_service.ingest_file(
            file_uri=str(contract_file),
            tenant_id=user_id,
            user_id=user_id,
            category="legal-contract",
            tags=["contract", "test"],
            is_local_server=True,
        )

        print(f"   ✅ File ingested: {ingest_result['processing_status']}")
        print(f"   ✅ Resources created: {ingest_result['resources_created']}")

        # Run agent analysis on the parsed content
        print(f"\n🤖 Step 2: Running agent analysis on contract...")

        # Create agent context
        context = AgentContext(
            user_id=user_id,
            tenant_id=user_id,
            default_model=settings.llm.default_model,
        )

        # Load contract analyzer schema
        import importlib.resources
        import yaml

        schema_ref = importlib.resources.files("rem") / "schemas/agents/contract-analyzer.yaml"
        with open(str(schema_ref), "r") as f:
            contract_schema = yaml.safe_load(f)

        # Create agent
        agent = await create_agent(
            agent_schema_override=contract_schema,
            model_override=settings.llm.default_model,
        )

        # Prepare analysis query with the contract content
        analysis_query = f"""Analyze this consulting agreement:

{ingest_result['content'][:5000]}

Please extract:
- Contract type
- Parties involved
- Key financial terms
- Important obligations
- Any risk flags"""

        # Run agent
        result = await agent.run(analysis_query)

        # SIDE EFFECT 1: Agent's structured response
        print("\n" + "=" * 80)
        print("✅ SIDE EFFECT 1: Agent Structured Response")
        print("=" * 80)

        if hasattr(result, "output") and hasattr(result.output, "model_dump"):
            agent_output = result.output.model_dump()
            # Use default=str to handle date objects
            print(json.dumps(agent_output, indent=2, default=str))
        else:
            print(f"Agent response: {result}")

        # SIDE EFFECT 2: Parsed data on filesystem (markdown)
        print("\n" + "=" * 80)
        print("✅ SIDE EFFECT 2: Parsed Data on Filesystem")
        print("=" * 80)

        storage_path = ingest_result["storage_uri"].replace("file://", "")
        storage_file = Path(storage_path)

        if storage_file.exists():
            file_size = storage_file.stat().st_size
            print(f"📁 Storage location: {storage_path}")
            print(f"📊 File size: {file_size:,} bytes")
            print(f"✅ File exists on filesystem: True")
        else:
            print(f"❌ File not found at: {storage_path}")

        # SIDE EFFECT 3: Database records
        print("\n" + "=" * 80)
        print("✅ SIDE EFFECT 3: Database Records")
        print("=" * 80)

        # Check Files table
        files = await postgres_service.fetch(
            "SELECT id, name, size_bytes, processing_status FROM files WHERE user_id = $1",
            user_id
        )
        print(f"\n📋 Files table: {len(files)} record(s)")
        for file_row in files:
            print(f"  - {file_row['name']}: {file_row['size_bytes']:,} bytes ({file_row['processing_status']})")

        # Check Resources table
        resources = await postgres_service.fetch(
            "SELECT name, ordinal, LENGTH(content) as content_length FROM resources WHERE user_id = $1 ORDER BY ordinal",
            user_id
        )
        print(f"\n📦 Resources table: {len(resources)} record(s)")
        for resource_row in resources:
            print(f"  - Chunk {resource_row['ordinal']}: {resource_row['content_length']:,} chars")

        # Summary
        print("\n" + "=" * 80)
        print("📊 SUMMARY")
        print("=" * 80)
        print(f"✅ Agent analysis: Completed")
        print(f"✅ File on filesystem: {storage_file.exists()}")
        print(f"✅ Database - Files: {len(files)} record(s)")
        print(f"✅ Database - Resources: {len(resources)} chunk(s)")

        if storage_file.exists() and len(files) > 0 and len(resources) > 0:
            print("\n🎉 ALL THREE SIDE EFFECTS VERIFIED!")
        else:
            print("\n⚠️  Some side effects missing")

    finally:
        await postgres_service.disconnect()
        settings.s3.bucket_name = original_bucket


if __name__ == "__main__":
    asyncio.run(main())
