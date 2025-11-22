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
                # Add tenant_id
                row_data["tenant_id"] = tenant_id

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
        # Use uri as entity_key (matches KV store trigger)
        return {
            "root": "project-plan",
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
    # Note: Using user_id for partitioning (tenant_id deprecated)
    user_id = "test-graph-traversal"
    seed_result = await seed_graph_data(tenant_id=user_id)
    root_key = seed_result["root"]

    pg = PostgresService()
    await pg.connect()

    try:
        # 2. Execute Traversal (No filter)
        # Max depth 5 to capture the full chain (length 3 edges)
        # rem_traverse signature: (entity_key, user_id, max_depth, rel_type)
        query = """
            SELECT * FROM rem_traverse($1, $2, $3)
        """
        rows = await pg.fetch(query, root_key, user_id, 5)
        
        print(f"\n--- Traversal Result (No Filter): {len(rows)} nodes found ---")
        for row in rows:
            print(f"Depth {row['depth']}: {row['entity_key']} ({row['entity_type']}) via {row['rel_type']}")

        results = {row['entity_key']: row for row in rows}
        # Note: resources use uri as entity_key, moments/users use name
        assert "meeting-notes" in results  # Resource uri
        assert "Engineering Sync" in results  # Moment name
        assert "Sarah Chen" in results  # User name

        # 3. Execute Traversal (With Array Filter)
        # Filter only for 'referenced_by' and 'documented_in'
        # Should find B and C, but NOT D (connected via 'attendee')
        # Note: rem_traverse takes single rel_type string, not array
        # We need to run multiple queries or update the function
        # For now, test with single rel_type
        query_filtered = """
            SELECT * FROM rem_traverse($1, $2, $3, $4)
        """

        rows_filtered = await pg.fetch(query_filtered, root_key, user_id, 5, "referenced_by")

        print(f"\n--- Traversal Result (Filtered: referenced_by): {len(rows_filtered)} nodes found ---")
        for row in rows_filtered:
            print(f"Depth {row['depth']}: {row['entity_key']} ({row['entity_type']}) via {row['rel_type']}")
            
        results_filtered = {row['entity_key']: row for row in rows_filtered}

        # Should find B via referenced_by
        assert "meeting-notes" in results_filtered  # Resource uri

        # Should NOT find C (different rel_type: documented_in)
        assert "Engineering Sync" not in results_filtered, "Engineering Sync should be filtered out (wrong rel_type)"

        # Should NOT find D (different rel_type: attendee)
        assert "Sarah Chen" not in results_filtered, "Sarah Chen should be filtered out (wrong rel_type)"

        
    finally:
        await pg.disconnect()

if __name__ == "__main__":
    # Allow running as standalone script
    asyncio.run(test_recursive_graph_traversal())