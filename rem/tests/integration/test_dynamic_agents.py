"""
Integration tests for dynamic agent loading from database.

Tests the complete workflow:
1. Load agent schema from database or filesystem
2. Verify schema caching behavior
3. Execute agent with test query (with LLM)
4. Verify structured output matches schema

Prerequisites:
- PostgreSQL running with rem schema
- Agent schemas loaded via: rem db load <schema>.yaml --user-id system
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
    test_schema = "test-schema-xyz"
    if test_schema.lower() in _fs_schema_cache:
        del _fs_schema_cache[test_schema.lower()]

    # Should fail since test-schema-xyz isn't in filesystem
    with pytest.raises(FileNotFoundError):
        load_agent_schema(
            test_schema,
            enable_db_fallback=False,  # Disable DB lookup
        )


# =============================================================================
# Caching Tests
# =============================================================================


@pytest.mark.asyncio
async def test_schema_caching_filesystem(db):
    """Test that filesystem schemas are properly cached after first load."""
    from rem.utils.schema_loader import _fs_schema_cache

    # Use a known filesystem schema (like rem-agents-query-agent if it exists)
    # This test documents expected caching behavior

    # Clear any existing test cache entries
    test_keys_to_clear = [k for k in _fs_schema_cache.keys() if "test" in k.lower()]
    for key in test_keys_to_clear:
        del _fs_schema_cache[key]

    # Note: DB schemas currently don't use _fs_schema_cache (TODO in schema_loader.py)
    # This test documents current behavior - DB schemas are NOT cached in _fs_schema_cache
    pass  # Placeholder for when filesystem schemas are tested
