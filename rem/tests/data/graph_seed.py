import asyncio
import logging
from uuid import uuid4
from datetime import datetime

from rem.models.entities import Resource, Moment, User
from rem.models.core.inline_edge import InlineEdge
from rem.services.postgres import PostgresService
from rem.settings import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def seed_graph_data(tenant_id: str = "test-tenant-graph"):
    """
    Seed a test graph:
    Resource A -> Resource B -> Moment C -> User D
    """
    logger.info(f"Seeding graph data for tenant: {tenant_id}")
    
    pg = PostgresService()
    await pg.connect()

    try:
        # 1. Create User D ("Sarah") - Using User entity
        user_d = User(
            name="Sarah Chen",
            tenant_id=tenant_id,
            role="VP Engineering",
            email="sarah@example.com",
            metadata={"department": "Engineering"}
        )
        await pg.upsert(user_d, User, "users", entity_key_field="name")
        logger.info(f"Created User: {user_d.name}")

        # 2. Create Moment C ("Engineering Sync")
        # Connects to User D via graph edge
        moment_c = Moment(
            name="Engineering Sync",
            tenant_id=tenant_id,
            starts_timestamp=datetime.now(),
            moment_type="meeting",
            graph_edges=[
                InlineEdge(dst="Sarah Chen", rel_type="attendee", weight=1.0).model_dump(mode='json')
            ]
        )
        await pg.upsert(moment_c, Moment, "moments", entity_key_field="name")
        logger.info(f"Created Moment: {moment_c.name} -> Sarah Chen")

        # 3. Create Resource B ("Meeting Notes")
        # Connects to Moment C
        resource_b = Resource(
            name="Meeting Notes",
            tenant_id=tenant_id,
            content="Notes from the sync...",
            category="document",
            graph_edges=[
                InlineEdge(dst="Engineering Sync", rel_type="documented_in", weight=0.8).model_dump(mode='json')
            ]
        )
        await pg.upsert(resource_b, Resource, "resources", entity_key_field="name")
        logger.info(f"Created Resource: {resource_b.name} -> Engineering Sync")

        # 4. Create Resource A ("Project Plan")
        # Connects to Resource B
        resource_a = Resource(
            name="Project Plan",
            tenant_id=tenant_id,
            content="High level plan...",
            category="document",
            graph_edges=[
                InlineEdge(dst="Meeting Notes", rel_type="referenced_by", weight=0.5).model_dump(mode='json')
            ]
        )
        await pg.upsert(resource_a, Resource, "resources", entity_key_field="name")
        logger.info(f"Created Resource: {resource_a.name} -> Meeting Notes")
        
        logger.info("Graph seeding complete.")
        return {
            "root": resource_a.name,
            "tenant_id": tenant_id
        }

    finally:
        await pg.disconnect()

if __name__ == "__main__":
    # Allow running as standalone script
    asyncio.run(seed_graph_data())