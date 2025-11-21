"""Repository for Ontology entities."""

from typing import Optional
from uuid import UUID

from ...models.entities.ontology import Ontology
from ...services.postgres import PostgresService


class OntologyRepository:
    """Repository for managing Ontology entities.

    Provides CRUD operations for domain-specific extracted knowledge.
    """

    def __init__(self, postgres_service: PostgresService):
        self.postgres = postgres_service

    async def upsert(self, ontology: Ontology) -> Ontology:
        """Insert or update an ontology.

        Uses name as entity_key for idempotency.
        """
        return await self.postgres.upsert_entity(
            entity=ontology,
            entity_key=ontology.name,
            tenant_id=ontology.tenant_id,
        )

    async def get_by_id(self, ontology_id: UUID | str, tenant_id: str) -> Optional[Ontology]:
        """Retrieve ontology by ID."""
        # TODO: Implement once get_entity_by_id is available in PostgresService
        raise NotImplementedError("get_by_id not yet implemented in PostgresService")

    async def get_by_name(
        self, name: str, tenant_id: str
    ) -> Optional[Ontology]:
        """Retrieve ontology by name (entity key)."""
        # TODO: Implement once get_entity_by_key is available in PostgresService
        raise NotImplementedError("get_by_name not yet implemented in PostgresService")

    async def get_by_file_id(
        self, file_id: UUID | str, tenant_id: str
    ) -> list[Ontology]:
        """Retrieve all ontologies extracted from a file.

        Args:
            file_id: File UUID
            tenant_id: Tenant identifier for isolation

        Returns:
            List of Ontology instances (may be empty)
        """
        # TODO: Implement query by file_id once query interface available
        raise NotImplementedError("get_by_file_id not yet implemented")

    async def get_by_agent_schema(
        self, agent_schema_id: str, tenant_id: str
    ) -> list[Ontology]:
        """Retrieve all ontologies extracted using a specific agent schema.

        Args:
            agent_schema_id: Schema identifier
            tenant_id: Tenant identifier for isolation

        Returns:
            List of Ontology instances
        """
        # TODO: Implement query by agent_schema_id
        raise NotImplementedError("get_by_agent_schema not yet implemented")

    async def delete(self, ontology_id: UUID | str, tenant_id: str) -> bool:
        """Soft delete an ontology.

        Sets deleted_at timestamp.
        """
        # TODO: Implement once soft delete available in PostgresService
        raise NotImplementedError("delete not yet implemented in PostgresService")
