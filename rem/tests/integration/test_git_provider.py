"""Integration tests for GitProvider and GitService.

Tests semantic versioning, schema loading, version comparison, and
Git repository integration.
"""

import os
from pathlib import Path

import pytest

from rem.services.git import GitService
from rem.settings import settings


# Skip all tests if Git is not enabled
pytestmark = pytest.mark.skipif(
    not settings.git.enabled,
    reason="Git provider not enabled. Set GIT__ENABLED=true"
)


@pytest.fixture
def git_service():
    """Create GitService instance for testing."""
    return GitService()


def test_git_service_initialization(git_service):
    """Test GitService initializes correctly."""
    assert git_service.fs is not None
    assert git_service.fs._git_provider is not None
    assert git_service.schemas_dir == "rem/schemas/agents"
    assert git_service.experiments_dir == "rem/experiments"


def test_list_schema_versions(git_service):
    """Test listing semantic versions for a schema."""
    versions = git_service.list_schema_versions("test")

    # Should have at least 3 versions (v1.0.0, v2.0.0, v2.1.0)
    assert len(versions) >= 3

    # Versions should be sorted by semver (newest first)
    assert versions[0]["tag"] == "schemas/test/v2.1.0"
    assert versions[1]["tag"] == "schemas/test/v2.0.0"
    assert versions[2]["tag"] == "schemas/test/v1.0.0"

    # Each version should have required metadata
    for version in versions:
        assert "tag" in version
        assert "version" in version
        assert "commit" in version
        assert "date" in version
        assert "message" in version
        assert "author" in version


def test_list_schema_versions_with_pattern(git_service):
    """Test listing versions with pattern filter."""
    # Get all v2.x versions
    v2_versions = git_service.list_schema_versions("test", pattern="schemas/test/v2\\..*")

    assert len(v2_versions) >= 2
    for version in v2_versions:
        assert version["tag"].startswith("schemas/test/v2.")


def test_load_schema_latest(git_service):
    """Test loading latest schema version."""
    schema = git_service.load_schema("test")

    assert schema is not None
    assert schema["type"] == "object"
    assert "message" in schema["properties"]
    assert "confidence" in schema["properties"]
    assert "metadata" in schema["properties"]  # Latest version has metadata
    assert schema["json_schema_extra"]["version"] == "2.1.0"


def test_load_schema_specific_version(git_service):
    """Test loading specific schema version."""
    # Load v1.0.0
    v1_schema = git_service.load_schema("test", version="schemas/test/v1.0.0")

    assert v1_schema is not None
    assert v1_schema["type"] == "object"
    assert "message" in v1_schema["properties"]
    assert "confidence" not in v1_schema["properties"]  # v1.0.0 doesn't have confidence
    assert "metadata" not in v1_schema["properties"]  # v1.0.0 doesn't have metadata
    assert v1_schema["json_schema_extra"]["version"] == "1.0.0"

    # Load v2.0.0
    v2_schema = git_service.load_schema("test", version="schemas/test/v2.0.0")

    assert v2_schema is not None
    assert "message" in v2_schema["properties"]
    assert "confidence" in v2_schema["properties"]  # v2.0.0 has confidence
    assert "metadata" not in v2_schema["properties"]  # v2.0.0 doesn't have metadata yet
    assert v2_schema["json_schema_extra"]["version"] == "2.0.0"


def test_compare_schemas(git_service):
    """Test comparing two schema versions."""
    diff = git_service.compare_schemas("test", "schemas/test/v1.0.0", "schemas/test/v2.0.0")

    assert diff is not None
    assert isinstance(diff, str)

    # Diff should show confidence field addition
    assert "confidence" in diff
    assert "+" in diff  # Should have additions

    # Should be in unified diff format
    assert "@@" in diff  # Unified diff markers


def test_compare_schemas_minor_version(git_service):
    """Test comparing minor version bump."""
    diff = git_service.compare_schemas("test", "schemas/test/v2.0.0", "schemas/test/v2.1.0")

    assert diff is not None

    # Diff should show metadata field addition
    assert "metadata" in diff


def test_has_breaking_changes(git_service):
    """Test breaking change detection."""
    # v1.0.0 → v2.0.0 should be breaking (major version bump + required field added)
    has_breaking = git_service.has_breaking_changes(
        "test",
        "schemas/test/v1.0.0",
        "schemas/test/v2.0.0"
    )

    assert has_breaking is True  # Major version bump

    # v2.0.0 → v2.1.0 should NOT be breaking (minor version bump, optional field)
    has_breaking = git_service.has_breaking_changes(
        "test",
        "schemas/test/v2.0.0",
        "schemas/test/v2.1.0"
    )

    assert has_breaking is False  # Minor version, no breaking changes


def test_get_commit(git_service):
    """Test getting commit hash for specific version."""
    commit = git_service.get_commit("schemas/agents/examples/test.yaml", "schemas/test/v1.0.0")

    assert commit is not None
    assert isinstance(commit, str)
    assert len(commit) == 40  # Full commit hash


def test_sync(git_service):
    """Test repository sync (cache clearing)."""
    # This should not raise an error
    git_service.sync()

    # After sync, should still be able to load schemas
    schema = git_service.load_schema("test")
    assert schema is not None


def test_fs_git_uri(git_service):
    """Test FS class with git:// URIs."""
    from rem.services.fs import FS

    fs = FS()

    # Test git:// URI with ref parameter
    uri = "git://rem/schemas/agents/examples/test.yaml?ref=schemas/test/v1.0.0"

    # Check if file exists
    exists = fs.exists(uri)
    assert exists is True

    # Read file
    schema = fs.read(uri)
    assert schema is not None
    assert schema["json_schema_extra"]["version"] == "1.0.0"


def test_git_provider_ls(git_service):
    """Test listing files via GitProvider."""
    files = git_service.fs.ls("git://rem/schemas/agents/")

    assert len(files) > 0
    assert any("test.yaml" in f for f in files)


@pytest.mark.skipif(
    not os.getenv("GIT__DEFAULT_REPO_URL"),
    reason="GIT__DEFAULT_REPO_URL not set"
)
def test_real_repository_integration():
    """Test with real Git repository configuration."""
    # This test runs only if actual Git repository is configured
    git_svc = GitService()

    # List available schemas
    versions = git_svc.list_schema_versions("test")
    assert len(versions) > 0

    # Load latest
    schema = git_svc.load_schema("test")
    assert schema is not None


if __name__ == "__main__":
    # Allow running directly for local testing
    pytest.main([__file__, "-v"])
