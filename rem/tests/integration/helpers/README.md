# Integration Test Helpers

Centralized helper functions for populating test data in integration tests.

## Seed Data Helpers

### Overview

The `seed_data.py` module provides clean, Repository-based helper functions for populating test data. These helpers replace the old `test_seed_data_population.py` approach with a more maintainable solution.

### Available Functions

All functions follow the same pattern:
- Accept `PostgresService` instance
- Accept list of entity dicts
- Return list of created entity instances
- Handle timezone stripping automatically
- Use Repository pattern internally

#### `seed_resources(postgres_service, resources_data, generate_embeddings=False)`

Seed resources with optional embedding generation.

**Parameters:**
- `postgres_service`: PostgresService instance
- `resources_data`: List of resource dicts
- `generate_embeddings`: Whether to generate embeddings (default: False)

**Returns:** List of created Resource instances

**Example:**
```python
resources = await seed_resources(
    postgres_service,
    [
        {
            "entity_key": "docs://getting-started.md",
            "user_id": "acme-corp",
            "category": "documentation",
            "content": "Getting started guide...",
            "timestamp": "2024-01-01T10:00:00",  # Auto-converted to timezone-naive
        }
    ],
    generate_embeddings=False,
)
```

#### `seed_users(postgres_service, users_data)`

Seed user entities.

**Parameters:**
- `postgres_service`: PostgresService instance
- `users_data`: List of user dicts

**Returns:** List of created User instances

#### `seed_moments(postgres_service, moments_data)`

Seed moment entities with automatic timestamp parsing.

**Parameters:**
- `postgres_service`: PostgresService instance
- `moments_data`: List of moment dicts

**Returns:** List of created Moment instances

**Note:** Automatically parses both `starts_timestamp` and `ends_timestamp` fields.

#### `seed_messages(postgres_service, messages_data)`

Seed message entities.

**Parameters:**
- `postgres_service`: PostgresService instance
- `messages_data`: List of message dicts

**Returns:** List of created Message instances

#### `seed_files(postgres_service, files_data)`

Seed file entities.

**Parameters:**
- `postgres_service`: PostgresService instance
- `files_data`: List of file dicts

**Returns:** List of created File instances

#### `seed_schemas(postgres_service, schemas_data)`

Seed schema entities.

**Parameters:**
- `postgres_service`: PostgresService instance
- `schemas_data`: List of schema dicts

**Returns:** List of created Schema instances

### Timezone Handling

**CRITICAL:** All helpers automatically handle timezone conversion:

```python
# Parse timestamp if string (strip timezone to make naive UTC)
if "timestamp" in data and isinstance(data["timestamp"], str):
    dt = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    data["timestamp"] = dt.replace(tzinfo=None) if dt.tzinfo else dt
```

**Why:**
- System standardizes on timezone-naive datetimes
- Assumes all timestamps are UTC
- Prevents timezone mismatch errors

### Usage in Tests

**pytest fixture example:**

```python
from tests.integration.helpers import seed_resources

@pytest.fixture
async def populated_database(postgres_service):
    """Populate database with seed data."""
    resources = await seed_resources(
        postgres_service,
        SAMPLE_RESOURCES,
        generate_embeddings=False,
    )
    return {
        "resources": resources,
    }
```

**Direct usage in test:**

```python
from tests.integration.helpers import seed_resources, seed_users

async def test_query_with_seed_data(postgres_service, rem_query_service):
    """Test REM queries with seed data."""
    # Seed users first
    users = await seed_users(
        postgres_service,
        [{"entity_key": "user-1", "user_id": "acme-corp", "name": "Test User"}],
    )

    # Seed resources
    resources = await seed_resources(
        postgres_service,
        [{"entity_key": "doc-1", "user_id": "acme-corp", "content": "Test document"}],
    )

    # Run tests
    result = await rem_query_service.execute('LOOKUP "doc-1" IN resources', user_id="acme-corp")
    assert result.count == 1
```

### Default Values

Helpers set sensible defaults:
- `ordinal`: Defaults to 0 for resources
- Missing timestamps are left as None

### Implementation Details

All helpers use the Repository pattern:

```python
repo = Repository(Resource, "resources", db=postgres_service)
return await repo.upsert(
    resources,
    embeddable_fields=["content"],
    generate_embeddings=generate_embeddings,
)
```

### Migration from Old Approach

**Old (deprecated):**
```python
# Manual Resource creation
resources = []
for data in resources_data:
    if "ordinal" not in data:
        data["ordinal"] = 0
    resource = Resource(**data)
    resources.append(resource)

repo = Repository(Resource, "resources", db=postgres_service)
await repo.upsert(resources)
```

**New (current):**
```python
# Use helper
from tests.integration.helpers import seed_resources

resources = await seed_resources(postgres_service, resources_data)
```

### Error Handling

Helpers do NOT handle errors - let them propagate to test framework:
- Pydantic validation errors will fail the test
- Database connection errors will fail the test
- Missing required fields will fail the test

This is intentional - tests should fail loudly when data is invalid.

### See Also

- [Integration Tests README](../README.md)
- [Test Data README](../../data/seed/README.md)
- [Repository Pattern](../../../src/rem/services/postgres/repository.py)
