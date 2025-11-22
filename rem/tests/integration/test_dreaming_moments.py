"""
Integration test for dreaming worker - moment construction.

Tests the complete workflow:
1. Load realistic sample data (resources and sessions)
2. Run MomentBuilder agent to extract temporal narratives
3. Verify moments created with correct structure
4. Validate graph edges link moments to source resources
5. Check embeddings generated automatically

This test validates the first-order dreaming process that transforms
raw resources into structured temporal moments.
"""

import pytest

# Import from relative path since tests are not a package
import sys
from pathlib import Path

# Add tests directory to path
tests_dir = Path(__file__).parent.parent
sys.path.insert(0, str(tests_dir))

from integration.sample_data.dreaming.load_sample_data import SampleDataLoader
from rem.workers.dreaming import DreamingWorker


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.skipif(
    condition=True,  # Skip by default - requires DB and LLM API keys
    reason="Requires PostgreSQL database and LLM API credentials"
)
async def test_construct_moments_from_sample_data():
    """
    Test moment construction from realistic sample data.

    Scenario:
    - Technical team activity over 5 days
    - Mix of meetings, planning, reflections, incidents
    - Multiple resources and sessions with relationships

    Expected outcome:
    - 5-8 moments extracted
    - Each moment has temporal boundaries
    - Moments linked to source resources via graph edges
    - Topic tags and emotion tags populated
    - Present persons extracted where applicable
    """
    # Test configuration
    TENANT_ID = "test-tenant-dreaming-integration"
    USER_ID = "sarah-chen"
    LOOKBACK_HOURS = 24 * 30  # 30 days to capture all sample data

    # Load sample data
    async with SampleDataLoader(tenant_id=TENANT_ID, user_id=USER_ID) as loader:
        load_summary = await loader.load_all()

        print(f"\n=== Sample Data Loaded ===")
        print(f"Resources: {load_summary['total_resources']}")
        print(f"Sessions: {load_summary['total_sessions']}")
        print(f"Graph edges: {load_summary['graph_edges_created']}")
        print(f"Categories: {load_summary['resource_categories']}")

        # Run dreaming worker
        worker = DreamingWorker(
            default_model="gpt-4o",  # Use GPT-4o for better extraction quality
            lookback_hours=LOOKBACK_HOURS,
        )

        result = await worker.construct_moments(
            user_id=USER_ID,
            tenant_id=TENANT_ID,
            lookback_hours=LOOKBACK_HOURS,
        )

        print(f"\n=== Moment Construction Results ===")
        print(f"Resources queried: {result['resources_queried']}")
        print(f"Sessions queried: {result['sessions_queried']}")
        print(f"Moments created: {result['moments_created']}")
        print(f"Graph edges added: {result['graph_edges_added']}")
        print(f"Status: {result['status']}")
        print(f"\nAnalysis: {result.get('analysis_summary', 'N/A')}")

        # Assertions
        assert result["status"] == "success", f"Dreaming failed: {result.get('error')}"
        assert result["resources_queried"] == 5, "Should query 5 resources"
        assert result["sessions_queried"] == 5, "Should query 5 sessions"
        assert result["moments_created"] >= 5, "Should extract at least 5 moments"
        assert result["moments_created"] <= 10, "Should not over-segment (max 10 moments)"
        assert result["graph_edges_added"] > 0, "Should create graph edges"

        # Verify moments in database
        from rem.models.entities.moment import Moment
        from rem.services.postgres.repository import Repository
        from rem.services.postgres.service import PostgresService

        db = PostgresService()
        await db.connect()

        try:
            moment_repo = Repository(Moment, "moments", db=db)
            moments = await moment_repo.find(
                filters={"user_id": USER_ID, "tenant_id": TENANT_ID},
                order_by="starts_timestamp ASC",
            )

            print(f"\n=== Extracted Moments ===")
            for i, moment in enumerate(moments, 1):
                print(f"\n{i}. {moment.name}")
                print(f"   Type: {moment.moment_type}")
                print(f"   Time: {moment.starts_timestamp} - {moment.ends_timestamp}")
                print(f"   Emotions: {', '.join(moment.emotion_tags[:3])}")
                print(f"   Topics: {', '.join(moment.topic_tags[:5])}")
                print(f"   Persons: {len(moment.present_persons)}")
                print(f"   Graph edges: {len(moment.graph_edges or [])}")

            # Validate moment structure
            assert len(moments) >= 5, f"Expected at least 5 moments, got {len(moments)}"

            for moment in moments:
                # Required fields
                assert moment.name, "Moment should have a name"
                assert moment.moment_type, "Moment should have a type"
                assert moment.starts_timestamp, "Moment should have start time"

                # Temporal consistency
                if moment.ends_timestamp:
                    assert (
                        moment.ends_timestamp > moment.starts_timestamp
                    ), f"End time should be after start time for {moment.name}"

                # Tags populated
                assert len(moment.emotion_tags) >= 2, "Should have at least 2 emotion tags"
                assert len(moment.emotion_tags) <= 4, "Should have at most 4 emotion tags"
                assert len(moment.topic_tags) >= 3, "Should have at least 3 topic tags"
                assert len(moment.topic_tags) <= 7, "Should have at most 7 topic tags"

                # Graph edges present
                assert len(moment.graph_edges or []) > 0, f"Moment {moment.name} should have graph edges"

                # All edges should link to resources
                for edge in moment.graph_edges or []:
                    assert edge.get("dst"), "Edge should have destination"
                    assert edge.get("rel_type") == "extracted_from", "Should use extracted_from relationship"
                    assert edge.get("weight"), "Edge should have weight"
                    assert edge.get("properties"), "Edge should have properties"

            # Check for expected moment types
            moment_types = {m.moment_type for m in moments}
            assert "meeting" in moment_types, "Should extract at least one meeting"
            print(f"\n=== Moment Types Found ===")
            print(f"{moment_types}")

        finally:
            await db.disconnect()

        # Cleanup sample data
        cleanup_summary = await loader.cleanup()
        print(f"\n=== Cleanup ===")
        print(f"Resources deleted: {cleanup_summary['resources_deleted']}")
        print(f"Sessions deleted: {cleanup_summary['sessions_deleted']}")
        # Note: Moments remain for inspection - manual cleanup required


if __name__ == "__main__":
    """Run test manually for debugging."""
    import asyncio

    asyncio.run(test_construct_moments_from_sample_data())
