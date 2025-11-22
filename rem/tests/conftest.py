"""
Pytest configuration and fixtures for REM tests.
"""

import yaml
from pathlib import Path

import pytest


@pytest.fixture
def tests_data_dir() -> Path:
    """Path to tests/data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture
def query_agent_schema(tests_data_dir: Path) -> dict:
    """Load query agent YAML schema."""
    schema_path = tests_data_dir / "schemas" / "agents" / "query_agent.yaml"
    with open(schema_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def summarization_agent_schema(tests_data_dir: Path) -> dict:
    """Load summarization agent YAML schema."""
    schema_path = tests_data_dir / "schemas" / "agents" / "summarization_agent.yaml"
    with open(schema_path) as f:
        return yaml.safe_load(f)


@pytest.fixture
def accuracy_evaluator_schema(tests_data_dir: Path) -> dict:
    """Load accuracy evaluator YAML schema."""
    schema_path = tests_data_dir / "schemas" / "evaluators" / "accuracy_evaluator.yaml"
    with open(schema_path) as f:
        return yaml.safe_load(f)
