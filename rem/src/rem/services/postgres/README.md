### PostgresService - CloudNativePG Database Operations

Comprehensive service for PostgreSQL 18 with pgvector, including:
- Entity CRUD with automatic embeddings
- KV_STORE cache for O(1) lookups
- Fuzzy text search with pg_trgm
- Background index creation
- Batch operations with transaction management

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PostgresService                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Batch Upsert Pipeline                                │  │
│  │  1. Validate entities                                 │  │
│  │  2. Generate embeddings (batch OpenAI API)           │  │
│  │  3. Upsert to primary tables                         │  │
│  │  4. Upsert to embeddings_<table>                     │  │
│  │  5. Upsert to KV_STORE (via trigger)                │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Background Index Thread                              │  │
│  │  - Monitors pending indexes queue                     │  │
│  │  - Creates indexes CONCURRENTLY                       │  │
│  │  - Handles index creation failures                    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    Database Schema                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Primary Tables:        resources, moments, users, etc.     │
│  Embeddings Tables:     embeddings_resources, etc.          │
│  KV_STORE Cache:        UNLOGGED table for O(1) lookups    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Core Design Patterns

### 1. Entity Storage Pattern

**Primary Tables** store entities with system fields:
```sql
CREATE TABLE resources (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(100),     -- Optional: for future multi-tenant SaaS use
    user_id VARCHAR(100) NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    content TEXT,
    graph_edges JSONB DEFAULT '[]',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
```

### 2. Embeddings Pattern

**Multiple embeddings per record** with provider flexibility:

```sql
CREATE TABLE embeddings_resources (
    id UUID PRIMARY KEY,
    entity_id UUID REFERENCES resources(id) ON DELETE CASCADE,
    field_name VARCHAR(100) NOT NULL,  -- 'description', 'content', etc.
    provider VARCHAR(50) NOT NULL,      -- 'openai', 'cohere', etc.
    model VARCHAR(100) NOT NULL,        -- 'text-embedding-3-small'
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entity_id, field_name, provider)
);
```

**Key Features**:
- One row per (entity, field, provider)
- Unique constraint prevents duplicates
- Supports multiple embedding providers
- CASCADE delete when entity deleted

**Embedding Configuration**:
```python
from pydantic import BaseModel, Field

class Resource(BaseModel):
    name: str
    description: str = Field(
        ...,
        json_schema_extra={"embed": True}  # Explicit embedding
    )
    content: str  # Auto-embeds (default for content fields)
    notes: str = Field(
        ...,
        json_schema_extra={"embed": False}  # Disable embedding
    )
```

**Default Embedding Fields** (if not explicitly disabled):
- `content`
- `description`
- `summary`
- `text`
- `body`
- `message`
- `notes`

### 3. KV_STORE Cache Pattern

**UNLOGGED table** for fast entity lookups:

```sql
CREATE UNLOGGED TABLE kv_store (
    entity_key VARCHAR(255) NOT NULL,   -- Natural language key
    entity_type VARCHAR(100) NOT NULL,  -- Table name
    entity_id UUID NOT NULL,            -- Foreign key to entity
    tenant_id VARCHAR(100),             -- Optional: for future multi-tenant SaaS use
    user_id VARCHAR(100) NOT NULL,      -- Primary isolation scope
    content_summary TEXT,               -- For fuzzy search
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, entity_key)
);
```

**Key Features**:
- UNLOGGED = faster writes, no WAL overhead
- Rebuilt automatically from primary tables on restart
- O(1) lookups by entity_key
- User-scoped filtering when `user_id IS NOT NULL`
- Fuzzy search via pg_trgm indexes

**Trigger-based Updates**:
```sql
CREATE TRIGGER trg_resources_kv_store
AFTER INSERT OR UPDATE OR DELETE ON resources
FOR EACH ROW EXECUTE FUNCTION fn_resources_kv_store_upsert();
```

Automatically maintains KV_STORE on entity changes.

### 4. Batch Upsert Pattern

**Efficient bulk operations** with automatic embedding generation:

```python
from rem.services import PostgresService

service = PostgresService(connection_string)

# Batch upsert entities
entities = [
    Resource(name="doc-1", description="First document", content="..."),
    Resource(name="doc-2", description="Second document", content="..."),
]

result = await service.batch_upsert(
    table_name="resources",
    entities=entities,
    entity_key_field="name",
    generate_embeddings=True,  # Auto-generate embeddings
    embedding_provider="openai",
    embedding_model="text-embedding-3-small"
)

# Result:
# {
#     "inserted": 2,
#     "updated": 0,
#     "embeddings_generated": 4,  # 2 entities × 2 fields (description, content)
#     "kv_entries": 2
# }
```

**Pipeline Steps**:
1. **Validate** entities against Pydantic model
2. **Generate embeddings** in batch (OpenAI API supports up to 2048 texts)
3. **Upsert entities** to primary table (ON CONFLICT DO UPDATE)
4. **Upsert embeddings** to `embeddings_<table>`
5. **Update KV_STORE** (automatic via trigger)
6. **Queue background indexes** if needed

### 5. Embedding Generation Pattern

**Batch OpenAI API calls** for performance:

```python
# Collect all texts to embed
texts_to_embed = []
for entity in entities:
    for field_name in embeddable_fields:
        text = getattr(entity, field_name)
        if text:
            texts_to_embed.append({
                "text": text,
                "entity_id": entity.id,
                "field_name": field_name
            })

# Batch generate embeddings (up to 2048 texts per call)
embeddings = await generate_embeddings_batch(
    texts=[item["text"] for item in texts_to_embed],
    provider="openai",
    model="text-embedding-3-small"
)

# Map embeddings back to entities and fields
for item, embedding in zip(texts_to_embed, embeddings):
    await upsert_embedding(
        entity_id=item["entity_id"],
        field_name=item["field_name"],
        provider="openai",
        model="text-embedding-3-small",
        embedding=embedding
    )
```

**Supported Providers**:
- `openai` - text-embedding-3-small, text-embedding-3-large
- `cohere` - embed-english-v3.0, embed-multilingual-v3.0
- Custom providers via plugin system

### 6. Background Index Creation Pattern

**Non-blocking index creation** after data load:

```python
# Index creation thread
class BackgroundIndexer:
    def __init__(self, postgres_service):
        self.service = postgres_service
        self.queue = asyncio.Queue()
        self.running = False

    async def queue_index(self, table_name: str, index_type: str):
        """Queue an index for background creation."""
        await self.queue.put({
            "table_name": table_name,
            "index_type": index_type,
            "attempts": 0
        })

    async def run(self):
        """Background thread that creates indexes CONCURRENTLY."""
        self.running = True
        while self.running:
            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=5.0)

                # Create index CONCURRENTLY (non-blocking)
                await self.service.create_index_concurrently(
                    table_name=item["table_name"],
                    index_type=item["index_type"]
                )

                logger.info(f"Created index for {item['table_name']}")

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                # Retry with backoff
                if item["attempts"] < 3:
                    item["attempts"] += 1
                    await asyncio.sleep(2 ** item["attempts"])
                    await self.queue.put(item)
                else:
                    logger.error(f"Failed to create index after 3 attempts: {e}")
```

**Index Types**:
- **HNSW** for vector similarity (embeddings)
- **GIN** for JSONB (graph_edges, metadata)
- **GIN with pg_trgm** for fuzzy text search
- **B-tree** for foreign keys and common filters

### 7. REM Query Integration

**LOOKUP Queries** use KV_STORE for O(1) access:

```python
# REM LOOKUP query
result = await service.lookup_entity(
    entity_key="sarah-chen",
    user_id="user123"
)

# SQL:
# SELECT entity_id, entity_type, metadata
# FROM kv_store
# WHERE user_id = $1 AND entity_key = $2;
```

**FUZZY Queries** use pg_trgm indexes:

```python
# REM FUZZY query
results = await service.fuzzy_search(
    query="sara",
    user_id="user123",
    threshold=0.3,
    limit=10
)

# SQL:
# SELECT entity_key, entity_type, similarity(entity_key, $1) AS score
# FROM kv_store
# WHERE user_id = $2 AND entity_key % $1
# ORDER BY score DESC
# LIMIT $3;
```

**SEARCH Queries** use vector similarity:

```python
# REM SEARCH query
results = await service.vector_search(
    table_name="resources",
    query_text="machine learning documentation",
    field_name="content",
    user_id="user123",
    limit=10,
    min_similarity=0.7
)

# SQL:
# SELECT r.*, 1 - (e.embedding <=> $1) AS similarity
# FROM resources r
# JOIN embeddings_resources e ON e.entity_id = r.id
# WHERE r.user_id = $2
# AND e.field_name = 'content'
# AND e.provider = 'openai'
# AND 1 - (e.embedding <=> $1) >= $3
# ORDER BY e.embedding <=> $1
# LIMIT $4;
```

## Usage Examples

### Initialize Service

There are two ways to initialize the PostgresService:

**Option 1: Factory function (recommended for apps using remdb as a library)**

```python
from rem.services.postgres import get_postgres_service

# Uses POSTGRES__CONNECTION_STRING from environment
pg = get_postgres_service()
if pg is None:
    raise RuntimeError("Database not configured - set POSTGRES__CONNECTION_STRING")

await pg.connect()
# ... use pg ...
await pg.disconnect()
```

**Option 2: Direct instantiation**

```python
from rem.services.postgres import PostgresService

service = PostgresService(
    connection_string="postgresql://user:pass@localhost/remdb",
    pool_size=20
)

await service.connect()
```

> **Note**: `get_postgres_service()` returns the service directly. It does NOT support
> `async with` context manager syntax. Always call `connect()` and `disconnect()` explicitly.

### Using Repository Pattern

**Generic Repository** for simple CRUD operations:

```python
from rem.services.postgres import Repository
from rem.models.entities import Message, Resource

# Create repository for any model
message_repo = Repository(Message)
resource_repo = Repository(Resource)

# Create single record
message = Message(
    content="Hello, world!",
    message_type="user",
    session_id="session-123",
    user_id="user123"
)
created = await message_repo.upsert(message)

# Upsert also accepts lists (no need for separate batch method)
messages = [message1, message2, message3]
created_messages = await message_repo.upsert(messages)

# Find records
messages = await message_repo.find({
    "session_id": "session-123",
    "user_id": "user123"
}, order_by="created_at ASC", limit=100)

# Get by ID
message = await message_repo.get_by_id("msg-id", "user123")

# Get by session (convenience method)
session_messages = await message_repo.get_by_session(
    session_id="session-123",
    user_id="user123"
)

# Count
count = await message_repo.count({"session_id": "session-123"})

# Delete (soft delete)
deleted = await message_repo.delete("msg-id", "user123")
```

**When to use Repository vs PostgresService:**
- **Repository**: Simple CRUD, session management, high-level operations
- **PostgresService**: Batch operations with embeddings, custom queries, performance-critical code

### Register Entity Types

```python
from rem.services.postgres.register_type import register_type
from rem.models.entities import Resource

# Register Resource model
schema = await register_type(
    model=Resource,
    table_name="resources",
    entity_key_field="name",
    tenant_scoped=True,
    create_embeddings=True,
    create_kv_trigger=True
)

# Execute generated SQL
await service.execute(schema["sql"]["table"])
await service.execute(schema["sql"]["embeddings"])
await service.execute(schema["sql"]["kv_trigger"])
```

### Batch Upsert with Embeddings

```python
# Create entities
resources = [
    Resource(
        name="api-design-doc",
        description="API design guidelines",
        content="RESTful API best practices..."
    ),
    Resource(
        name="deployment-guide",
        description="Kubernetes deployment guide",
        content="Deploy to EKS with Karpenter..."
    )
]

# Batch upsert
result = await service.batch_upsert(
    table_name="resources",
    entities=resources,
    user_id="user123",
    generate_embeddings=True
)

print(f"Inserted: {result['inserted']}")
print(f"Embeddings: {result['embeddings_generated']}")
```

### Query Operations

```python
# LOOKUP by natural key
entity = await service.lookup_entity(
    entity_key="api-design-doc",
    user_id="user123"
)

# FUZZY search
results = await service.fuzzy_search(
    query="api design",
    user_id="user123",
    threshold=0.3,
    limit=5
)

# SEARCH by semantic similarity
results = await service.vector_search(
    table_name="resources",
    query_text="how to deploy kubernetes",
    field_name="content",
    user_id="user123",
    limit=10
)
```

## Performance Considerations

### Batch Size Optimization

- **Embeddings**: OpenAI supports up to 2048 texts per call
- **Inserts**: Batch 100-500 rows per transaction
- **Connection pool**: Size based on workload (default: 20)

### Index Strategy

- **Foreground indexes**: Critical for queries (tenant_id, user_id)
- **Background indexes**: HNSW for vectors, created CONCURRENTLY
- **GIN indexes**: For JSONB fields (graph_edges, metadata)

### KV_STORE Maintenance

- UNLOGGED table = faster but lost on crash
- Rebuild from primary tables on startup
- Vacuum regularly to reclaim space

### Memory Usage

- Vector indexes can be memory-intensive
- HNSW parameters: `m=16, ef_construction=64` (tunable)
- Monitor shared_buffers and work_mem

## Schema Management

REM uses a **code-as-source-of-truth** approach. Pydantic models define the schema, and the database is kept in sync via diff-based migrations.

### File Structure

```
src/rem/sql/
├── migrations/
│   ├── 001_install.sql          # Core infrastructure (manual)
│   └── 002_install_models.sql   # Entity tables (auto-generated)
└── background_indexes.sql       # HNSW vector indexes (optional)
```

**Key principle**: Only two migration files. No incremental `003_`, `004_` files.

### CLI Commands

```bash
# Apply migrations (installs extensions, core tables, entity tables)
rem db migrate

# Check migration status
rem db status

# Generate schema SQL from models (for remdb development)
rem db schema generate --models src/rem/models/entities

# Validate models for schema generation
rem db schema validate --models src/rem/models/entities
```

### Model Registry

Models are discovered via the registry:

```python
import rem
from rem.models.core import CoreModel

@rem.register_model
class MyEntity(CoreModel):
    name: str
    description: str  # Auto-embeds
```

## Using REM as a Library (Downstream Apps)

When building an application that **depends on remdb as a package** (e.g., `pip install remdb`),
there are important differences from developing remdb itself.

### What Works Out of the Box

1. **All core entity tables** - Resources, Messages, Users, Sessions, etc.
2. **PostgresService** - Full database access via `get_postgres_service()`
3. **Repository pattern** - CRUD operations for core entities
4. **Migrations** - `rem db migrate` applies the bundled SQL files

```python
# In your downstream app (e.g., myapp/main.py)
from rem.services.postgres import get_postgres_service
from rem.models.entities import Message, Resource

pg = get_postgres_service()
await pg.connect()

# Use core entities - tables already exist
messages = await pg.query(Message, {"session_id": "abc"})
```

### Custom Models in Downstream Apps

The `@rem.register_model` decorator registers models in the **runtime registry**, which is useful for:
- Schema introspection at runtime
- Future tooling that reads the registry

However, **`rem db migrate` only applies SQL files bundled in the remdb package**.
Custom models from downstream apps do NOT automatically get tables created.

**Options for custom model tables:**

**Option A: Use core entities with metadata**

Store custom data in the `metadata` JSONB field of existing entities:

```python
resource = Resource(
    name="my-custom-thing",
    content="...",
    metadata={"custom_field": "value", "another": 123}
)
```

**Option B: Create tables manually**

Write and apply your own SQL:

```sql
-- myapp/sql/custom_tables.sql
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_ref TEXT NOT NULL,
    summary TEXT NOT NULL,
    -- ... include CoreModel fields for compatibility
    user_id VARCHAR(256),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

```bash
psql $DATABASE_URL -f myapp/sql/custom_tables.sql
```

**Option C: Contribute upstream**

If your model is generally useful, contribute it to remdb so it's included in
the next release and `rem db migrate` creates it automatically.

### Example: Downstream App Structure

```
myapp/
├── main.py              # Import models, start API
├── models/
│   └── __init__.py      # @rem.register_model decorators
├── sql/
│   └── custom.sql       # Manual migrations for custom tables
├── .env                 # POSTGRES__CONNECTION_STRING, LLM keys
└── pyproject.toml       # dependencies = ["remdb>=0.3.110"]
```

```python
# myapp/models/__init__.py
import rem
from rem.models.core import CoreModel

@rem.register_model
class ConversationSummary(CoreModel):
    """Registered for introspection, but table created via sql/custom.sql"""
    session_ref: str
    summary: str
```

```python
# myapp/main.py
import models  # Registers custom models

from rem.api.main import app  # Use REM's FastAPI app
# Or build your own app using rem.services
```

## Adding Models & Migrations

Quick workflow for adding new database models:

1. **Create a model** in `models/__init__.py` (or a submodule):
   ```python
   import rem
   from rem.models.core import CoreModel

   @rem.register_model
   class MyEntity(CoreModel):
       name: str
       description: str  # Auto-embedded (common field name)
   ```

2. **Check for schema drift** - REM auto-detects `./models` directory:
   ```bash
   rem db diff              # Show pending changes (additive only)
   rem db diff --strategy full  # Include destructive changes
   ```

3. **Generate migration** (optional - for version-controlled SQL):
   ```bash
   rem db diff --generate   # Creates numbered .sql file
   ```

4. **Apply changes**:
   ```bash
   rem db migrate           # Apply all pending migrations
   ```

**Key points:**
- Models in `./models/` are auto-discovered (must have `__init__.py`)
- Or set `MODELS__IMPORT_MODULES=myapp.models` for custom paths
- `CoreModel` provides: `id`, `tenant_id`, `user_id`, `created_at`, `updated_at`, `deleted_at`, `graph_edges`, `metadata`, `tags`
- Fields named `content`, `description`, `summary`, `text`, `body`, `message`, `notes` get embeddings by default
- Use `Field(json_schema_extra={"embed": True})` to embed other fields

## Configuration

Environment variables:

```bash
# Database
POSTGRES__HOST=localhost
POSTGRES__PORT=5432
POSTGRES__DATABASE=remdb
POSTGRES__USER=rem_user
POSTGRES__PASSWORD=secret
POSTGRES__POOL_SIZE=20

# Embeddings
EMBEDDING__PROVIDER=openai
EMBEDDING__MODEL=text-embedding-3-small
EMBEDDING__DIMENSIONS=1536
EMBEDDING__BATCH_SIZE=2048

# Background indexing
BACKGROUND_INDEX__ENABLED=true
BACKGROUND_INDEX__CONCURRENCY=2
```

## See Also

- [register_type.py](./register_type.py) - Dynamic schema generation
- [schema_generator.py](./schema_generator.py) - Bulk schema generation
- [REM Query System](../../models/core/rem_query.py) - Query types and contracts
