"""Repository pattern for entity persistence."""

from .file_repository import FileRepository
from .resource_repository import ResourceRepository

__all__ = ["FileRepository", "ResourceRepository"]
