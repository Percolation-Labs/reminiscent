# REM Utilities

## Table of Contents

1. [SQL Types](#sql-types-sql_typespy) - Pydantic to PostgreSQL type mapping
2. [Embeddings](#embeddings-embeddingspy) - Vector embeddings generation
3. [Files](#files-filespy) - File utilities and DataFrame I/O

## SQL Types (`sql_types.py`)

Intelligent Pydantic to PostgreSQL type mapping utility for generating database schemas and UPSERT statements.

### Features

- **Smart String Handling**: VARCHAR(256) by default, TEXT for content/description fields
- **Union Type Preferences**: Prioritizes UUID and JSONB in Union types
- **Array Support**: PostgreSQL arrays for `list[str]`, JSONB for complex lists
- **JSONB for Structured Data**: Automatic JSONB for dicts and nested structures
- **Custom Type Overrides**: Support for `sql_type` in `json_schema_extra`
- **Embedding Field Detection**: Auto-detects embedding fields via `embedding_provider`
- **Schema Generation**: CREATE TABLE with appropriate indexes
- **UPSERT Templates**: INSERT ... ON CONFLICT UPDATE statements

### Type Mapping Rules

| Pydantic Type | PostgreSQL Type | Notes |
|---------------|-----------------|-------|
| `str` | `VARCHAR(256)` | Default for strings |
| `str` (field name: content, description, summary, etc.) | `TEXT` | Long-form text fields |
| `str` (with `embedding_provider`) | `TEXT` | For vector search preprocessing |
| `int` | `INTEGER` | Standard integer |
| `float` | `DOUBLE PRECISION` | Floating point |
| `bool` | `BOOLEAN` | Boolean values |
| `UUID` | `UUID` | PostgreSQL UUID type |
| `datetime` | `TIMESTAMP` | Timestamp without timezone |
| `date` | `DATE` | Date only |
| `dict` | `JSONB` | Structured JSON data |
| `list[str]` | `TEXT[]` | PostgreSQL array |
| `list[dict]` | `JSONB` | Complex nested data |
| `UUID \| str` | `UUID` | Prefers UUID in unions |
| `dict \| None` | `JSONB` | Prefers JSONB in unions |

### Long-Form Text Field Names

Fields with these names automatically use TEXT:
- `content`, `description`, `summary`
- `instructions`, `prompt`, `message`
- `body`, `text`, `note`, `comment`
- Fields ending with `_content`, `_description`, `_summary`, `_text`, `_message`

### Usage Examples

#### Basic Type Mapping

```python
from pydantic import Field
from rem.utils.sql_types import get_sql_type

# String field
field = Field(default="")
get_sql_type(field, "name")  # "VARCHAR(256)"

# Content field (detected by name)
field = Field(default="")
get_sql_type(field, "content")  # "TEXT"

# Dict field
field = Field(default_factory=dict)
get_sql_type(field, "metadata")  # "JSONB"

# List of strings
field = Field(default_factory=list)
get_sql_type(field, "tags")  # "TEXT[]"
```

#### Custom Type Override

```python
from pydantic import BaseModel, Field

class Document(BaseModel):
    # Custom pgvector type
    embedding: list[float] = Field(
        default_factory=list,
        json_schema_extra={"sql_type": "vector(1536)"}
    )

    # Embedding provider detection (format: provider:model_name)
    content: str = Field(
        default="",
        json_schema_extra={"embedding_provider": "openai:text-embedding-3-small"}
    )  # Will use TEXT

    # Alternative embedding providers
    description: str = Field(
        default="",
        json_schema_extra={"embedding_provider": "anthropic:voyage-2"}
    )  # Will use TEXT
```

#### Generate CREATE TABLE

```python
from rem.models.entities import Resource
from rem.utils.sql_types import model_to_create_table

sql = model_to_create_table(Resource, "resources")
print(sql)
```

Output:
```sql
CREATE TABLE IF NOT EXISTS resources (
    id UUID PRIMARY KEY,
    name VARCHAR(256) NOT NULL,
    uri VARCHAR(256),
    content TEXT NOT NULL DEFAULT '',
    description TEXT,
    category VARCHAR(256),
    related_entities JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_resources_tenant_id ON resources(tenant_id);
CREATE INDEX IF NOT EXISTS idx_resources_related_entities ON resources USING GIN(related_entities);
```

#### Generate UPSERT Statement

```python
from rem.models.entities import Resource
from rem.utils.sql_types import model_to_upsert

sql = model_to_upsert(Resource, "resources")
print(sql)
```

Output:
```sql
INSERT INTO resources (id, name, uri, content, description, category, related_entities)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (id)
DO UPDATE SET name = EXCLUDED.name, uri = EXCLUDED.uri, content = EXCLUDED.content,
              description = EXCLUDED.description, category = EXCLUDED.category,
              related_entities = EXCLUDED.related_entities;
```

#### Complete Column Definition

```python
from pydantic import Field
from rem.utils.sql_types import get_column_definition

# Primary key
field = Field(..., description="User ID")
get_column_definition(field, "id", nullable=False, primary_key=True)
# "id UUID PRIMARY KEY"

# Optional field
field = Field(default=None)
get_column_definition(field, "email", nullable=True)
# "email VARCHAR(256)"

# JSONB with default
field = Field(default_factory=dict)
get_column_definition(field, "metadata", nullable=False)
# "metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
```

### Index Generation

The utility automatically creates indexes for:

1. **Foreign Keys**: Fields ending with `_id` (e.g., `user_id`, `tenant_id`)
2. **JSONB Fields**: GIN indexes for efficient querying
3. **Array Fields**: GIN indexes for array containment queries
4. **Primary Keys**: Automatically indexed

### Integration with REM Models

```python
# Generate schema for all REM entities
from rem.models.entities import Resource, Message, User, File, Moment, Schema
from rem.utils.sql_types import model_to_create_table

for model, table_name in [
    (Resource, "resources"),
    (Message, "messages"),
    (User, "users"),
    (File, "files"),
    (Moment, "moments"),
    (Schema, "schemas"),
]:
    sql = model_to_create_table(model, table_name)
    with open(f"migrations/{table_name}.sql", "w") as f:
        f.write(sql)
```

### Best Practices (from Research)

Based on PostgreSQL documentation and community best practices:

1. **VARCHAR(256) for Most Strings**: Good balance between validation and flexibility
2. **TEXT for Long Content**: No performance penalty, better for variable-length text
3. **JSONB over JSON**: Better querying capabilities, GIN indexing support
4. **Arrays for Simple Lists**: More efficient than JSONB for simple string/int lists
5. **Consistent Typing**: Use one approach throughout your schema for maintainability
6. **Index Size Limits**: PostgreSQL has a 2712-byte limit per index row; TEXT fields should have constraints if indexed

### Running the Example

```bash
cd src/rem/utils/examples
python sql_types_example.py
```

This will demonstrate:
- Field type mapping
- Column definitions
- CREATE TABLE generation
- UPSERT statement generation

### See Also

- `examples/sql_types_example.py` - Complete working examples
- `../../models/entities/` - REM entity models
- `../../models/core/core_model.py` - CoreModel base class

---

## Embeddings (`embeddings.py`)

Vector embeddings generation utility using HTTP requests (no provider SDKs required). Supports batch processing for efficient API usage and automatic retry with exponential backoff using `tenacity`.

### Features

- **No SDK Dependencies**: Uses `requests` library for HTTP calls
- **Batch Processing**: Generate embeddings for multiple texts in a single API call
- **Multiple Providers**: OpenAI (text-embedding-3-small, text-embedding-3-large, ada-002), Voyage AI (voyage-2)
- **Automatic Retries**: Uses `tenacity` library for exponential backoff on rate limits
- **Provider Format**: Uses `provider:model_name` format (e.g., `openai:text-embedding-3-small`)
- **Environment Variables**: API keys from `LLM__OPENAI_API_KEY` or `OPENAI_API_KEY`
- **Error Handling**: Custom exceptions for embedding errors and rate limits

### Supported Models

| Provider | Model | Dimensions | Cost (per 1M tokens) |
|----------|-------|------------|---------------------|
| OpenAI | text-embedding-3-small | 1536 | $0.02 |
| OpenAI | text-embedding-3-large | 3072 | $0.13 |
| OpenAI | text-embedding-ada-002 | 1536 | $0.10 |
| Voyage AI | voyage-2 | 1024 | Varies |
| Voyage AI | voyage-large-2 | 1536 | Varies |

### Usage Examples

#### Single Text Embedding

```python
from rem.utils.embeddings import generate_embeddings

# Generate embedding for single text
embedding = generate_embeddings(
    "openai:text-embedding-3-small",
    "What is the meaning of life?"
)

# Result: list[float] with 1536 dimensions
print(f"Embedding dimension: {len(embedding)}")  # 1536
print(f"First 5 values: {embedding[:5]}")
```

#### Batch Processing (Recommended)

```python
from rem.utils.embeddings import generate_embeddings

# Generate embeddings for multiple texts (more efficient)
texts = [
    "What is machine learning?",
    "How does neural network work?",
    "Explain deep learning",
]

embeddings = generate_embeddings(
    "openai:text-embedding-3-small",
    texts
)

# Result: list[list[float]] - one embedding per text
print(f"Generated {len(embeddings)} embeddings")
for i, embedding in enumerate(embeddings):
    print(f"Text {i+1}: {len(embedding)} dimensions")
```

#### Get Embedding Dimension

```python
from rem.utils.embeddings import get_embedding_dimension

# Get dimension for a model (useful for creating vector columns)
dimension = get_embedding_dimension("openai:text-embedding-3-small")
print(f"Dimension: {dimension}")  # 1536

# Create PostgreSQL vector column with correct dimension
# CREATE TABLE documents (
#     id UUID PRIMARY KEY,
#     content TEXT,
#     embedding vector(1536)  -- Use dimension from get_embedding_dimension
# );
```

#### Error Handling

```python
from rem.utils.embeddings import (
    generate_embeddings,
    EmbeddingError,
    RateLimitError,
)

try:
    embeddings = generate_embeddings(
        "openai:text-embedding-3-small",
        texts,
        max_retries=2,  # Optional: increase retries if needed
    )
except RateLimitError as e:
    print(f"Rate limit exceeded after retries: {e}")
    # All retries exhausted, implement queue or wait longer
except EmbeddingError as e:
    print(f"Embedding generation failed: {e}")
```

#### Custom API Key

```python
from rem.utils.embeddings import generate_embeddings

# Provide API key explicitly (instead of environment variable)
embedding = generate_embeddings(
    "openai:text-embedding-3-small",
    "Hello world",
    api_key="sk-..."
)
```

### PostgreSQL Integration

#### Add Embedding Column

```python
from rem.utils.embeddings import get_embedding_dimension

# Get dimension for the model you'll use
dimension = get_embedding_dimension("openai:text-embedding-3-small")

# Create vector column (requires pgvector extension)
await postgres.execute(f"""
    ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS embedding vector({dimension})
""")
```

#### Generate and Store Embeddings

```python
from rem.utils.embeddings import generate_embeddings

# Single record
async def add_document_with_embedding(content: str):
    # Generate embedding
    embedding = generate_embeddings(
        "openai:text-embedding-3-small",
        content
    )

    # Store in database
    await postgres.execute(
        """
        INSERT INTO documents (id, content, embedding)
        VALUES ($1, $2, $3::vector)
        """,
        doc_id,
        content,
        embedding,
    )

# Batch processing (efficient)
async def batch_generate_embeddings(batch_size: int = 100):
    # Get records without embeddings
    records = await postgres.fetch_all("""
        SELECT id, content
        FROM documents
        WHERE embedding IS NULL
        LIMIT $1
    """, batch_size)

    # Extract texts
    texts = [r["content"] for r in records]

    # Generate all embeddings in one API call
    embeddings = generate_embeddings(
        "openai:text-embedding-3-small",
        texts
    )

    # Store embeddings
    for record, embedding in zip(records, embeddings):
        await postgres.execute(
            """
            UPDATE documents
            SET embedding = $1::vector
            WHERE id = $2
            """,
            embedding,
            record["id"],
        )
```

#### Similarity Search

```python
# Vector similarity search using pgvector
async def search_similar_documents(query: str, limit: int = 10):
    # Generate query embedding
    query_embedding = generate_embeddings(
        "openai:text-embedding-3-small",
        query
    )

    # Search using cosine similarity (pgvector <=> operator)
    results = await postgres.fetch_all(
        """
        SELECT id, content,
               embedding <=> $1::vector as distance
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        query_embedding,
        limit,
    )

    return results
```

#### Create Vector Index

```python
# Create ivfflat index for faster similarity search
# Note: Requires at least 1000 rows for effective indexing
await postgres.execute("""
    CREATE INDEX IF NOT EXISTS idx_documents_embedding
    ON documents
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
""")
```

### Best Practices

1. **Batch Processing**
   - Always batch multiple texts in a single API call when possible
   - OpenAI supports up to 2048 inputs per request
   - Reduces API overhead and stays within RPM (requests per minute) limits

2. **Rate Limit Management**
   - Uses `tenacity` library for automatic exponential backoff (default: 1 retry with 1s wait)
   - Adjust `max_retries` parameter if needed (default: 1)
   - Monitor your usage and adjust batch size accordingly
   - For large-scale processing, implement a queue system

3. **Cost Optimization**
   - Use `text-embedding-3-small` ($0.02/1M tokens) for most use cases
   - Only use `text-embedding-3-large` ($0.13/1M tokens) when higher accuracy is critical
   - Batch requests to minimize API calls

4. **Error Handling**
   - Catch `RateLimitError` separately for specific rate limit handling
   - Catch `EmbeddingError` for general API errors
   - Validate `embedding_provider` format early in your code

5. **PostgreSQL Performance**
   - Create vector indexes after populating data (requires 1000+ rows)
   - Use `ivfflat` indexes for approximate nearest neighbor search
   - Consider HNSW indexes for better accuracy (pgvector 0.5.0+)
   - Use `vector_cosine_ops` for cosine similarity (most common)

6. **Environment Variables**
   - Set `LLM__OPENAI_API_KEY` in `.env` for consistency with REM settings
   - Falls back to `OPENAI_API_KEY` for compatibility
   - Never commit API keys to version control

### API Reference

#### `generate_embeddings()`

```python
def generate_embeddings(
    embedding_provider: str,
    texts: str | list[str],
    api_key: str | None = None,
    max_retries: int = 1,
) -> list[float] | list[list[float]]:
    """
    Generate embeddings for text(s) using specified provider.

    Uses tenacity for automatic retry with exponential backoff on rate limits.

    Args:
        embedding_provider: Provider and model (e.g., "openai:text-embedding-3-small")
        texts: Single text or list of texts
        api_key: API key (if None, reads from environment)
        max_retries: Maximum retry attempts for rate limits (default: 1)

    Returns:
        Single embedding (list[float]) or list of embeddings (list[list[float]])

    Raises:
        EmbeddingError: If generation fails
        RateLimitError: If rate limit exceeded after retries
        ValueError: If provider format is invalid
    """
```

#### `get_embedding_dimension()`

```python
def get_embedding_dimension(embedding_provider: str) -> int:
    """
    Get embedding dimension for a provider and model.

    Args:
        embedding_provider: Provider and model (e.g., "openai:text-embedding-3-small")

    Returns:
        Embedding dimension (e.g., 1536)

    Raises:
        ValueError: If provider/model is unknown
    """
```

### Environment Variables

Set in `.env` or environment:

```bash
# OpenAI (preferred format for REM)
LLM__OPENAI_API_KEY=sk-...

# Or standard OpenAI format (fallback)
OPENAI_API_KEY=sk-...

# Anthropic/Voyage AI
LLM__ANTHROPIC_API_KEY=sk-ant-...
```

### Running the Example

```bash
# Set API key
export LLM__OPENAI_API_KEY='sk-...'

# Run examples
cd src/rem/utils/examples
python embeddings_example.py
```

This will demonstrate:
- Single text embedding
- Batch processing
- Multiple providers
- Error handling
- PostgreSQL integration patterns

### See Also

- `examples/embeddings_example.py` - Complete working examples
- `sql_types.py` - Use `embedding_provider` in json_schema_extra for TEXT fields
- OpenAI Embeddings API: https://platform.openai.com/docs/api-reference/embeddings
- pgvector Documentation: https://github.com/pgvector/pgvector

---

## Files (`files.py`)

File utilities including temporary file handling and DataFrame I/O with automatic format detection.

### DataFrame I/O

Read and write DataFrames with format auto-detected from file extension:

```python
from rem.utils.files import read_dataframe, write_dataframe

# Read - format inferred from extension
df = read_dataframe("data.csv")
df = read_dataframe("data.parquet")
df = read_dataframe("data.xlsx")

# Read from bytes (e.g., from S3)
df = read_dataframe(content_bytes, filename="data.csv")

# Write - format inferred from extension
write_dataframe(df, "output.parquet")
```

**Supported formats**: `.csv`, `.tsv`, `.parquet`, `.json`, `.jsonl`, `.avro`, `.xlsx`, `.xls`, `.ods`, `.ipc`, `.arrow`, `.feather`

Note: Some formats require optional dependencies (e.g., `fastexcel` for Excel).

### Temporary File Utilities

```python
from rem.utils.files import temp_file_from_bytes, temp_directory

# Create temp file from bytes, auto-cleanup
with temp_file_from_bytes(pdf_bytes, suffix=".pdf") as tmp_path:
    result = process_pdf(tmp_path)

# Create temp directory, auto-cleanup
with temp_directory() as tmp_dir:
    # Work with files in tmp_dir
    pass
```
