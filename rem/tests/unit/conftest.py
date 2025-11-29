"""
Pytest configuration and fixtures for REM unit tests.

Unit tests MUST be isolated from external dependencies like databases.
This conftest provides mocks for PostgresService and related components.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def mock_postgres_service():
    """
    Mock PostgresService for all unit tests.

    This prevents any database connection attempts during unit testing.
    The mock is applied at the module level where PostgresService is imported.
    """
    # Create a mock PostgresService
    mock_service = MagicMock()
    mock_service.connect = AsyncMock()
    mock_service.disconnect = AsyncMock()
    mock_service.execute = AsyncMock(return_value=[])
    mock_service.fetch_one = AsyncMock(return_value=None)
    mock_service.fetch_all = AsyncMock(return_value=[])
    mock_service.pool = MagicMock()
    mock_service._connected = False

    # Patch PostgresService in all locations where it might be imported
    with patch('rem.services.postgres.service.PostgresService', return_value=mock_service):
        with patch('rem.api.middleware.tracking.PostgresService', return_value=mock_service):
            with patch('rem.services.postgres.PostgresService', return_value=mock_service):
                yield mock_service


@pytest.fixture
def mock_rate_limiter():
    """Mock RateLimitService for unit tests."""
    mock_limiter = MagicMock()
    mock_limiter.check_rate_limit = AsyncMock(return_value=(True, None))  # (allowed, error)
    mock_limiter.get_limit_info = AsyncMock(return_value={
        "requests_remaining": 100,
        "reset_at": "2025-01-01T00:00:00Z"
    })

    with patch('rem.api.middleware.tracking.RateLimitService', return_value=mock_limiter):
        yield mock_limiter
