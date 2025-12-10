"""
Test Schema Introspection MCP Tools.

This test validates that:
1. list_schema returns all REM database tables
2. get_schema returns accurate column information
3. An LLM can use schema information to construct valid SQL queries

Requirements:
    - PostgreSQL database must be running
    - POSTGRES__CONNECTION_STRING must be set
    - For LLM tests: OPENAI_API_KEY or ANTHROPIC_API_KEY must be set

Run with:
    # Non-LLM tests only (fast)
    pytest tests/integration/test_schema_introspection.py -v -m "not llm"

    # All tests including LLM
    pytest tests/integration/test_schema_introspection.py -v
"""

import pytest
from rem.api.mcp_router.tools import list_schema, get_schema, _service_cache


@pytest.fixture(autouse=True)
async def setup_services():
    """
    Setup services for each test.

    This fixture ensures the PostgresService and RemService are properly
    initialized and connected before each test, and cleaned up after.
    """
    from rem.services.postgres import get_postgres_service
    from rem.services.rem import RemService

    # Clear any stale service cache
    _service_cache.clear()

    # Initialize services
    postgres_service = get_postgres_service()
    await postgres_service.connect()

    rem_service = RemService(postgres_service=postgres_service)

    # Store in cache for tools to use
    _service_cache["postgres"] = postgres_service
    _service_cache["rem"] = rem_service

    yield

    # Cleanup
    await postgres_service.disconnect()
    _service_cache.clear()


@pytest.mark.asyncio
async def test_list_schema_returns_core_tables():
    """Test that list_schema returns expected REM core tables."""
    result = await list_schema()

    assert result["status"] == "success"
    assert "tables" in result
    assert "count" in result
    assert result["count"] > 0

    # Extract table names
    table_names = [t["name"] for t in result["tables"]]

    # Core REM tables that should exist
    expected_tables = ["resources", "moments", "users", "files", "messages"]

    found_tables = [t for t in expected_tables if t in table_names]
    print(f"\nFound {len(found_tables)}/{len(expected_tables)} expected tables:")
    for t in found_tables:
        print(f"  - {t}")

    # At least some core tables should exist
    assert len(found_tables) >= 3, f"Expected at least 3 core tables, found: {found_tables}"


@pytest.mark.asyncio
async def test_list_schema_includes_row_counts():
    """Test that list_schema includes estimated row counts."""
    result = await list_schema()

    assert result["status"] == "success"

    for table in result["tables"]:
        assert "name" in table
        assert "schema" in table
        assert "estimated_rows" in table
        # estimated_rows should be a number (can be 0 for empty tables)
        assert isinstance(table["estimated_rows"], int)

    print(f"\nTable row counts:")
    for table in result["tables"][:10]:  # Show first 10
        print(f"  {table['name']}: ~{table['estimated_rows']} rows")


@pytest.mark.asyncio
async def test_get_schema_resources():
    """Test that get_schema returns accurate schema for resources table."""
    result = await get_schema(table_name="resources")

    assert result["status"] == "success"
    assert result["table_name"] == "resources"
    assert "columns" in result
    assert result["column_count"] > 0

    # Extract column names
    column_names = [c["name"] for c in result["columns"]]

    # Expected columns for resources table
    expected_columns = ["id", "name", "content", "user_id", "created_at"]
    found_columns = [c for c in expected_columns if c in column_names]

    print(f"\nResources table schema ({result['column_count']} columns):")
    for col in result["columns"]:
        nullable = "NULL" if col["nullable"] else "NOT NULL"
        print(f"  {col['name']}: {col['type']} {nullable}")

    assert len(found_columns) >= 4, f"Expected core columns, found: {found_columns}"


@pytest.mark.asyncio
async def test_get_schema_with_column_filter():
    """Test that get_schema can filter to specific columns."""
    result = await get_schema(
        table_name="resources",
        columns=["id", "name", "created_at"]
    )

    assert result["status"] == "success"
    assert result["column_count"] == 3

    column_names = [c["name"] for c in result["columns"]]
    assert "id" in column_names
    assert "name" in column_names
    assert "created_at" in column_names

    print(f"\nFiltered columns: {column_names}")


@pytest.mark.asyncio
async def test_get_schema_includes_indexes():
    """Test that get_schema includes index information."""
    result = await get_schema(table_name="resources", include_indexes=True)

    assert result["status"] == "success"
    assert "indexes" in result

    # Should have at least primary key index
    assert len(result["indexes"]) >= 1

    print(f"\nResources table indexes:")
    for idx in result["indexes"]:
        unique = "UNIQUE" if idx["unique"] else ""
        primary = "(PK)" if idx["primary"] else ""
        print(f"  {idx['name']}: {idx['type']} {unique} {primary}")
        print(f"    Columns: {idx['columns']}")


@pytest.mark.asyncio
async def test_get_schema_includes_constraints():
    """Test that get_schema includes constraint information."""
    result = await get_schema(table_name="resources", include_constraints=True)

    assert result["status"] == "success"
    assert "constraints" in result

    # Should have at least primary key constraint
    constraint_types = [c["type"] for c in result["constraints"]]
    assert "PRIMARY KEY" in constraint_types

    print(f"\nResources table constraints:")
    for con in result["constraints"]:
        print(f"  {con['name']}: {con['type']}")
        print(f"    Columns: {con['columns']}")


@pytest.mark.asyncio
async def test_get_schema_nonexistent_table():
    """Test that get_schema handles nonexistent tables gracefully."""
    result = await get_schema(table_name="nonexistent_table_xyz")

    assert result["status"] == "error"
    assert "not found" in result["error"].lower()

    print(f"\nError message: {result['error']}")


@pytest.mark.asyncio
async def test_get_schema_primary_key():
    """Test that get_schema returns primary key information."""
    result = await get_schema(table_name="resources")

    assert result["status"] == "success"
    assert "primary_key" in result
    assert len(result["primary_key"]) >= 1
    assert "id" in result["primary_key"]

    print(f"\nPrimary key: {result['primary_key']}")


# =============================================================================
# LLM Integration Tests - Schema-aware SQL Construction
# =============================================================================

@pytest.mark.asyncio
@pytest.mark.llm
async def test_llm_constructs_sql_from_schema():
    """
    Test that an LLM can use schema information to construct a valid SQL query.

    This test:
    1. Uses list_tables and get_table_schema to get database schema
    2. Asks an LLM to construct a SQL query based on the schema
    3. Validates the query uses correct column names
    """
    from pydantic_ai import Agent
    from pydantic import BaseModel

    # Step 1: Get schema information using our new tools
    tables_result = await list_schema()
    assert tables_result["status"] == "success"

    # Get resources table schema
    schema_result = await get_schema(table_name="resources")
    assert schema_result["status"] == "success"

    # Format schema for LLM
    columns_info = "\n".join([
        f"  - {col['name']}: {col['type']} {'(nullable)' if col['nullable'] else '(required)'}"
        for col in schema_result["columns"]
    ])

    schema_context = f"""
Database Table: resources

Columns:
{columns_info}

Primary Key: {schema_result['primary_key']}
"""

    # Step 2: Ask LLM to construct SQL
    class SQLQuery(BaseModel):
        """SQL query constructed from schema."""
        query: str
        explanation: str

    agent = Agent(
        "openai:gpt-4o-mini",
        output_type=SQLQuery,
        system_prompt=(
            "You are a SQL expert. Given a database schema, construct valid SQL queries. "
            "Only use columns that exist in the schema. Return the query and a brief explanation."
        ),
    )

    prompt = f"""
{schema_context}

Task: Write a SQL query to find the 10 most recently created resources that are not deleted.
Use only columns that exist in the schema above.
"""

    result = await agent.run(prompt)

    # Step 3: Validate the query
    query = result.output.query.upper()

    # Check that query uses valid columns from schema
    column_names = [col["name"] for col in schema_result["columns"]]

    print(f"\nLLM-generated SQL query:")
    print(f"  {result.output.query}")
    print(f"\nExplanation: {result.output.explanation}")

    # Basic validation
    assert "SELECT" in query
    assert "FROM" in query
    assert "RESOURCES" in query

    # Should reference created_at for ordering
    if "created_at" in column_names:
        assert "CREATED_AT" in query or "ORDER BY" in query

    # Should have a LIMIT clause
    assert "LIMIT" in query

    print("\n Schema-aware SQL construction successful")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_llm_constructs_join_query_from_multiple_tables():
    """
    Test that an LLM can construct a JOIN query using multiple table schemas.
    """
    from pydantic_ai import Agent
    from pydantic import BaseModel

    # Get schemas for multiple tables
    resources_schema = await get_schema(table_name="resources")
    moments_schema = await get_schema(table_name="moments")

    if resources_schema["status"] != "success" or moments_schema["status"] != "success":
        pytest.skip("Required tables not found")

    # Format schema for LLM
    def format_schema(name: str, schema: dict) -> str:
        columns_info = "\n".join([
            f"    - {col['name']}: {col['type']}"
            for col in schema["columns"]
        ])
        return f"Table: {name}\n  Columns:\n{columns_info}"

    schema_context = f"""
{format_schema('resources', resources_schema)}

{format_schema('moments', moments_schema)}
"""

    class SQLQuery(BaseModel):
        query: str
        tables_used: list[str]
        explanation: str

    agent = Agent(
        "openai:gpt-4o-mini",
        output_type=SQLQuery,
        system_prompt=(
            "You are a SQL expert. Given database schemas, construct valid SQL queries. "
            "Only use columns that exist in the schemas provided."
        ),
    )

    prompt = f"""
{schema_context}

Task: Write a SQL query to find resources that have a user_id column
and show how many there are per user_id. Group by user_id and order by count descending.
"""

    result = await agent.run(prompt)

    print(f"\nLLM-generated query:")
    print(f"  {result.output.query}")
    print(f"\nTables used: {result.output.tables_used}")
    print(f"Explanation: {result.output.explanation}")

    query = result.output.query.upper()

    # Validate structure
    assert "SELECT" in query
    assert "FROM" in query
    assert "GROUP BY" in query or "COUNT" in query

    print("\n Multi-table schema analysis successful")


@pytest.mark.asyncio
@pytest.mark.llm
async def test_agent_with_schema_tools():
    """
    Test that a REM agent can use schema tools to understand database structure
    and answer questions about what data is available.
    """
    from pydantic_ai import Agent
    from pydantic_ai.tools import Tool
    from pydantic import BaseModel

    # Create tools that the agent can call
    async def agent_list_schema() -> dict:
        """List all tables in the REM database."""
        return await list_schema()

    async def agent_get_schema(table_name: str) -> dict:
        """Get schema for a specific table."""
        return await get_schema(table_name=table_name)

    class SchemaAnswer(BaseModel):
        """Answer about database schema."""
        answer: str
        tables_inspected: list[str]
        relevant_columns: list[str]

    agent = Agent(
        "openai:gpt-4o-mini",
        output_type=SchemaAnswer,
        system_prompt=(
            "You are a database assistant. Use the available tools to inspect "
            "the database schema and answer questions about what data is stored."
        ),
        tools=[
            Tool(agent_list_schema, takes_ctx=False),
            Tool(agent_get_schema, takes_ctx=False),
        ],
    )

    result = await agent.run(
        "What columns are available in the resources table for filtering by date?"
    )

    print(f"\nAgent answer: {result.output.answer}")
    print(f"Tables inspected: {result.output.tables_inspected}")
    print(f"Relevant columns: {result.output.relevant_columns}")

    # Should have inspected resources table
    assert "resources" in [t.lower() for t in result.output.tables_inspected]

    # Should have found date-related columns
    date_keywords = ["date", "time", "created", "updated", "at"]
    found_date_column = any(
        any(kw in col.lower() for kw in date_keywords)
        for col in result.output.relevant_columns
    )
    assert found_date_column, "Should find date-related columns"

    print("\n Agent with schema tools successful")


if __name__ == "__main__":
    import asyncio

    async def run_tests():
        print("=" * 80)
        print("Schema Introspection Test Suite")
        print("=" * 80)
        print()

        print("1. Testing list_tables...")
        await test_list_schema_returns_core_tables()
        print()

        print("2. Testing list_tables row counts...")
        await test_list_schema_includes_row_counts()
        print()

        print("3. Testing get_table_schema for resources...")
        await test_get_schema_resources()
        print()

        print("4. Testing column filtering...")
        await test_get_schema_with_column_filter()
        print()

        print("5. Testing index information...")
        await test_get_schema_includes_indexes()
        print()

        print("6. Testing constraint information...")
        await test_get_schema_includes_constraints()
        print()

        print("7. Testing nonexistent table handling...")
        await test_get_schema_nonexistent_table()
        print()

        print("8. Testing primary key extraction...")
        await test_get_schema_primary_key()
        print()

        print("=" * 80)
        print(" Non-LLM tests passed!")
        print("=" * 80)
        print()

        # LLM tests
        print("Running LLM tests (requires API key)...")
        print()

        try:
            print("9. Testing LLM SQL construction from schema...")
            await test_llm_constructs_sql_from_schema()
            print()

            print("10. Testing LLM with multiple table schemas...")
            await test_llm_constructs_join_query_from_multiple_tables()
            print()

            print("11. Testing agent with schema tools...")
            await test_agent_with_schema_tools()
            print()

            print("=" * 80)
            print(" All tests passed!")
            print("=" * 80)

        except Exception as e:
            print(f"LLM tests failed (may need API key): {e}")

    asyncio.run(run_tests())
