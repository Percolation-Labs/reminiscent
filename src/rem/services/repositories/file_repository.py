"""FileRepository for file entity persistence."""

from rem.models.entities import File
from rem.services.postgres import PostgresService


class FileRepository:
    """Repository for File entities."""

    def __init__(self, db: PostgresService):
        self.db = db
        self.table = "files"

    async def upsert(self, file: File) -> File:
        """Upsert file record."""
        await self.db.batch_upsert(
            records=[file],
            model=File,
            table_name=self.table,
            entity_key_field="uri",
        )
        return file
