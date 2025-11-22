import pytest
import asyncio
import logging
from rem.services.postgres import PostgresService
from tests.data.graph_seed import seed_graph_data

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@pytest.mark.asyncio
async def test_recursive_graph_traversal():
    """
    Test the rem_traverse recursive CTE function.
    
    Scenario:
    A (Resource) -> referenced_by -> B (Resource) -> documented_in -> C (Moment) -> attendee -> D (User)
    
    We start traversal at A and expect to find B, C, and D.
    """
    # 1. Seed Data
    seed_result = await seed_graph_data(tenant_id="test-graph-traversal")
    root_key = seed_result["root"]
    tenant_id = seed_result["tenant_id"]
    
    pg = PostgresService()
    await pg.connect()
    
    try:
        # 2. Execute Traversal (No filter)
        # Max depth 5 to capture the full chain (length 3 edges)
        query = """
            SELECT * FROM rem_traverse($1, $2, $3)
        """
        rows = await pg.fetch(query, root_key, tenant_id, 5)
        
        print(f"\n--- Traversal Result (No Filter): {len(rows)} nodes found ---")
        for row in rows:
            print(f"Depth {row['depth']}: {row['entity_key']} ({row['entity_type']}) via {row['rel_type']}")

        results = {row['entity_key']: row for row in rows}
        assert "Meeting Notes" in results
        assert "Engineering Sync" in results
        assert "Sarah Chen" in results

        # 3. Execute Traversal (With Array Filter)
        # Filter only for 'referenced_by' and 'documented_in'
        # Should find B and C, but NOT D (connected via 'attendee')
        query_filtered = """
            SELECT * FROM rem_traverse($1, $2, $3, $4)
        """
        # Pass array as a list for asyncpg
        filter_types = ["referenced_by", "documented_in"]
        
        rows_filtered = await pg.fetch(query_filtered, root_key, tenant_id, 5, filter_types)
        
        print(f"\n--- Traversal Result (Filtered: {filter_types}): {len(rows_filtered)} nodes found ---")
        for row in rows_filtered:
            print(f"Depth {row['depth']}: {row['entity_key']} ({row['entity_type']}) via {row['rel_type']}")
            
        results_filtered = {row['entity_key']: row for row in rows_filtered}
        
        # Should find B (referenced_by)
        assert "Meeting Notes" in results_filtered
        
        # Should find C (documented_in)
        assert "Engineering Sync" in results_filtered
        
        # Should NOT find D (attendee)
        assert "Sarah Chen" not in results_filtered, "Sarah Chen should be filtered out"

        
    finally:
        await pg.disconnect()

if __name__ == "__main__":
    # Allow running as standalone script
    asyncio.run(test_recursive_graph_traversal())