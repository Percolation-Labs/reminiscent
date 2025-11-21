"""Repository for OntologyConfig entities."""

import re
from typing import Optional
from uuid import UUID

from ...models.entities.file import File
from ...models.entities.ontology_config import OntologyConfig
from ...services.postgres import PostgresService


class OntologyConfigRepository:
    """Repository for managing OntologyConfig entities.

    Provides CRUD operations and file matching logic.
    """

    def __init__(self, postgres_service: PostgresService):
        self.postgres = postgres_service

    async def upsert(self, config: OntologyConfig) -> OntologyConfig:
        """Insert or update an ontology config.

        Uses name as entity_key for idempotency.
        """
        return await self.postgres.upsert_entity(
            entity=config,
            entity_key=config.name,
            tenant_id=config.tenant_id,
        )

    async def get_by_id(
        self, config_id: UUID | str, tenant_id: str
    ) -> Optional[OntologyConfig]:
        """Retrieve config by ID."""
        # TODO: Implement once get_entity_by_id is available in PostgresService
        raise NotImplementedError("get_by_id not yet implemented in PostgresService")

    async def get_by_name(
        self, name: str, tenant_id: str
    ) -> Optional[OntologyConfig]:
        """Retrieve config by name (entity key)."""
        # TODO: Implement once get_entity_by_key is available in PostgresService
        raise NotImplementedError("get_by_name not yet implemented in PostgresService")

    async def get_all_enabled(self, tenant_id: str) -> list[OntologyConfig]:
        """Retrieve all enabled configs for a tenant.

        Returns configs sorted by priority (descending).
        """
        # TODO: Implement query with WHERE enabled=true ORDER BY priority DESC
        raise NotImplementedError("get_all_enabled not yet implemented")

    async def get_matching_configs(
        self, file: File, tenant_id: str
    ) -> list[OntologyConfig]:
        """Find all enabled configs that match a file.

        Matching rules (ANY rule triggers match):
        - mime_type_pattern matches file.mime_type
        - uri_pattern matches file.uri
        - tag_filter: file must have ALL tags in filter

        Args:
            file: File to match against
            tenant_id: Tenant identifier

        Returns:
            List of matching OntologyConfig instances, sorted by priority (descending)
        """
        all_configs = await self.get_all_enabled(tenant_id)
        matching_configs = []

        for config in all_configs:
            if self._file_matches_config(file, config):
                matching_configs.append(config)

        # Sort by priority descending (higher priority first)
        return sorted(matching_configs, key=lambda c: c.priority, reverse=True)

    def _file_matches_config(self, file: File, config: OntologyConfig) -> bool:
        """Check if a file matches a config's rules.

        Returns True if ANY of the following match:
        - mime_type_pattern matches file.mime_type (regex)
        - uri_pattern matches file.uri (regex)
        - tag_filter: file has ALL tags in filter (set intersection)
        """
        # MIME type pattern match
        if config.mime_type_pattern and file.mime_type:
            try:
                if re.match(config.mime_type_pattern, file.mime_type):
                    return True
            except re.error:
                # Invalid regex, skip this rule
                pass

        # URI pattern match
        if config.uri_pattern and file.uri:
            try:
                if re.match(config.uri_pattern, file.uri):
                    return True
            except re.error:
                # Invalid regex, skip this rule
                pass

        # Tag filter match (file must have ALL tags)
        if config.tag_filter:
            file_tags = set(file.tags or [])
            required_tags = set(config.tag_filter)
            if required_tags.issubset(file_tags):
                return True

        return False

    async def delete(self, config_id: UUID | str, tenant_id: str) -> bool:
        """Soft delete a config.

        Sets deleted_at timestamp.
        """
        # TODO: Implement once soft delete available in PostgresService
        raise NotImplementedError("delete not yet implemented in PostgresService")
