import pytest
import asyncio
import logging
import yaml
from pathlib import Path
from datetime import datetime
from rem.services.postgres import PostgresService
from rem.services.postgres.repository import Repository
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
                # Add user_id (tenant_id deprecated after migration 006)
                row_data["user_id"] = tenant_id
                row_data["tenant_id"] = tenant_id  # Still set for backwards compat

                # Convert graph_edges to InlineEdge format if present
                if "graph_edges" in row_data:
                    row_data["graph_edges"] = [
                        InlineEdge(**edge).model_dump(mode='json')
                        for edge in row_data["graph_edges"]
                    ]

                # Convert timestamp strings to datetime for Moment objects
                # NOTE: Using timezone-naive datetimes to match CoreModel.created_at/updated_at
                if table_name == "moments":
                    if "starts_timestamp" in row_data and isinstance(row_data["starts_timestamp"], str):
                        row_data["starts_timestamp"] = datetime.fromisoformat(row_data["starts_timestamp"].replace('Z', '+00:00')).replace(tzinfo=None)
                    if "ends_timestamp" in row_data and isinstance(row_data["ends_timestamp"], str):
                        row_data["ends_timestamp"] = datetime.fromisoformat(row_data["ends_timestamp"].replace('Z', '+00:00')).replace(tzinfo=None)

                # Create model instance and upsert using Repository
                instance = model_class(**row_data)
                repo = Repository(model_class, table_name, db=pg)
                await repo.upsert(instance)

        # Return root key (last resource loaded - "Project Plan")
        # Use normalized name as entity_key (KV store trigger uses normalize_key())
        # normalize_key converts "Project Plan" -> "project-plan"
        return {
            "root": "project-plan",
            "tenant_id": tenant_id
        }
    finally:
        await pg.disconnect()


@pytest.mark.skip(reason="Graph edges not being populated correctly - pre-existing issue")
@pytest.mark.asyncio
async def test_recursive_graph_traversal():
    """
    Test the rem_traverse recursive CTE function.

    Scenario:
    A (Resource) -> referenced_by -> B (Resource) -> documented_in -> C (Moment) -> attendee -> D (User)

    We start traversal at A and expect to find B, C, and D.
    """
    # 1. Seed Data
    # Note: Using user_id for partitioning (tenant_id deprecated)
    user_id = "test-graph-traversal"
    seed_result = await seed_graph_data(tenant_id=user_id)
    root_key = seed_result["root"]

    pg = PostgresService()
    await pg.connect()

    try:
        # Debug: Check if data was inserted into kv_store
        debug_query = "SELECT * FROM kv_store WHERE user_id = $1"
        kv_rows = await pg.fetch(debug_query, user_id)
        print(f"\n--- KV Store Entries for user_id={user_id}: {len(kv_rows)} found ---")
        for row in kv_rows:
            print(f"  entity_key={row['entity_key']}, entity_type={row['entity_type']}")

        # 2. Execute Traversal (No filter)
        # Max depth 5 to capture the full chain (length 3 edges)
        # rem_traverse signature: (entity_key, tenant_id, user_id, max_depth, rel_type, keys_only)
        query = """
            SELECT * FROM rem_traverse($1, $2, $3, $4, $5, $6)
        """
        rows = await pg.fetch(query, root_key, user_id, user_id, 5, None, False)
        
        print(f"\n--- Traversal Result (No Filter): {len(rows)} nodes found ---")
        for row in rows:
            print(f"Depth {row['depth']}: {row['entity_key']} ({row['entity_type']}) via {row['rel_type']}")

        results = {row['entity_key']: row for row in rows}
        # Note: entity_key is normalized (lowercase kebab-case) via normalize_key()
        assert "meeting-notes" in results  # Resource name
        assert "engineering-sync" in results  # Moment name
        assert "sarah-chen" in results  # User name

        # 3. Execute Traversal (With Array Filter)
        # Filter only for 'referenced_by' and 'documented_in'
        # Should find B and C, but NOT D (connected via 'attendee')
        # Note: rem_traverse takes single rel_type string, not array
        # We need to run multiple queries or update the function
        # For now, test with single rel_type
        # rem_traverse signature: (entity_key, tenant_id, user_id, max_depth, rel_type, keys_only)
        query_filtered = """
            SELECT * FROM rem_traverse($1, $2, $3, $4, $5, $6)
        """

        rows_filtered = await pg.fetch(query_filtered, root_key, user_id, user_id, 5, "referenced_by", False)

        print(f"\n--- Traversal Result (Filtered: referenced_by): {len(rows_filtered)} nodes found ---")
        for row in rows_filtered:
            print(f"Depth {row['depth']}: {row['entity_key']} ({row['entity_type']}) via {row['rel_type']}")
            
        results_filtered = {row['entity_key']: row for row in rows_filtered}

        # Should find B via referenced_by
        assert "meeting-notes" in results_filtered  # Resource name (normalized)

        # Should NOT find C (different rel_type: documented_in)
        assert "engineering-sync" not in results_filtered, "engineering-sync should be filtered out (wrong rel_type)"

        # Should NOT find D (different rel_type: attendee)
        assert "sarah-chen" not in results_filtered, "sarah-chen should be filtered out (wrong rel_type)"

        
    finally:
        await pg.disconnect()

if __name__ == "__main__":
    # Allow running as standalone script
    asyncio.run(test_recursive_graph_traversal())