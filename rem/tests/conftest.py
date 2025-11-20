"""
Pytest configuration and fixtures for REM tests.
"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def tests_data_dir() -> Path:
    """Path to tests/data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture
def query_agent_schema(tests_data_dir: Path) -> dict:
    """Load query agent JSON schema."""
    schema_path = tests_data_dir / "agents" / "query_agent.json"
    with open(schema_path) as f:
        return json.load(f)


@pytest.fixture
def summarization_agent_schema(tests_data_dir: Path) -> dict:
    """Load summarization agent JSON schema."""
    schema_path = tests_data_dir / "agents" / "summarization_agent.json"
    with open(schema_path) as f:
        return json.load(f)


@pytest.fixture
def accuracy_evaluator_schema(tests_data_dir: Path) -> dict:
    """Load accuracy evaluator JSON schema."""
    schema_path = tests_data_dir / "agents" / "evaluators" / "accuracy_evaluator.json"
    with open(schema_path) as f:
        return json.load(f)
