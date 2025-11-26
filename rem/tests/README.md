# REM Testing Strategy

Test philosophy: Be slow to create tests. Focus on key requirements and documented conventions. Avoid brittle tests that assert specific values that could change.

## Test Categories

### Unit Tests (`tests/unit/`)

**Purpose**: Test pure logic, schema validation, and critical utilities in isolation.

**Rules**:
- ✅ **NEVER** use real services (databases, APIs, file systems)
- ✅ **ALWAYS** use mocks/stubs for external dependencies
- ✅ Focus on business logic, schema parsing, and data transformations
- ✅ Test documented conventions (path parsing, ID generation, schema validation)
- ✅ Fast execution (< 1s for entire suite)

**What to test**:
- Schema validation (Pydantic models, JSON Schema conformance)
- Data transformations (e.g., JSON Schema → Pydantic models)
- Utility functions (deterministic ID generation, path conventions)
- Edge cases in pure functions
- Documented conventions (e.g., parsing hooks path mapping)

**What NOT to test**:
- Implementation details that could change
- Specific string values (unless part of documented convention)
- Integration between services
- External API responses

**Examples**:
```python
# ✅ Good: Tests schema validation logic
def test_agent_schema_validation():
    schema = create_agent_schema(
        description="Test agent",
        properties={"result": {"type": "string"}},
        required=["result"],
        fully_qualified_name="rem.agents.Test"
    )
    assert isinstance(schema, AgentSchema)
    assert "result" in schema.properties

# ✅ Good: Tests documented convention
def test_deterministic_id_generation():
    """IDs should be same for same URI + ordinal."""
    prepared1 = prepare_record_for_upsert(resource1, Resource, entity_key_field="uri")
    prepared2 = prepare_record_for_upsert(resource2, Resource, entity_key_field="uri")
    assert prepared1["id"] == prepared2["id"]  # Deterministic

# ❌ Bad: Tests specific implementation detail
def test_id_format():
    id = generate_id("test")
    assert id.startswith("test-")  # Too specific, could change

# ❌ Bad: Tests specific string value
def test_error_message():
    with pytest.raises(ValueError) as exc:
        validate_input(None)
    assert str(exc.value) == "Input cannot be None"  # Brittle
```

### Integration Tests (`tests/integration/`)

**Purpose**: Test end-to-end flows with real services. Validate that components work together correctly.

**Rules**:
- ✅ **ALWAYS** use real services (PostgreSQL, S3/MinIO, Redis, etc.)
- ✅ **NEVER** use mocks for external services
- ✅ Test complete workflows (upload → parse → store → retrieve)
- ✅ Verify service integration points
- ✅ Can be slow (database setup, API calls)
- ✅ Use fixtures to manage service lifecycle

**What to test**:
- Database flows (upsert → trigger → KV store population)
- Auth flows (login → session → protected endpoint)
- File processing workflows (upload → parse → chunk → embed)
- API endpoint behavior (request → response)
- Content provider integration (file → extract → markdown)

**What NOT to test**:
- Specific values unless they're critical to the workflow
- Implementation details
- Multiple variations of the same flow

**Examples**:
```python
# ✅ Good: Tests end-to-end database flow
@pytest.mark.integration
async def test_batch_upsert_populates_kv_store(postgres_service):
    """Verify triggers populate KV store on upsert."""
    result = await postgres_service.batch_upsert(
        records=resources,
        model=Resource,
        table_name="resources"
    )
    assert result["upserted_count"] == 5
    assert result["kv_store_populated"] == 5  # Verify trigger worked

# ✅ Good: Tests auth workflow
@pytest.mark.integration
async def test_oauth_login_flow(api_client):
    """Test complete OAuth login flow."""
    # Initiate auth
    response = await api_client.get("/auth/login")
    assert response.status_code == 302
    # Follow redirect, exchange code, get session
    session = await complete_oauth_flow(response)
    assert session.user_id is not None

# ✅ Good: Tests content provider with real file
@pytest.mark.integration
def test_pdf_parsing_workflow(content_service, tmp_path):
    """Test PDF → markdown conversion."""
    pdf_file = tmp_path / "test.pdf"
    create_sample_pdf(pdf_file)  # Helper creates real PDF

    result = content_service.process_uri(str(pdf_file))
    assert result["provider"] == "doc"
    assert len(result["content"]) > 0  # Has content
    assert "metadata" in result  # Has metadata

# ❌ Bad: Mocking database in integration test
@pytest.mark.integration
async def test_batch_upsert_with_mock(mock_postgres):
    mock_postgres.batch_upsert.return_value = {"upserted_count": 5}
    # This defeats the purpose of integration testing!
```

## Running Tests

### All Tests
```bash
# Run everything
pytest

# Run with coverage
pytest --cov=rem --cov-report=html
```

### Unit Tests Only (Fast)
```bash
# All unit tests
pytest tests/unit/

# Specific test file
pytest tests/unit/agentic/test_schema.py

# Specific test
pytest tests/unit/agentic/test_schema.py::test_agent_schema_validation
```

### Integration Tests Only
```bash
# All integration tests
pytest tests/integration/

# Specific category
pytest tests/integration/services/

# Exclude tests requiring specific services
pytest tests/integration/ -k "not (postgres or redis)"
```

### Cost-Effective LLM Testing

**Recommended:** Use `openai:gpt-4.1-nano` for development and CI to minimize API costs:

```bash
# Run non-LLM integration tests (fast, no API costs)
REM_SKIP_CONFIG_FILE=true pytest tests/integration/ -m "not llm" -v

# Run LLM tests with cheap model (for development)
REM_SKIP_CONFIG_FILE=true LLM__DEFAULT_MODEL=openai:gpt-4.1-nano pytest tests/integration/ -m "llm" -v

# Run all tests with cheap model
REM_SKIP_CONFIG_FILE=true LLM__DEFAULT_MODEL=openai:gpt-4.1-nano pytest tests/integration/ -v
```

**Note:** Some tests may fail with smaller models due to:
- `UsageLimitExceeded` - smaller models need more turns, hitting the 20-request limit
- Query format differences - smaller models may not generate exact expected query syntax

These are model-specific behaviors, not code regressions. For release validation, use the default model (`anthropic:claude-sonnet-4-5-20250929`).

### Watch Mode (Development)
```bash
# Re-run tests on file changes
pytest-watch tests/unit/
```

## Test Fixtures

### Unit Test Fixtures (`tests/conftest.py`)
```python
@pytest.fixture
def query_agent_schema(tests_data_dir: Path) -> dict:
    """Load query agent schema."""
    # Loads from tests/data/schemas/agents/query_agent.yaml
```

### Integration Test Fixtures
```python
@pytest.fixture
async def postgres_service() -> PostgresService:
    """Real PostgreSQL connection for integration tests."""
    pg = PostgresService(connection_string="postgresql://rem:rem@localhost:5050/rem")
    await pg.connect()
    yield pg
    await pg.disconnect()
```

## Test Data

Test data lives in `tests/data/` - all in YAML format:
```
tests/data/
├── schemas/                        # Schema files (YAML)
│   ├── agents/                     # Agent schemas
│   │   ├── query_agent.yaml
│   │   ├── summarization_agent.yaml
│   │   └── test-cv-parser.yaml
│   └── evaluators/                 # Evaluator schemas
├── content-examples/               # Sample files for testing
│   ├── service_agreement.txt
│   ├── service_agreement_output.yaml
│   ├── pdf/
│   │   ├── service_contract.pdf
│   │   └── [more PDFs]
│   └── README.md
├── sample_conversations.yaml       # Conversation fixtures
├── graph_seed.yaml                 # Graph relationship seed data
└── seed/                           # Additional seed data for integration tests
    └── resources.yaml
```

**Convention:** All configuration and fixture data uses YAML format (not JSON or Python files). Executable code belongs in `tests/integration/` as proper test files.

### Test Helpers

Test helpers live in `tests/integration/helpers/`:
- `seed_data.py` - Repository-based seed data functions for all entity types
- Uses timezone-naive datetimes (UTC assumed)
- Follows current Repository API patterns

**Example usage:**
```python
from tests.integration.helpers import seed_resources

@pytest.fixture
async def populated_database(postgres_service):
    resources = await seed_resources(
        postgres_service,
        SAMPLE_RESOURCES,
        generate_embeddings=False,
    )
    return resources
```

See `tests/integration/helpers/README.md` for complete documentation.

## Test Requirements

### Prerequisites
```bash
# Unit tests (no external dependencies)
pytest tests/unit/

# Integration tests (requires services)
docker compose up -d postgres  # PostgreSQL
docker compose up -d minio     # S3-compatible storage
```

### Environment Variables
```bash
# For integration tests with real APIs
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# For local development
export POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5050/rem
export S3__ENDPOINT_URL=http://localhost:9000
```

## Writing Good Tests

### DO:
- ✅ Test documented behavior and conventions
- ✅ Test critical business logic
- ✅ Test edge cases that could cause bugs
- ✅ Use descriptive test names (`test_deterministic_id_with_same_uri`)
- ✅ Add docstrings explaining what's being tested
- ✅ Use fixtures for common setup
- ✅ Keep tests independent (no shared state)

### DON'T:
- ❌ Test implementation details
- ❌ Assert specific error messages (unless part of API contract)
- ❌ Test every possible input combination
- ❌ Create tests just to increase coverage
- ❌ Test third-party libraries
- ❌ Use brittle assertions (specific timestamps, UUIDs, etc.)

### Example: Good vs Bad

**❌ Bad - Tests implementation detail:**
```python
def test_internal_cache_size():
    service = MyService()
    service.process_data([1, 2, 3])
    assert len(service._cache) == 3  # Internal detail
```

**✅ Good - Tests documented behavior:**
```python
def test_data_processing_idempotent():
    """Processing same data twice should return same result."""
    service = MyService()
    result1 = service.process_data([1, 2, 3])
    result2 = service.process_data([1, 2, 3])
    assert result1 == result2  # Documented behavior
```

**❌ Bad - Brittle specific value:**
```python
def test_error_handling():
    with pytest.raises(ValueError) as exc:
        parse_date("invalid")
    assert str(exc.value) == "Invalid date format: invalid"  # Too specific
```

**✅ Good - Tests category of behavior:**
```python
def test_invalid_date_raises_error():
    """Invalid dates should raise ValueError."""
    with pytest.raises(ValueError):
        parse_date("invalid")  # What happens, not exact message
```

## CI/CD

Tests run in GitHub Actions on every push:
```yaml
# .github/workflows/test.yml
- name: Run unit tests
  run: pytest tests/unit/ --cov=rem

- name: Run integration tests
  run: |
    docker compose up -d postgres minio
    pytest tests/integration/
  env:
    POSTGRES__CONNECTION_STRING: postgresql://rem:rem@localhost:5050/rem
```

## Current Test Status

### Unit Tests
- ✅ Schema validation (AgentSchema, MCPToolReference, etc.)
- ✅ Pydantic AI provider (model creation, schema wrapping)
- ✅ REM Query Agent schema conformance
- ⚠️  One failing test (enum serialization) - not critical

### Integration Tests
- ✅ Content providers (text, doc, audio)
- ✅ Batch upsert with deterministic IDs
- ✅ REM query operations (LOOKUP, FUZZY, TRAVERSE)
- ⚠️  Some tests require PostgreSQL/services to be running
- ⚠️  Search tests fail without embeddings (expected)

## Contributing

When adding new tests:

1. **Ask yourself**: Is this testing critical behavior or implementation detail?
2. **Choose the right category**: Unit (logic) or Integration (services)
3. **Use existing patterns**: Follow examples in similar test files
4. **Be specific in docstrings**: Explain WHAT you're testing and WHY
5. **Keep it simple**: Don't overcomplicate test setup

## Philosophy

> "Tests are documentation that runs." - Unknown

Good tests:
- Document how the system should behave
- Catch regressions when behavior changes
- Give confidence during refactoring
- Are easy to understand and maintain

Bad tests:
- Break when implementation changes (but behavior doesn't)
- Require constant updates
- Test the same thing multiple ways
- Are hard to understand

**When in doubt, delete the test.** No test is better than a bad test.
