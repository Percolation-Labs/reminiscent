"""
Pytest configuration for integration tests.

Integration tests may require real external services (database, LLM APIs).
Tests marked with `llm` require actual API calls and are skipped in pre-push hooks.
"""

import asyncio
import pytest

import rem.services.embeddings.worker as worker_module
import rem.services.postgres as postgres_module
import rem.api.mcp_router.tools as mcp_tools_module


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop.

    This ensures all async tests and fixtures share the same event loop,
    preventing 'Event loop is closed' errors when mixing sync TestClient
    tests with async database tests.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def reset_embedding_worker():
    """Reset global embedding worker between tests."""
    # Reset before test
    worker_module._global_worker = None

    yield

    # Reset after test
    worker_module._global_worker = None


@pytest.fixture(autouse=True)
def reset_postgres_service_sync():
    """Reset postgres service state between tests (sync version for cleanup).

    This clears references but doesn't try to await disconnect, avoiding
    event loop issues during test teardown.
    """
    # Reset before test
    postgres_module._postgres_instance = None
    mcp_tools_module._service_cache.clear()

    yield

    # Reset after test
    postgres_module._postgres_instance = None
    mcp_tools_module._service_cache.clear()


def pytest_collection_modifyitems(items):
    """Add markers to integration tests."""
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
