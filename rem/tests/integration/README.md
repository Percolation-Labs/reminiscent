# REM Integration Tests

Integration tests for REM data pipeline, query system, and agentic workflows.

## Quick Start

```bash
# Complete teardown and spin-up (validates init scripts)
docker compose down -v && docker compose up -d postgres
pytest tests/integration/test_seed_data_population.py -v

# With detailed logging
docker compose down -v && docker compose up -d postgres
pytest tests/integration/test_seed_data_population.py -v --log-cli-level=INFO

# Run all integration tests
pytest tests/integration/ -v
```

**Note:** The `docker compose down -v` flag destroys volumes for a truly fresh database. The `-v` is critical for testing init scripts (`sql/migrations/*.sql`) that run via `docker-entrypoint-initdb.d`.

## Test Categories

### 🔥 CRITICAL: Seed Data Population

**File:** `test_seed_data_population.py`

The most important integration tests - validates the complete data ingestion pipeline.

**What it tests:**
- ✅ Standard seed data loading (users, resources, moments, files, messages, schemas)
- ✅ Engram YAML processing (memory documents with attached moments)
- ✅ Dual indexing (SQL + KV store + embeddings structure)
- ✅ Graph edges with human-friendly labels
- ✅ Comprehensive diagnostics

**Three tests:**
1. `test_load_standard_seed_data` - Loads entities from YAML, validates KV store
2. `test_process_engram_files` - Processes engram YAML files, creates Resources and Moments
3. `test_data_diagnostics` - **MASTER TEST** - Complete end-to-end validation

**Run this first** - all other tests depend on data being properly ingested.

```bash
# Verify setup first
python tests/integration/verify_setup.py

# Run master diagnostic test
pytest tests/integration/test_seed_data_population.py::test_data_diagnostics -v --log-cli-level=INFO
```

**Test data created:**
- 3 users (Sarah Chen, Mike Rodriguez, Alex Kim)
- 6 resources (3 standard + 3 engrams)
- 9 moments (3 standard + 6 from engrams)
- 4 messages, 3 files, 3 schemas
- ~28 KV store entries
- Graph edges on all resources and moments

**Engram files:**
- `team_standup_meeting.yaml` - Meeting with 3 moments (progress, API, blocker)
- `personal_reflection.yaml` - Personal diary with 3 moments
- `product_idea_voice_memo.yaml` - Voice memo with location metadata

### Query System Tests

**File:** `test_rem_query.py`

Tests REM query operations:
- LOOKUP - O(1) exact match by label
- SEARCH - Vector similarity search (requires embeddings)
- TRAVERSE - Graph traversal with multi-hop relationships
- SQL - Direct SQL queries with filtering

### Batch Upsert Tests

**File:** `test_batch_upsert.py`

Tests PostgreSQL batch upsert functionality:
- Deterministic ID generation
- Composite key handling (uri + ordinal)
- KV store trigger population
- Transaction safety

### Content Provider Tests

**File:** `services/test_content_providers.py`

Tests file content extraction:
- Text files (.txt, .md)
- Documents (.pdf, .docx) - Kreuzberg integration
- Audio files (.m4a, .mp3) - Transcription

### Embedding Tests

**Files:**
- `test_embeddings_e2e.py` - End-to-end embedding generation
- `test_embedding_worker.py` - Background worker processing

Tests embedding generation pipeline:
- OpenAI text-embedding-3-small integration
- Batch embedding generation
- Embeddings table population
- Vector similarity search readiness

## Test Data

All test data lives in `tests/data/seed/`:

```
tests/data/seed/
├── 001_sample_data.yaml           # Standard entities
├── resources.yaml                  # Additional resources
└── files/
    ├── engrams/                    # Engram YAML files
    │   ├── team_standup_meeting.yaml
    │   ├── personal_reflection.yaml
    │   └── product_idea_voice_memo.yaml
    └── documents/                  # Standard documents
        ├── api_spec.md
        └── meeting_notes.txt
```

See `data/seed/README.md` for detailed documentation.

## Prerequisites

### Database

PostgreSQL with pgvector running on localhost:5050:

```bash
docker compose up -d postgres
```

Migrations are automatically applied via docker-entrypoint-initdb.d:
- `001_install.sql` - pgvector extension, core functions
- `002_install_models.sql` - Entity tables, KV store, triggers

### Environment Variables

Optional - tests work with defaults:

```bash
# For embedding tests (requires real API)
export OPENAI_API_KEY=sk-...

# For custom database connection
export POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5050/rem
```

## Running Tests

### All Integration Tests

```bash
pytest tests/integration/ -v
```

### Specific Test File

```bash
pytest tests/integration/test_seed_data_population.py -v
```

### Specific Test Function

```bash
pytest tests/integration/test_seed_data_population.py::test_data_diagnostics -v
```

### With Logging

```bash
pytest tests/integration/ -v --log-cli-level=INFO
```

### Skip Slow Tests

```bash
pytest tests/integration/ -v -m "not slow"
```

## Test Isolation

Each test file uses `fresh_database` fixture to:
1. Clear all data for `tenant_id="acme-corp"`
2. Ensure clean slate for each test run
3. Prevent test pollution

**WARNING:** Only run against test database (localhost:5050), not production!

## Troubleshooting

### Database Connection Issues

```bash
# Check database is running
docker ps --filter "name=rem-postgres"

# Check database is healthy
docker exec rem-postgres pg_isready -U rem -d rem

# Restart if needed
docker compose down
docker compose up -d postgres
sleep 10
```

### Migrations Not Applied

```bash
# Check if tables exist
docker exec rem-postgres psql -U rem -d rem -c "\\dt"

# Manually apply if needed
docker exec -i rem-postgres psql -U rem -d rem < sql/migrations/001_install.sql
docker exec -i rem-postgres psql -U rem -d rem < sql/migrations/002_install_models.sql
```

### KV Store Not Populated

```bash
# Check if triggers exist
docker exec rem-postgres psql -U rem -d rem -c "\\dftS"

# Check KV store has entries
docker exec rem-postgres psql -U rem -d rem -c "SELECT COUNT(*) FROM kv_store WHERE tenant_id = 'acme-corp';"

# Manually populate for testing
docker exec rem-postgres psql -U rem -d rem << 'EOF'
SELECT populate_kv_store('resources');
SELECT populate_kv_store('moments');
SELECT populate_kv_store('users');
EOF
```

### Engram Processing Fails

**Pydantic validation errors:**
- Check `present_persons` format matches `Person` model (id, name, role)
- Check `starts_timestamp` is valid ISO 8601 datetime
- Check `graph_edges` format matches `InlineEdge` model

**Example:**
```yaml
present_persons:
  - id: "sarah-chen"
    name: "Sarah Chen"
    role: "VP Engineering"  # Optional, but must be string if provided
```

### No Graph Edges Visible

```bash
# Check for non-empty graph_edges
docker exec rem-postgres psql -U rem -d rem << 'EOF'
SELECT name, jsonb_array_length(graph_edges) as edge_count
FROM resources
WHERE tenant_id = 'acme-corp'
AND jsonb_array_length(COALESCE(graph_edges, '[]'::jsonb)) > 0
ORDER BY edge_count DESC;
EOF
```

### Import Errors

```bash
# Ensure rem package is installed in editable mode
pip install -e .

# Or use uv
uv sync
```

### Embedding Tables Missing

**Expected:** Some embeddings tables may not exist yet (migrations pending).
**Impact:** Tests will skip embedding structure validation for missing tables.
**Action:** No action needed - structure validation is optional.

## Test Philosophy

From `tests/README.md`:

> **Be slow to create tests.** Focus on key requirements and documented conventions. Avoid brittle tests that assert specific values that could change.

Integration tests should:
- ✅ Test end-to-end workflows with real services
- ✅ Validate service integration points
- ✅ Use real PostgreSQL, not mocks
- ❌ Not test implementation details
- ❌ Not assert specific values unless critical

## CI/CD

Tests run in GitHub Actions on every push:

```yaml
- name: Start PostgreSQL
  run: docker compose up -d postgres

- name: Wait for database
  run: sleep 10

- name: Run integration tests
  run: pytest tests/integration/ -v
  env:
    POSTGRES__CONNECTION_STRING: postgresql://rem:rem@localhost:5050/rem
```

## Key Files

- `test_seed_data_population.py` - **CRITICAL** data ingestion tests
- `verify_setup.py` - Quick health check script
- `conftest.py` - Shared fixtures and configuration
- `../data/seed/README.md` - Seed data documentation

## Next Steps

After integration tests pass:

1. **Embedding Generation**
   ```bash
   python -m rem.workers.embedding_worker --tenant-id=acme-corp
   ```

2. **Query Testing**
   ```bash
   pytest tests/integration/test_rem_query.py -v
   ```

3. **Agent Testing**
   ```bash
   pytest tests/integration/test_ask_rem_agent.py -v
   ```

4. **Dreaming Worker**
   ```bash
   python -m rem.cli.dreaming full --tenant-id=acme-corp
   ```

## Quick Reference

### Database Operations

```bash
# Complete teardown and fresh spin-up (validates init scripts)
docker compose down -v && docker compose up -d postgres

# Check migrations applied
docker exec rem-postgres psql -U rem -d rem -c "SELECT * FROM migration_status();"

# Check KV store entries (auto-populated by triggers)
docker exec rem-postgres psql -U rem -d rem -c "SELECT entity_key, entity_type FROM kv_store LIMIT 10;"

# Manual cleanup for specific tenant
docker exec rem-postgres psql -U rem -d rem -c "DELETE FROM users WHERE tenant_id = 'acme-corp';"
```

**Note:** KV store is **automatically populated by triggers** on INSERT/UPDATE/DELETE. Manual rebuild is **only needed** after:
- Database crash/restart (UNLOGGED table lost)
- Backup restoration (UNLOGGED not backed up)
- Bulk data imports that bypass triggers (COPY, pg_restore)

```bash
# Rebuild KV store (only needed in scenarios above)
docker exec rem-postgres psql -U rem -d rem -c "SELECT * FROM rebuild_kv_store();"
```

### Testing

```bash
# Full teardown/spin-up + seed data test (recommended)
docker compose down -v && docker compose up -d postgres && sleep 15 && pytest tests/integration/test_seed_data_population.py -v

# Or wait for healthcheck explicitly
docker compose down -v
docker compose up -d postgres
until docker exec rem-postgres pg_isready -U rem -d rem; do sleep 1; done
pytest tests/integration/test_seed_data_population.py -v

# Verify database setup
python tests/integration/verify_setup.py

# Run specific test
pytest tests/integration/test_seed_data_population.py::test_data_diagnostics -v

# Run all integration tests
pytest tests/integration/ -v
```

## Related Documentation

- [REM Testing Strategy](../README.md) - Overall testing philosophy
- [Seed Data README](../data/seed/README.md) - Test data contents
- [CLAUDE.md](../../../CLAUDE.md) - REM architecture overview
- [Engram Specification](/Users/sirsh/code/p8fs-modules/p8fs/docs/04 engram-specification.md) - Engram format

---

**Remember:** Run `test_seed_data_population.py` first. Everything else depends on it.
