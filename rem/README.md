# REM - Resources Entities Moments

Cloud-native unified memory infrastructure for agentic AI systems built with Pydantic AI, FastAPI, and FastMCP.

## Architecture Overview

<p align="center">
  <img src="https://mermaid.ink/img/Z3JhcGggVEQKICAgIEFQSVtGYXN0QVBJPGJyLz5DaGF0ICsgTUNQXSAtLT4gQUdFTlRTW0pTT04gU2NoZW1hPGJyLz5BZ2VudHNdCiAgICBBR0VOVFMgLS0-IFRPT0xTW01DUCBUb29sczxici8-NSBUb29sc10KCiAgICBUT09MUyAtLT4gUVVFUllbUkVNIFF1ZXJ5PGJyLz5EaWFsZWN0XQogICAgUVVFUlkgLS0-IERCWyhQb3N0Z3JlU1FMPGJyLz4rcGd2ZWN0b3IpXQoKICAgIEZJTEVTW0ZpbGUgUHJvY2Vzc29yXSAtLT4gRFJFQU1bRHJlYW1pbmc8YnIvPldvcmtlcnNdCiAgICBEUkVBTSAtLT4gREIKCiAgICBBR0VOVFMgLS0-IE9URUxbT3BlblRlbGVtZXRyeV0KICAgIE9URUwgLS0-IFBIT0VOSVhbQXJpemU8YnIvPlBob2VuaXhdCgogICAgRVZBTFtFdmFsdWF0aW9uPGJyLz5GcmFtZXdvcmtdIC0tPiBQSE9FTklYCgogICAgY2xhc3NEZWYgYXBpIGZpbGw6IzRBOTBFMixzdHJva2U6IzJFNUM4QSxjb2xvcjojZmZmCiAgICBjbGFzc0RlZiBhZ2VudCBmaWxsOiM3QjY4RUUsc3Ryb2tlOiM0ODNEOEIsY29sb3I6I2ZmZgogICAgY2xhc3NEZWYgZGIgZmlsbDojNTBDODc4LHN0cm9rZTojMkU3RDRFLGNvbG9yOiNmZmYKICAgIGNsYXNzRGVmIG9icyBmaWxsOiM5QjU5QjYsc3Ryb2tlOiM2QzM0ODMsY29sb3I6I2ZmZgoKICAgIGNsYXNzIEFQSSxUT09MUyBhcGkKICAgIGNsYXNzIEFHRU5UUyBhZ2VudAogICAgY2xhc3MgREIsUVVFUlkgZGIKICAgIGNsYXNzIE9URUwsUEhPRU5JWCxFVkFMIG9icwo=" alt="REM Architecture" width="700">
</p>

**Key Components:**

- **API Layer**: OpenAI-compatible chat completions + MCP server (not separate deployments)
- **Agentic Framework**: JSON Schema-based agents with no-code configuration
- **Database Layer**: PostgreSQL 18 with pgvector for multi-index memory (KV + Vector + Graph)
- **REM Query Dialect**: Custom query language with O(1) lookups, semantic search, graph traversal
- **Ingestion & Dreaming**: Background workers for content extraction and progressive index enrichment (0% → 100% answerable)
- **Observability & Evals**: OpenTelemetry tracing + Arize Phoenix + LLM-as-a-Judge evaluation framework

## Features

| Feature | Description | Benefits |
|---------|-------------|----------|
| **OpenAI-Compatible Chat API** | Drop-in replacement for OpenAI chat completions API with streaming support | Use with existing OpenAI clients, switch models across providers (OpenAI, Anthropic, etc.) |
| **Built-in MCP Server** | FastMCP server with 5 tools + 3 resources for memory operations | Export memory to Claude Desktop, Cursor, or any MCP-compatible host |
| **REM Query Engine** | Multi-index query system (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE) with custom dialect | O(1) lookups, semantic search, graph traversal - all tenant-isolated |
| **Dreaming Workers** | Background workers for entity extraction, moment generation, and affinity matching | Automatic knowledge graph construction from resources (0% → 100% query answerable) |
| **PostgreSQL + pgvector** | CloudNativePG with PostgreSQL 18, pgvector extension, streaming replication | Production-ready vector search, no external vector DB needed |
| **AWS EKS Recipe** | Complete infrastructure-as-code with Pulumi, Karpenter, ArgoCD | Deploy to production EKS in minutes with auto-scaling and GitOps |
| **JSON Schema Agents** | Dynamic agent creation from YAML schemas via Pydantic AI factory | Define agents declaratively, version control schemas, load dynamically |
| **Content Providers** | Audio transcription (Whisper), vision (GPT-4V, Claude), PDFs, DOCX, images | Multimodal ingestion out of the box with format detection |
| **Configurable Embeddings** | Provider-agnostic embedding system (OpenAI, Cohere, Jina) | Switch embedding providers via env vars, no code changes |
| **Multi-Tenancy** | Tenant isolation at database level with automatic scoping | SaaS-ready with complete data separation per tenant |
| **Streaming Everything** | SSE for chat, background workers for embeddings, async throughout | Real-time responses, non-blocking operations, scalable |
| **Zero Vendor Lock-in** | Raw HTTP clients (no OpenAI SDK), swappable providers, open standards | Not tied to any vendor, easy to migrate, full control |

## Quick Start

Choose your path:

- **Option 1: Package Users** (Recommended for non-developers) - PyPI package + dockerized database
- **Option 2: Developers** - Clone repo, local development with uv

---

## Option 1: Package Users (Recommended)

**Best for**: Using REM as a service (API + CLI) without modifying code.

### Step 1: Start Database and API with Docker Compose

```bash
# Create a project directory
mkdir my-rem-project && cd my-rem-project

# Download docker-compose file from public gist
curl -O https://gist.githubusercontent.com/percolating-sirsh/d117b673bc0edfdef1a5068ccd3cf3e5/raw/docker-compose.prebuilt.yml

# IMPORTANT: Export API keys BEFORE running docker compose
# Docker Compose reads env vars at startup - exporting them after won't work!

# Required: OpenAI for embeddings (text-embedding-3-small)
export OPENAI_API_KEY="sk-..."

# Recommended: At least one chat completion provider
export ANTHROPIC_API_KEY="sk-ant-..."           # Claude Sonnet 4.5 (high quality)
export CEREBRAS_API_KEY="csk-..."               # Cerebras (fast, cheap inference)

# Start PostgreSQL + API
docker compose -f docker-compose.prebuilt.yml up -d

# Verify services are running
curl http://localhost:8000/health
```

This starts:
- **PostgreSQL** with pgvector on port **5051** (connection: `postgresql://rem:rem@localhost:5051/rem`)
- **REM API** on port **8000** with OpenAI-compatible chat completions + MCP server
- Uses pre-built Docker image from Docker Hub (no local build required)

### Step 2: Install and Configure CLI (REQUIRED)

**This step is required** before you can use REM - it installs the database schema and configures your LLM API keys.

```bash
# Install remdb package from PyPI
pip install remdb[all]

# Configure REM (defaults to port 5051 for package users)
rem configure --install --claude-desktop
```

The interactive wizard will:
1. **Configure PostgreSQL**: Defaults to `postgresql://rem:rem@localhost:5051/rem` (prebuilt docker-compose)
   - Just press Enter to accept defaults
   - Custom database: Enter your own host/port/credentials
2. **Configure LLM providers**: Enter your OpenAI/Anthropic API keys
3. **Install database tables**: Creates schema, functions, indexes (**required for CLI/API to work**)
4. **Register with Claude Desktop**: Adds REM MCP server to Claude

Configuration saved to `~/.rem/config.yaml` (can edit with `rem configure --edit`)

**Port Guide:**
- **5051**: Package users with `docker-compose.prebuilt.yml` (pre-built image)
- **5050**: Developers with `docker-compose.yml` (local build)
- **Custom**: Your own PostgreSQL database

**Next Steps:**
- See [CLI Reference](#cli-reference) for all available commands
- See [REM Query Dialect](#rem-query-dialect) for query examples
- See [API Endpoints](#api-endpoints) for OpenAI-compatible API usage

### Step 3: Test the Stack

```bash
# Ingest a test file to populate your knowledge base
echo "REM is a bio-inspired memory system for agentic AI workloads." > test-doc.txt
rem process ingest test-doc.txt --user-id test-user --category documentation --tags rem,ai

# Query your ingested data
rem ask "What do you know about REM from my knowledge base?" --user-id test-user

# Test with a general query (uses agent's built-in knowledge + your data)
rem ask "What is REM?" --user-id test-user

# Test the API
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: test-user" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "What is REM?"}],
    "stream": false
  }'
```

**File Ingestion Commands:**
- `rem process ingest <file>` - Full ingestion pipeline (storage + parsing + embedding + database)
- `rem process uri <file>` - READ-ONLY parsing (no database storage, useful for testing parsers)


## See Also

- [REM Query Dialect](#rem-query-dialect) - LOOKUP, SEARCH, TRAVERSE, SQL query types
- [API Endpoints](#api-endpoints) - OpenAI-compatible chat completions, MCP server
- [CLI Reference](#cli-reference) - Complete command-line interface documentation
- [Bring Your Own Agent](#bring-your-own-agent) - Create custom agents with your own prompts and tools
- [Production Deployment](#production-deployment) - AWS EKS with Kubernetes

**Sample Data**: Test data with users, resources, and moments is at `tests/data/seed/test-user-data.yaml`

---

## Bring Your Own Agent

REM allows you to create **custom agents** with your own system prompts, tools, and output schemas. Custom agents are stored in the database and dynamically loaded when referenced, enabling **no-code agent creation** without modifying the codebase.

### How It Works

1. **Define Agent Schema** - Create a YAML file with your agent's prompt, tools, and output structure
2. **Ingest Schema** - Use `rem process ingest` to store the schema in the database
3. **Use Your Agent** - Reference your agent by name with `rem ask <agent-name> "query"`

When you run `rem ask my-agent "query"`, REM:
1. Checks if `my-agent` exists in the filesystem (`schemas/agents/`)
2. If not found, performs a **LOOKUP** query on the `schemas` table in the database
3. Loads the schema dynamically and creates a Pydantic AI agent
4. Runs your query with the custom agent

### Expected Behavior

**Schema Ingestion Flow** (`rem process ingest my-agent.yaml`):
- Parse YAML file to extract JSON Schema content
- Extract `json_schema_extra.kind` field → maps to `category` column
- Extract `json_schema_extra.provider_configs` → stores provider configurations
- Extract `json_schema_extra.embedding_fields` → stores semantic search fields
- Create `Schema` entity in `schemas` table with `user_id` scoping
- Schema is now queryable via `LOOKUP "my-agent" FROM schemas`

**Agent Loading Flow** (`rem ask my-agent "query"`):
1. `load_agent_schema("my-agent")` checks filesystem cache → miss
2. Falls back to database: `LOOKUP "my-agent" FROM schemas WHERE user_id = '<user-id>'`
3. Returns `Schema.spec` (JSON Schema dict) from database
4. `create_agent()` factory creates Pydantic AI agent from schema
5. Agent runs with tools specified in `json_schema_extra.tools`
6. Returns structured output defined in `properties` field

### Quick Example

**Step 1: Create Agent Schema** (`my-research-assistant.yaml`)

```yaml
type: object
description: |
  You are a research assistant that helps users find and analyze documents.

  Use the search_rem tool to find relevant documents, then analyze and summarize them.
  Be concise and cite specific documents in your responses.

properties:
  summary:
    type: string
    description: A concise summary of findings
  sources:
    type: array
    items:
      type: string
    description: List of document labels referenced

required:
  - summary
  - sources

json_schema_extra:
  kind: agent
  name: research-assistant
  version: 1.0.0
  tools:
    - search_rem
    - lookup_rem
  resources: []
```

**For more examples**, see:
- Simple agent (no tools): `src/rem/schemas/agents/examples/simple.yaml`
- Agent with REM tools: `src/rem/schemas/agents/core/rem-query-agent.yaml`
- Ontology extractor: `src/rem/schemas/agents/examples/cv-parser.yaml`

**Step 2: Ingest Schema into Database**

```bash
# Ingest the schema (stores in database schemas table)
rem process ingest my-research-assistant.yaml \
  --user-id my-user \
  --category agents \
  --tags custom,research

# Verify schema is in database (should show schema details)
rem ask "LOOKUP 'my-research-assistant' FROM schemas" --user-id my-user
```

**Step 3: Use Your Custom Agent**

```bash
# Run a query with your custom agent
rem ask research-assistant "Find documents about machine learning architecture" \
  --user-id my-user

# With streaming
rem ask research-assistant "Summarize recent API design documents" \
  --user-id my-user \
  --stream

# With session continuity
rem ask research-assistant "What did we discuss about ML?" \
  --user-id my-user \
  --session-id abc-123
```

### Agent Schema Structure

Every agent schema must include:

**Required Fields:**
- `type: object` - JSON Schema type (always "object")
- `description` - System prompt with instructions for the agent
- `properties` - Output schema defining structured response fields

**Optional Metadata** (`json_schema_extra`):
- `kind` - Agent category ("agent", "evaluator", etc.) → maps to `Schema.category`
- `name` - Agent identifier (used for LOOKUP)
- `version` - Semantic version (e.g., "1.0.0")
- `tools` - List of MCP tools to load (e.g., `["search_rem", "lookup_rem"]`)
- `resources` - List of MCP resources to expose (e.g., `["user_profile"]`)
- `provider_configs` - Multi-provider testing configurations (for ontology extractors)
- `embedding_fields` - Fields to embed for semantic search (for ontology extractors)

### Available MCP Tools

REM provides **5 built-in MCP tools** your agents can use:

| Tool | Purpose | Example |
|------|---------|---------|
| `search_rem` | Semantic vector search | `SEARCH "ML architecture" FROM resources LIMIT 10` |
| `lookup_rem` | O(1) exact lookup by label | `LOOKUP "sarah-chen" FROM resources` |
| `traverse_rem` | Graph traversal | `TRAVERSE FROM "project-x" TYPE "references" DEPTH 2` |
| `query_rem` | Execute REM queries (LOOKUP, SEARCH, TRAVERSE, SQL) | Any REM query |
| `ask_rem` | Iterated retrieval with query evolution | Natural language questions |

**Tool Reference**: Tools are defined in `src/rem/api/mcp_router/tools.py`

### Multi-User Isolation

Custom agents are **scoped by `user_id`**, ensuring complete data isolation:

```bash
# User A creates a custom agent
rem process ingest my-agent.yaml --user-id user-a --category agents

# User B cannot see User A's agent
rem ask my-agent "test" --user-id user-b
# ❌ Error: Schema not found (LOOKUP returns no results for user-b)

# User A can use their agent
rem ask my-agent "test" --user-id user-a
# ✅ Works - LOOKUP finds schema for user-a
```

### Advanced: Ontology Extractors

Custom agents can also be used as **ontology extractors** to extract structured knowledge from files. See [CLAUDE.md](../CLAUDE.md#ontology-extraction-pattern) for details on:
- Multi-provider testing (`provider_configs`)
- Semantic search configuration (`embedding_fields`)
- File matching rules (`OntologyConfig`)
- Dreaming workflow integration

### Troubleshooting

**Schema not found error:**
```bash
# Check if schema was ingested correctly
rem ask "SEARCH 'my-agent' FROM schemas" --user-id my-user

# List all schemas for your user
rem ask "SELECT name, category, created_at FROM schemas ORDER BY created_at DESC LIMIT 10" --user-id my-user
```

**Agent not loading tools:**
- Verify `json_schema_extra.tools` lists correct tool names
- Check MCP tool names in `src/rem/api/mcp_router/tools.py`
- Tools are case-sensitive: use `search_rem`, not `Search_REM`

**Agent not returning structured output:**
- Ensure `properties` field defines all expected output fields
- Use `required` field to mark mandatory fields
- Check agent response with `--stream` disabled to see full JSON output

---

## REM Query Dialect

REM provides a custom query language designed for **LLM-driven iterated retrieval** with performance guarantees.

### Design Philosophy

Unlike traditional single-shot SQL queries, the REM dialect is optimized for **multi-turn exploration** where LLMs participate in query planning:

- **Iterated Queries**: Queries return partial results that LLMs use to refine subsequent queries
- **Composable WITH Syntax**: Chain operations together (e.g., `TRAVERSE FROM ... WITH LOOKUP "..."`)
- **Mixed Indexes**: Combines exact lookups (O(1)), semantic search (vector), and graph traversal
- **Query Planner Participation**: Results include metadata for LLMs to decide next steps

**Example Multi-Turn Flow**:
```
Turn 1: LOOKUP "sarah-chen" → Returns entity + available edge types
Turn 2: TRAVERSE FROM "sarah-chen" TYPE "authored_by" DEPTH 1 → Returns connected documents
Turn 3: SEARCH "architecture decisions" WITH TRAVERSE FROM "sarah-chen" → Combines semantic + graph
```

This enables LLMs to **progressively build context** rather than requiring perfect queries upfront.

See [REM Query Dialect (AST)](#rem-query-dialect-ast) for complete grammar specification.

### Query Types

#### `LOOKUP` - O(1) Exact Label Lookup

Fast exact match on entity labels (natural language identifiers, not UUIDs).

```sql
LOOKUP "sarah-chen" FROM resources
LOOKUP "api-design-v2" FROM resources WHERE category = "projects"
```

**Performance**: O(1) - indexed on `label` column
**Returns**: Single entity or null
**Use case**: Fetch specific known entities by human-readable name

#### `FUZZY` - Fuzzy Text Search

Fuzzy matching for partial names or misspellings using PostgreSQL trigram similarity.

```sql
FUZZY "sara" FROM resources LIMIT 10
FUZZY "api desgin" FROM resources THRESHOLD 0.3 LIMIT 5
```

**Performance**: O(n) with pg_trgm GIN index (fast for small-medium datasets)
**Returns**: Ranked list by similarity score
**Use case**: Handle typos, partial names, or when exact label is unknown

#### `SEARCH` - Semantic Vector Search

Semantic search using pgvector embeddings with cosine similarity.

```sql
SEARCH "machine learning architecture" FROM resources LIMIT 10
SEARCH "contract disputes" FROM resources WHERE tags @> ARRAY['legal'] LIMIT 5
```

**Performance**: O(log n) with HNSW index
**Returns**: Ranked list of semantically similar entities
**Use case**: Find conceptually related content without exact keyword matches

#### `TRAVERSE` - Recursive Graph Traversal

Follow `graph_edges` relationships across the knowledge graph.

```sql
TRAVERSE FROM "sarah-chen" TYPE "authored_by" DEPTH 2
TRAVERSE FROM "api-design-v2" TYPE "references,depends_on" DEPTH 3
```

**Features**:
- **Polymorphic**: Seamlessly traverses `resources`, `moments`, `users` via `all_graph_edges` view
- **Filtering**: Filter by one or multiple edge types (comma-separated)
- **Depth Control**: Configurable recursion depth (default: 2)
- **Data Model**: Requires `InlineEdge` JSON structure in `graph_edges` column

**Returns**: Graph of connected entities with edge metadata
**Use case**: Explore relationships, find connected entities, build context

#### Direct SQL Queries

Raw SQL for complex temporal, aggregation, or custom queries.

```sql
SELECT * FROM resources WHERE created_at > NOW() - INTERVAL '7 days' ORDER BY created_at DESC LIMIT 20
SELECT category, COUNT(*) as count FROM resources GROUP BY category
WITH recent AS (SELECT * FROM resources WHERE created_at > NOW() - INTERVAL '1 day') SELECT * FROM recent
```

**Performance**: Depends on query and indexes
**Returns**: Raw query results
**Use case**: Complex filtering, aggregations, temporal queries
**Allowed**: SELECT, INSERT, UPDATE, WITH (read + data modifications)
**Blocked**: DROP, DELETE, TRUNCATE, ALTER (destructive operations)
**Note**: Can be used standalone or with `WITH` syntax for composition

### Graph Edge Format

Edges stored inline using `InlineEdge` pattern with human-readable destination labels.

```json
{
  "dst": "sarah-chen",
  "rel_type": "authored_by",
  "weight": 1.0,
  "properties": {
    "dst_entity_type": "users:engineers/sarah-chen",
    "created_at": "2025-01-15T10:30:00Z"
  }
}
```

**Destination Entity Type Convention** (`properties.dst_entity_type`):

Format: `<table_schema>:<category>/<key>`

Examples:
- `"resources:managers/bob"` → Look up bob in resources table with category="managers"
- `"users:engineers/sarah-chen"` → Look up sarah-chen in users table
- `"moments:meetings/standup-2024-01"` → Look up in moments table
- `"resources/api-design-v2"` → Look up in resources table (no category)
- `"bob"` → Defaults to resources table, no category

**Edge Type Format** (`rel_type`):
- Use snake_case: `"authored_by"`, `"depends_on"`, `"references"`
- Be specific but consistent
- Use passive voice for bidirectional clarity

### Multi-Turn Iterated Retrieval

REM enables agents to conduct multi-turn database conversations:

1. **Initial Query**: Agent runs SEARCH to find candidates
2. **Refinement**: Agent analyzes results, runs LOOKUP on specific entities
3. **Context Expansion**: Agent runs TRAVERSE to find related entities
4. **Temporal Filter**: Agent runs SQL to filter by time range
5. **Final Answer**: Agent synthesizes knowledge from all queries

**Plan Memos**: Agents track query plans in scratchpad for iterative refinement.

### Query Performance Contracts

| Query Type | Complexity | Index | Use When |
|------------|-----------|-------|----------|
| `LOOKUP` | O(1) | B-tree on `label` | You know exact entity name |
| `FUZZY` | O(n) | GIN on `label` (pg_trgm) | Handling typos/partial matches |
| `SEARCH` | O(log n) | HNSW on `embedding` | Semantic similarity needed |
| `TRAVERSE` | O(depth × edges) | B-tree on `graph_edges` | Exploring relationships |
| `SQL` | Variable | Custom indexes | Complex filtering/aggregation |

### Example: Multi-Query Session

```python
# Query 1: Find relevant documents
SEARCH "API migration planning" FROM resources LIMIT 5

# Query 2: Get specific document
LOOKUP "tidb-migration-spec" FROM resources

# Query 3: Find related people
TRAVERSE FROM "tidb-migration-spec" TYPE "authored_by,reviewed_by" DEPTH 1

# Query 4: Recent activity
SELECT * FROM moments WHERE
    'tidb-migration' = ANY(topic_tags) AND
    start_time > NOW() - INTERVAL '30 days'
```

### Tenant Isolation

All queries automatically scoped by `user_id` for complete data isolation:

```sql
-- Automatically filtered to user's data
SEARCH "contracts" FROM resources LIMIT 10

-- No cross-user data leakage
TRAVERSE FROM "project-x" TYPE "references" DEPTH 3
```

## API Endpoints

### Chat Completions (OpenAI-compatible)

```bash
POST /api/v1/chat/completions
```

**Headers**:
- `X-Tenant-Id`: Tenant identifier (required for REM)
- `X-User-Id`: User identifier
- `X-Session-Id`: Session/conversation identifier
- `X-Agent-Schema`: Agent schema URI to use

**Body**:
```json
{
  "model": "anthropic:claude-sonnet-4-5-20250929",
  "messages": [
    {"role": "user", "content": "Find all documents Sarah authored"}
  ],
  "stream": true,
  "response_format": {"type": "text"}
}
```

**Streaming Response** (SSE):
```
data: {"id": "chatcmpl-123", "choices": [{"delta": {"role": "assistant", "content": ""}}]}

data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "[Calling: search_rem]"}}]}

data: {"id": "chatcmpl-123", "choices": [{"delta": {"content": "Found 3 documents..."}}]}

data: {"id": "chatcmpl-123", "choices": [{"delta": {}, "finish_reason": "stop"}]}

data: [DONE]
```

### MCP Endpoint

```bash
# MCP HTTP transport
POST /api/v1/mcp
```

Tools and resources for REM query execution, resource management, file operations.

### Health Check

```bash
GET /health
# {"status": "healthy", "version": "0.1.0"}
```

## CLI Reference

REM provides a comprehensive command-line interface for all operations.

### Configuration & Server

#### `rem configure` - Interactive Setup Wizard

Set up REM with PostgreSQL, LLM providers, and S3 storage. **Defaults to port 5051 (package users).**

```bash
# Complete setup (recommended for package users)
rem configure --install --claude-desktop

# This runs:
# 1. Interactive wizard (creates ~/.rem/config.yaml)
# 2. Installs database tables (rem db migrate)
# 3. Registers REM MCP server with Claude Desktop

# Other options:
rem configure                  # Just run wizard
rem configure --install        # Wizard + database install
rem configure --show           # Show current configuration
rem configure --edit           # Edit configuration in $EDITOR
```

**Default Configuration:**
- **Package users**: `localhost:5051` (docker-compose.prebuilt.yml with Docker Hub image)
- **Developers**: Change to `localhost:5050` during wizard (docker-compose.yml with local build)
- **Custom database**: Enter your own host/port/credentials

**Configuration File:** `~/.rem/config.yaml`

```yaml
postgres:
  # Package users (prebuilt)
  connection_string: postgresql://rem:rem@localhost:5051/rem
  # OR Developers (local build)
  # connection_string: postgresql://rem:rem@localhost:5050/rem
  pool_min_size: 5
  pool_max_size: 20

llm:
  default_model: anthropic:claude-sonnet-4-5-20250929
  openai_api_key: sk-...
  anthropic_api_key: sk-ant-...

s3:
  bucket_name: rem-storage
  region: us-east-1
```

**Precedence:** Environment variables > Config file > Defaults

**Port Guide:**
- **5051**: Package users with `docker-compose.prebuilt.yml` (recommended)
- **5050**: Developers with `docker-compose.yml` (local development)
- **Custom**: Your own PostgreSQL instance

#### `rem mcp` - Run MCP Server

Run the FastMCP server for Claude Desktop integration.

```bash
# Stdio mode (for Claude Desktop)
rem mcp

# HTTP mode (for testing)
rem mcp --http --port 8001
```

#### `rem serve` - Start API Server

Start the FastAPI server with uvicorn.

```bash
# Use settings from config
rem serve

# Development mode (auto-reload)
rem serve --reload

# Production mode (4 workers)
rem serve --workers 4

# Bind to all interfaces
rem serve --host 0.0.0.0 --port 8080

# Override log level
rem serve --log-level debug
```

### Database Management

#### `rem db migrate` - Run Migrations

Apply database migrations (install.sql and install_models.sql).

```bash
# Apply all migrations
rem db migrate

# Core infrastructure only (extensions, functions)
rem db migrate --install

# Entity tables only (Resource, Message, etc.)
rem db migrate --models

# Background indexes (HNSW for vectors)
rem db migrate --background-indexes

# Custom connection string
rem db migrate --connection "postgresql://user:pass@host:5432/db"

# Custom SQL directory
rem db migrate --sql-dir /path/to/sql
```

#### `rem db status` - Migration Status

Show applied migrations and execution times.

```bash
rem db status
```

#### `rem db rebuild-cache` - Rebuild KV Cache

Rebuild KV_STORE cache from entity tables (after database restart or bulk imports).

```bash
rem db rebuild-cache
```

### Schema Management

#### `rem db schema generate` - Generate SQL Schema

Generate database schema from Pydantic models.

```bash
# Generate install_models.sql from entity models
rem db schema generate \
  --models src/rem/models/entities \
  --output rem/src/rem/sql/install_models.sql

# Generate migration file
rem db schema generate \
  --models src/rem/models/entities \
  --output rem/src/rem/sql/migrations/003_add_fields.sql
```

#### `rem db schema indexes` - Generate Background Indexes

Generate SQL for background index creation (HNSW for vectors).

```bash
# Generate background_indexes.sql
rem db schema indexes \
  --models src/rem/models/entities \
  --output rem/src/rem/sql/background_indexes.sql
```

#### `rem db schema validate` - Validate Models

Validate Pydantic models for schema generation.

```bash
rem db schema validate --models src/rem/models/entities
```

### File Processing

#### `rem process files` - Process Files

Process files with optional custom extractor (ontology extraction).

```bash
# Process all completed files for tenant
rem process files \
  --tenant-id acme-corp \
  --status completed \
  --limit 10

# Process with custom extractor
rem process files \
  --tenant-id acme-corp \
  --extractor cv-parser-v1 \
  --limit 50

# Process files from the last 7 days
rem process files \
  --tenant-id acme-corp \
  --lookback-hours 168
```

#### `rem process ingest` - Ingest File into REM

Ingest a file into REM with full pipeline (storage + parsing + embedding + database).

```bash
# Ingest local file
rem process ingest /path/to/document.pdf \
  --user-id user-123 \
  --category legal \
  --tags contract,2024

# Ingest with minimal options
rem process ingest ./meeting-notes.md --user-id user-123
```

#### `rem process uri` - Parse File (Read-Only)

Parse a file and extract content **without** storing to database (useful for testing parsers).

```bash
# Parse local file (output to stdout)
rem process uri /path/to/document.pdf

# Parse and save extracted content to file
rem process uri /path/to/document.pdf --save output.json

# Parse S3 file
rem process uri s3://bucket/key.docx --output text
```

### Memory & Knowledge Extraction (Dreaming)

#### `rem dreaming full` - Complete Workflow

Run full dreaming workflow: extractors → moments → affinity → user model.

```bash
# Full workflow for user
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp

# Skip ontology extractors
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp \
  --skip-extractors

# Process last 24 hours only
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp \
  --lookback-hours 24

# Limit resources processed
rem dreaming full \
  --user-id user-123 \
  --tenant-id acme-corp \
  --limit 100
```

#### `rem dreaming custom` - Custom Extractor

Run specific ontology extractor on user's data.

```bash
# Run CV parser on user's files
rem dreaming custom \
  --user-id user-123 \
  --tenant-id acme-corp \
  --extractor cv-parser-v1

# Process last week's files
rem dreaming custom \
  --user-id user-123 \
  --tenant-id acme-corp \
  --extractor contract-analyzer-v1 \
  --lookback-hours 168 \
  --limit 50
```

#### `rem dreaming moments` - Extract Moments

Extract temporal narratives from resources.

```bash
# Generate moments for user
rem dreaming moments \
  --user-id user-123 \
  --tenant-id acme-corp \
  --limit 50

# Process last 7 days
rem dreaming moments \
  --user-id user-123 \
  --tenant-id acme-corp \
  --lookback-hours 168
```

#### `rem dreaming affinity` - Build Relationships

Build semantic relationships between resources using embeddings.

```bash
# Build affinity graph for user
rem dreaming affinity \
  --user-id user-123 \
  --tenant-id acme-corp \
  --limit 100

# Process recent resources only
rem dreaming affinity \
  --user-id user-123 \
  --tenant-id acme-corp \
  --lookback-hours 24
```

#### `rem dreaming user-model` - Update User Model

Update user model from recent activity (preferences, interests, patterns).

```bash
# Update user model
rem dreaming user-model \
  --user-id user-123 \
  --tenant-id acme-corp
```

### Evaluation & Experiments

#### `rem experiments` - Experiment Management

Manage evaluation experiments with datasets, prompts, and traces.

```bash
# Create experiment configuration
rem experiments create my-evaluation \
  --agent ask_rem \
  --evaluator rem-lookup-correctness \
  --description "Baseline evaluation"

# Run experiment
rem experiments run my-evaluation

# List experiments
rem experiments list
rem experiments show my-evaluation
```

#### `rem experiments dataset` - Dataset Management

```bash
# Create dataset from CSV
rem experiments dataset create rem-lookup-golden \
  --from-csv golden.csv \
  --input-keys query \
  --output-keys expected_label,expected_type

# Add more examples
rem experiments dataset add rem-lookup-golden \
  --from-csv more-data.csv \
  --input-keys query \
  --output-keys expected_label,expected_type

# List datasets
rem experiments dataset list
```

#### `rem experiments prompt` - Prompt Management

```bash
# Create agent prompt
rem experiments prompt create hello-world \
  --system-prompt "You are a helpful assistant." \
  --model-name gpt-4o

# List prompts
rem experiments prompt list
```

#### `rem experiments trace` - Trace Retrieval

```bash
# List recent traces
rem experiments trace list --project rem-agents --days 7 --limit 50
```

#### `rem experiments` - Experiment Config

Manage experiment configurations (A/B testing, parameter sweeps).

```bash
# Create experiment config
rem experiments create \
  --name cv-parser-test \
  --description "Test CV parser with different models"

# List experiments
rem experiments list

# Show experiment details
rem experiments show cv-parser-test

# Run experiment
rem experiments run cv-parser-test
```

### Interactive Agent

#### `rem ask` - Test Agent

Test Pydantic AI agent with natural language queries.

```bash
# Ask a question
rem ask "What documents did Sarah Chen author?"

# With context headers
rem ask "Find all resources about API design" \
  --user-id user-123 \
  --tenant-id acme-corp

# Use specific agent schema
rem ask "Analyze this contract" \
  --agent-schema contract-analyzer-v1
```

### Global Options

All commands support:

```bash
# Verbose logging
rem --verbose <command>
rem -v <command>

# Version
rem --version

# Help
rem --help
rem <command> --help
rem <command> <subcommand> --help
```

### Environment Variables

Override any setting via environment variables:

```bash
# Database
export POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5432/rem
export POSTGRES__POOL_MIN_SIZE=5

# LLM
export LLM__DEFAULT_MODEL=openai:gpt-4o
export LLM__OPENAI_API_KEY=sk-...
export LLM__ANTHROPIC_API_KEY=sk-ant-...

# S3
export S3__BUCKET_NAME=rem-storage
export S3__REGION=us-east-1

# Server
export API__HOST=0.0.0.0
export API__PORT=8000
export API__RELOAD=true

# Run command with overrides
rem serve
```

## Development (For Contributors)

**Best for**: Contributing to REM or customizing the codebase.

### Step 1: Clone Repository

```bash
git clone https://github.com/mr-saoirse/remstack.git
cd remstack/rem
```

### Step 2: Start PostgreSQL Only

```bash
# Start only PostgreSQL (port 5050 for developers, doesn't conflict with package users on 5051)
docker compose up postgres -d

# Verify connection
psql -h localhost -p 5050 -U rem -d rem -c "SELECT version();"
```

### Step 3: Set Up Development Environment

```bash
# IMPORTANT: If you previously installed the package and ran `rem configure`,
# delete the REM configuration directory to avoid conflicts:
rm -rf ~/.rem/

# Create virtual environment with uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode with all dependencies
uv pip install -e ".[all]"

# Set LLM API keys
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5050/rem"

# Verify CLI
rem --version
```

### Step 4: Initialize Database

```bash
# Apply migrations
rem db migrate

# Verify tables
psql -h localhost -p 5050 -U rem -d rem -c "\dt"
```

### Step 5: Run API Server (Optional)

```bash
# Start API server with hot reload
uv run python -m rem.api.main

# API runs on http://localhost:8000
```

### Step 6: Run Tests

```bash
# Run non-LLM tests (fast, no API costs)
uv run pytest tests/integration/ -m "not llm" -v

# Run all tests (uses API credits)
uv run pytest tests/integration/ -v

# Type check (saves report to .mypy/ folder)
../scripts/run_mypy.sh
```

Type checking reports are saved to `.mypy/report_YYYYMMDD_HHMMSS.txt` (gitignored).
Current status: 222 errors in 55 files (as of 2025-11-23).

### Environment Variables

All settings via environment variables with `__` delimiter:

```bash
# LLM
LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
LLM__DEFAULT_TEMPERATURE=0.5

# Auth (disabled by default)
AUTH__ENABLED=false
AUTH__OIDC_ISSUER_URL=https://accounts.google.com

# OTEL (disabled by default for local dev)
OTEL__ENABLED=false
OTEL__SERVICE_NAME=rem-api

# Postgres
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5050/rem

# S3
S3__BUCKET_NAME=rem-storage
S3__REGION=us-east-1
```

### Production Deployment (Optional)

For production deployment to AWS EKS with Kubernetes, see the main repository README:
- **Infrastructure**: [../../manifests/infra/pulumi/eks-yaml/README.md](../../manifests/infra/pulumi/eks-yaml/README.md)
- **Platform**: [../../manifests/platform/README.md](../../manifests/platform/README.md)
- **Application**: [../../manifests/application/README.md](../../manifests/application/README.md)


## REM Query Dialect (AST)

REM queries follow a structured dialect with formal grammar specification.

### Grammar

```
Query ::= LookupQuery | FuzzyQuery | SearchQuery | SqlQuery | TraverseQuery

LookupQuery ::= LOOKUP <key:string|list[string]>
  key         : Single entity name or list of entity names (natural language labels)
  performance : O(1) per key
  available   : Stage 1+
  examples    :
    - LOOKUP "Sarah"
    - LOOKUP ["Sarah", "Mike", "Emily"]
    - LOOKUP "Project Alpha"

FuzzyQuery ::= FUZZY <text:string> [THRESHOLD <t:float>] [LIMIT <n:int>]
  text        : Search text (partial/misspelled)
  threshold   : Similarity score 0.0-1.0 (default: 0.5)
  limit       : Max results (default: 5)
  performance : Indexed (pg_trgm)
  available   : Stage 1+
  example     : FUZZY "sara" THRESHOLD 0.5 LIMIT 10

SearchQuery ::= SEARCH <text:string> [TABLE <table:string>] [WHERE <clause:string>] [LIMIT <n:int>]
  text        : Semantic query text
  table       : Target table (default: "resources")
  clause      : Optional PostgreSQL WHERE clause for hybrid filtering (combines vector + structured)
  limit       : Max results (default: 10)
  performance : Indexed (pgvector)
  available   : Stage 3+
  examples    :
    - SEARCH "database migration" TABLE resources LIMIT 10
    - SEARCH "team discussion" TABLE moments WHERE "moment_type='meeting'" LIMIT 5
    - SEARCH "project updates" WHERE "created_at >= '2024-01-01'" LIMIT 20
    - SEARCH "AI research" WHERE "tags @> ARRAY['machine-learning']" LIMIT 10

  Hybrid Query Support: SEARCH combines semantic vector similarity with structured filtering.
  Use WHERE clause to filter on system fields or entity-specific fields.

SqlQuery ::= <raw_sql:string>
           | SQL <table:string> [WHERE <clause:string>] [ORDER BY <order:string>] [LIMIT <n:int>]

  Mode 1 (Raw SQL - Recommended):
    Any query not starting with a REM keyword (LOOKUP, FUZZY, SEARCH, TRAVERSE) is treated as raw SQL.
    Allowed: SELECT, INSERT, UPDATE, WITH (read + data modifications)
    Blocked: DROP, DELETE, TRUNCATE, ALTER (destructive operations)

  Mode 2 (Structured - Legacy):
    SQL prefix with table + WHERE clause (automatic tenant isolation)

  performance : O(n) with indexes
  available   : Stage 1+
  dialect     : PostgreSQL (full PostgreSQL syntax support)

  examples    :
    # Raw SQL (no prefix needed)
    - SELECT * FROM resources WHERE created_at > NOW() - INTERVAL '7 days' LIMIT 20
    - SELECT category, COUNT(*) as count FROM resources GROUP BY category
    - WITH recent AS (SELECT * FROM resources WHERE created_at > NOW() - INTERVAL '1 day') SELECT * FROM recent

    # Structured SQL (legacy, automatic tenant isolation)
    - SQL moments WHERE "moment_type='meeting'" ORDER BY starts_timestamp DESC LIMIT 10
    - SQL resources WHERE "metadata->>'status' = 'published'" LIMIT 20

  PostgreSQL Dialect: Full support for:
  - JSONB operators (->>, ->, @>, etc.)
  - Array operators (&&, @>, <@, etc.)
  - CTEs (WITH clauses)
  - Advanced filtering and aggregations

TraverseQuery ::= TRAVERSE [<edge_types:list>] WITH <initial_query:Query> [DEPTH <d:int>] [ORDER BY <order:string>] [LIMIT <n:int>]
  edge_types    : Relationship types to follow (e.g., ["manages", "reports-to"], default: all)
  initial_query : Starting query (typically LOOKUP)
  depth         : Number of hops (0=PLAN mode, 1=single hop, N=multi-hop, default: 1)
  order         : Order results (default: "edge.created_at DESC")
  limit         : Max nodes (default: 9)
  performance   : O(k) where k = visited nodes
  available     : Stage 3+
  examples      :
    - TRAVERSE manages WITH LOOKUP "Sally" DEPTH 1
    - TRAVERSE WITH LOOKUP "Sally" DEPTH 0  (PLAN mode: edge analysis only)
    - TRAVERSE manages,reports-to WITH LOOKUP "Sarah" DEPTH 2 LIMIT 5
```

### Query Availability by Evolution Stage

| Query Type | Stage 0 | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|------------|---------|---------|---------|---------|---------|
| LOOKUP     | ✗       | ✓       | ✓       | ✓       | ✓       |
| FUZZY      | ✗       | ✓       | ✓       | ✓       | ✓       |
| SEARCH     | ✗       | ✗       | ✗       | ✓       | ✓       |
| SQL        | ✗       | ✓       | ✓       | ✓       | ✓       |
| TRAVERSE   | ✗       | ✗       | ✗       | ✓       | ✓       |

**Stage 0**: No data, all queries fail.

**Stage 1** (20% answerable): Resources seeded with entity extraction. LOOKUP and FUZZY work for finding entities. SQL works for basic filtering.

**Stage 2** (50% answerable): Moments extracted. SQL temporal queries work. LOOKUP includes moment entities.

**Stage 3** (80% answerable): Affinity graph built. SEARCH and TRAVERSE become available. Multi-hop graph queries work.

**Stage 4** (100% answerable): Mature graph with rich historical data. All query types fully functional with high-quality results.

## License

MIT
