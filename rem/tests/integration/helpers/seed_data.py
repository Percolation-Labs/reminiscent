"""
Seed data helper for integration tests.

Provides simple functions to populate test data using the current Repository API.
"""

from datetime import datetime
from typing import Any

from rem.models.entities import File, Message, Moment, Resource, Schema, User
from rem.services.postgres import PostgresService, Repository


async def seed_resources(
    postgres_service: PostgresService,
    resources_data: list[dict[str, Any]],
    generate_embeddings: bool = False,
) -> list[Resource]:
    """
    Seed resources into the database.

    Args:
        postgres_service: PostgreSQL service instance
        resources_data: List of resource dicts
        generate_embeddings: Whether to generate embeddings

    Returns:
        List of created Resource instances
    """
    # Convert dicts to Resource models
    resources = []
    for data in resources_data:
        # Set defaults
        if "ordinal" not in data:
            data["ordinal"] = 0

        # Parse timestamp if string (strip timezone to make naive UTC)
        if "timestamp" in data and isinstance(data["timestamp"], str):
            dt = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            data["timestamp"] = dt.replace(tzinfo=None) if dt.tzinfo else dt

        resource = Resource(**data)
        resources.append(resource)

    # Upsert using Repository pattern
    repo = Repository(Resource, "resources", db=postgres_service)
    return await repo.upsert(
        resources,
        embeddable_fields=["content"],
        generate_embeddings=generate_embeddings,
    )


async def seed_users(
    postgres_service: PostgresService,
    users_data: list[dict[str, Any]],
) -> list[User]:
    """Seed users into the database."""
    users = [User(**data) for data in users_data]

    repo = Repository(User, "users", db=postgres_service)
    return await repo.upsert(users)


async def seed_moments(
    postgres_service: PostgresService,
    moments_data: list[dict[str, Any]],
) -> list[Moment]:
    """Seed moments into the database."""
    # Parse timestamps (strip timezone to make naive UTC)
    for data in moments_data:
        if "starts_timestamp" in data and isinstance(data["starts_timestamp"], str):
            dt = datetime.fromisoformat(data["starts_timestamp"])
            data["starts_timestamp"] = dt.replace(tzinfo=None) if dt.tzinfo else dt
        if "ends_timestamp" in data and isinstance(data["ends_timestamp"], str):
            dt = datetime.fromisoformat(data["ends_timestamp"])
            data["ends_timestamp"] = dt.replace(tzinfo=None) if dt.tzinfo else dt

    moments = [Moment(**data) for data in moments_data]

    repo = Repository(Moment, "moments", db=postgres_service)
    return await repo.upsert(moments)


async def seed_messages(
    postgres_service: PostgresService,
    messages_data: list[dict[str, Any]],
) -> list[Message]:
    """Seed messages into the database."""
    messages = [Message(**data) for data in messages_data]

    repo = Repository(Message, "messages", db=postgres_service)
    return await repo.upsert(messages)


async def seed_files(
    postgres_service: PostgresService,
    files_data: list[dict[str, Any]],
) -> list[File]:
    """Seed files into the database."""
    files = [File(**data) for data in files_data]

    repo = Repository(File, "files", db=postgres_service)
    return await repo.upsert(files)


async def seed_schemas(
    postgres_service: PostgresService,
    schemas_data: list[dict[str, Any]],
) -> list[Schema]:
    """Seed schemas into the database."""
    schemas = [Schema(**data) for data in schemas_data]

    repo = Repository(Schema, "schemas", db=postgres_service)
    return await repo.upsert(schemas)
