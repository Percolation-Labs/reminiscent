import pytest
import asyncio
import logging
import yaml
from pathlib import Path
from rem.services.postgres import PostgresService
from rem.models.entities import Resource, Moment, User
from rem.models.core.inline_edge import InlineEdge

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_graph_data(tenant_id: str) -> dict[str, str]:
    """Load graph seed data from YAML file."""
    # Load YAML
    yaml_path = Path(__file__).parent.parent / "data" / "graph_seed.yaml"
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    # Map table names to model classes
    MODEL_MAP = {
        "users": User,
        "moments": Moment,
        "resources": Resource,
    }

    # Connect to database
    pg = PostgresService()
    await pg.connect()

    try:
        # Load data
        for table_def in data:
            table_name = table_def["table"]
            key_field = table_def.get("key_field", "id")
            rows = table_def.get("rows", [])

            if table_name not in MODEL_MAP:
                continue

            model_class = MODEL_MAP[table_name]

            for row_data in rows:
                # Add tenant_id
                row_data["tenant_id"] = tenant_id

                # Convert graph_edges to InlineEdge format if present
                if "graph_edges" in row_data:
                    row_data["graph_edges"] = [
                        InlineEdge(**edge).model_dump(mode='json')
                        for edge in row_data["graph_edges"]
                    ]

                # Create model instance and upsert
                instance = model_class(**row_data)
                await pg.upsert(instance, model_class, table_name, entity_key_field=key_field)

        # Return root key (last resource loaded - "Project Plan")
        return {
            "root": "Project Plan",
            "tenant_id": tenant_id
        }
    finally:
        await pg.disconnect()


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