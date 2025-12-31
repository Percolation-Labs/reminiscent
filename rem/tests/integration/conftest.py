"""
Pytest configuration for integration tests.

Integration tests may require real external services (database, LLM APIs).
Tests marked with `llm` require actual API calls and are skipped in pre-push hooks.
"""

import pytest

import rem.services.embeddings.worker as worker_module


@pytest.fixture(autouse=True)
def reset_embedding_worker():
    """Reset global embedding worker between tests."""
    # Reset before test
    worker_module._global_worker = None

    yield

    # Reset after test
    worker_module._global_worker = None


def pytest_collection_modifyitems(items):
    """Add markers to integration tests."""
    for item in items:
        if "/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
