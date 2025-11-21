"""
Git service for versioned schema and experiment syncing.

Provides high-level operations for working with versioned agent schemas,
evaluators, and experiments stored in Git repositories.

Usage:
    from rem.services.git import GitService

    git_svc = GitService()
    versions = git_svc.list_schema_versions("cv-parser")
    schema = git_svc.load_schema("cv-parser", version="v2.1.0")
"""

from rem.services.git.service import GitService

__all__ = ["GitService"]
