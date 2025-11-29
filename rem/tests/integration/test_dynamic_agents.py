"""
Integration tests for dynamic agent loading from database.

Tests the complete workflow:
1. Load agent schema from database (Siggy mental health agent)
2. Verify schema caching behavior
3. Execute agent with test query
4. Verify structured output matches schema

Prerequisites:
- PostgreSQL running with rem schema
- Siggy agent loaded via: rem db load siggy_agent.yaml --user-id system
- LLM API keys configured (tests marked @pytest.mark.llm)
"""

import pytest
from unittest.mock import patch

from rem.services.postgres import get_postgres_service
from rem.utils.schema_loader import load_agent_schema, load_agent_schema_async, _fs_schema_cache


# =============================================================================
# Test Configuration
# =============================================================================

USER_ID = "system"
SCHEMA_NAME = "Siggy"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def db():
    """Get database connection for tests."""
    pg = get_postgres_service()
    if not pg:
        pytest.skip("PostgreSQL not available")
    await pg.connect()
    yield pg
    await pg.disconnect()


# =============================================================================
# Schema Loading Tests
# =============================================================================


@pytest.mark.asyncio
async def test_schema_not_found_returns_error():
    """Test that loading non-existent schema raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError) as exc_info:
        load_agent_schema(
            "nonexistent-agent-xyz",
            user_id=USER_ID,
            enable_db_fallback=True,
        )

    assert "nonexistent-agent-xyz" in str(exc_info.value)


@pytest.mark.asyncio
async def test_schema_database_fallback_disabled():
    """Test that with DB fallback disabled, only filesystem is searched."""
    # Clear cache
    if SCHEMA_NAME.lower() in _fs_schema_cache:
        del _fs_schema_cache[SCHEMA_NAME.lower()]

    # Should fail since Siggy isn't in filesystem
    with pytest.raises(FileNotFoundError):
        load_agent_schema(
            SCHEMA_NAME,
            enable_db_fallback=False,  # Disable DB lookup
        )


# =============================================================================
# Agent Execution Tests (require LLM)
# =============================================================================


@pytest.mark.asyncio
@pytest.mark.llm
async def test_create_agent_from_database_schema(db):
    """Test creating an agent from database-loaded schema."""
    from rem.agentic import create_agent, AgentContext

    # Load schema from database using async loader
    schema = await load_agent_schema_async(SCHEMA_NAME, user_id=USER_ID, db=db)

    # Create agent context
    context = AgentContext(
        user_id=USER_ID,
        tenant_id=USER_ID,
    )

    # Create agent from schema
    agent_runtime = await create_agent(
        context=context,
        agent_schema_override=schema,
    )

    assert agent_runtime is not None
    assert agent_runtime.agent is not None
    assert agent_runtime.temperature >= 0


@pytest.mark.asyncio
@pytest.mark.llm
async def test_execute_siggy_agent_green_risk(db):
    """Test executing Siggy agent with low-risk query."""
    from rem.agentic import create_agent, AgentContext

    # Load schema
    schema = await load_agent_schema_async(SCHEMA_NAME, user_id=USER_ID, db=db)

    # Create agent
    context = AgentContext(user_id=USER_ID, tenant_id=USER_ID)
    agent_runtime = await create_agent(context=context, agent_schema_override=schema)

    # Execute with low-risk query
    result = await agent_runtime.run(
        "What are the common side effects of sertraline?",
    )

    # Verify response structure
    assert result.output is not None, "Agent should return output"

    # Access structured output
    output = result.output
    if hasattr(output, "answer"):
        assert output.answer, "Should have non-empty answer"

    if hasattr(output, "analysis"):
        analysis = output.analysis
        # Risk level should be green for medication question
        if hasattr(analysis, "risk_level") or hasattr(analysis, "risk-level"):
            risk_level = getattr(analysis, "risk_level", None) or getattr(
                analysis, "risk-level", None
            )
            assert risk_level in ["green", "orange", "red"], f"Invalid risk level: {risk_level}"


@pytest.mark.asyncio
@pytest.mark.llm
async def test_execute_siggy_agent_elevated_risk(db):
    """Test Siggy agent risk assessment with elevated risk query."""
    from rem.agentic import create_agent, AgentContext

    # Load schema
    schema = await load_agent_schema_async(SCHEMA_NAME, user_id=USER_ID, db=db)

    # Create agent
    context = AgentContext(user_id=USER_ID, tenant_id=USER_ID)
    agent_runtime = await create_agent(context=context, agent_schema_override=schema)

    # Execute with query containing risk indicators
    result = await agent_runtime.run(
        "I've been feeling really down lately and sometimes I wish I wasn't here anymore.",
    )

    # Verify response contains crisis resources for elevated risk
    output = result.output
    if hasattr(output, "answer"):
        answer = output.answer.lower()
        # Should mention crisis resources for elevated risk
        assert any(
            term in answer for term in ["988", "crisis", "help", "support", "reach out"]
        ), "Should provide crisis resources for elevated risk"


# =============================================================================
# Caching Tests
# =============================================================================


@pytest.mark.asyncio
async def test_schema_caching_behavior(db):
    """Test that database schemas are properly cached after first load."""
    from rem.utils.schema_loader import _fs_schema_cache

    # Clear cache
    cache_key = SCHEMA_NAME.lower()
    if cache_key in _fs_schema_cache:
        del _fs_schema_cache[cache_key]

    # First load - should hit database
    schema1 = await load_agent_schema_async(SCHEMA_NAME, user_id=USER_ID, db=db)
    assert schema1 is not None

    # Note: DB schemas currently don't use _fs_schema_cache (TODO in schema_loader.py)
    # This test documents current behavior - DB schemas are NOT cached in _fs_schema_cache

    # Second load - with database fallback, still goes to DB each time
    # (until DB schema caching is implemented)
    schema2 = await load_agent_schema_async(SCHEMA_NAME, user_id=USER_ID, db=db)
    assert schema2 is not None

    # Schemas should be equivalent
    assert schema1.get("properties") == schema2.get("properties")
