"""ResourceRepository for resource entity persistence."""

from rem.models.entities import Resource
from rem.services.postgres import PostgresService


class ResourceRepository:
    """Repository for Resource entities with automatic embedding generation."""

    def __init__(self, db: PostgresService):
        self.db = db
        self.table = "resources"

    async def batch_upsert(self, resources: list[Resource]) -> list[Resource]:
        """
        Batch upsert resources with automatic embedding generation.

        Embeddings are generated asynchronously by the database triggers.
        """
        await self.db.batch_upsert(
            records=resources,
            model=Resource,
            table_name=self.table,
            entity_key_field="uri",
            embeddable_fields=["content"],
            generate_embeddings=True,
        )
        return resources
