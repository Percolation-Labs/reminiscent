"""
Git Service for semantic versioning and schema evolution tracking.

Provides high-level operations for working with versioned agent schemas,
evaluators, and experiments stored in Git repositories. Wraps GitProvider
with business logic and semantic versioning awareness.

**Key Concepts**:
1. **Schema Versioning**: Track agent schema evolution using semantic versions
2. **Reproducible Evaluations**: Pin experiments to specific schema versions
3. **Migration Planning**: Compare versions to identify breaking changes
4. **Audit Trail**: Track who changed what and when

**Architecture**:
```
GitService (this file)
    ↓
FS.git_provider (thin wrapper)
    ↓
GitProvider (git operations)
    ↓
GitPython (git CLI wrapper)
```

**Use Cases**:

1. **Schema Registry Pattern**:
   ```python
   git_svc = GitService()

   # List available schema versions
   versions = git_svc.list_schema_versions("cv-parser")

   # Load specific version
   schema = git_svc.load_schema("cv-parser", version="v2.1.0")

   # Load latest version
   schema = git_svc.load_schema("cv-parser")
   ```

2. **Version Comparison**:
   ```python
   # Compare two versions
   diff = git_svc.compare_schemas("cv-parser", "v2.0.0", "v2.1.0")

   # Check for breaking changes
   if git_svc.has_breaking_changes("cv-parser", "v2.0.0", "v2.1.0"):
       print("⚠️  Breaking changes detected!")
   ```

3. **Experiment Pinning**:
   ```python
   # Run experiment with pinned schema version
   schema = git_svc.load_schema("cv-parser", version="v2.1.0")
   experiment = git_svc.load_experiment("hello-world", version="v1.0.0")

   # Log version metadata
   metadata = {
       "schema_version": "v2.1.0",
       "experiment_version": "v1.0.0",
       "schema_commit": git_svc.get_commit("schemas/cv-parser.yaml", "v2.1.0")
   }
   ```

4. **Multi-Tenant Schema Management**:
   ```python
   # Each tenant can use different schema versions
   tenant_a_schema = git_svc.load_schema("cv-parser", version="v2.0.0")
   tenant_b_schema = git_svc.load_schema("cv-parser", version="v2.1.0")
   ```

**Integration with Agent Factory**:
```python
from rem.services.git_service import GitService
from rem.agentic.factory import create_agent

git_svc = GitService()

# Load schema from git
schema_content = git_svc.load_schema("cv-parser", version="v2.1.0")

# Create agent
agent = create_agent(schema_content)

# Run agent
result = await agent.run("Extract from resume...")
```

**CLI Integration**:
```bash
# List schema versions
rem git schema list cv-parser

# Compare versions
rem git schema diff cv-parser v2.0.0 v2.1.0

# Load schema at version
rem git schema show cv-parser --version v2.1.0

# Sync repo (pull latest changes)
rem git sync
```
"""

from typing import Any, TYPE_CHECKING
from pathlib import Path

from loguru import logger

from rem.settings import settings

if TYPE_CHECKING:
    from rem.services.fs import FS


class GitService:
    """
    High-level Git operations for versioned schemas and experiments.

    Provides semantic versioning awareness, schema comparison, and
    migration planning utilities. Wraps GitProvider with business logic.

    **Path Conventions**:
    - Agent schemas: schemas/agents/{agent_name}.yaml
    - Evaluators: schemas/evaluators/{agent_name}/{evaluator_name}.yaml
    - Experiments: experiments/{experiment_name}/

    **Version Format**: Semantic versioning (MAJOR.MINOR.PATCH)
    - Tags use format: schemas/{agent_name}/vX.Y.Z (e.g., schemas/test/v2.1.0)
    - Can use patterns: v2.* (all v2 versions)

    Attributes:
        fs: Filesystem interface with Git provider
        schemas_dir: Directory for agent schemas (default: schemas/agents)
        experiments_dir: Directory for experiments (default: experiments/)

    Examples:
        >>> git_svc = GitService()
        >>> versions = git_svc.list_schema_versions("cv-parser")
        >>> schema = git_svc.load_schema("cv-parser", version="schemas/cv-parser/v2.1.0")
        >>> diff = git_svc.compare_schemas("cv-parser", "schemas/cv-parser/v2.0.0", "schemas/cv-parser/v2.1.0")
    """

    def __init__(
        self,
        fs: "FS | None" = None,
        schemas_dir: str = "rem/schemas/agents",
        experiments_dir: str = "rem/experiments",
    ):
        """
        Initialize Git service.

        Args:
            fs: Filesystem interface (creates new FS() if None)
            schemas_dir: Directory for agent schemas (default: rem/schemas/agents)
            experiments_dir: Directory for experiments (default: rem/experiments)

        Raises:
            ValueError: If Git provider is not enabled
        """
        # Import here to avoid circular dependency
        from rem.services.fs import FS
        self.fs = fs or FS()

        if not settings.git.enabled or not self.fs._git_provider:
            raise ValueError(
                "Git provider not enabled. Set GIT__ENABLED=true and GIT__DEFAULT_REPO_URL"
            )

        # Type guard: git provider is guaranteed to exist after the check above
        assert self.fs._git_provider is not None

        self.schemas_dir = schemas_dir
        self.experiments_dir = experiments_dir

        logger.info("Initialized GitService")

    def list_schema_versions(
        self,
        schema_name: str,
        pattern: str | None = None
    ) -> list[dict[str, Any]]:
        """
        List all semantic versions of a schema.

        Returns versions sorted by semver (newest first) with commit metadata.

        Args:
            schema_name: Schema name (e.g., "cv-parser", "contract-analyzer")
            pattern: Optional version pattern (e.g., "v2\\..*" for v2.x.x only)

        Returns:
            List of version dicts:
            [
                {
                    "tag": "v2.1.1",
                    "version": (2, 1, 1),
                    "commit": "abc123...",
                    "date": "2025-01-15T10:30:00",
                    "message": "feat: Add confidence scoring",
                    "author": "alice@example.com"
                },
                ...
            ]

        Examples:
            >>> versions = git_svc.list_schema_versions("cv-parser")
            >>> print(f"Latest: {versions[0]['tag']}")
            Latest: v2.1.1

            >>> v2_versions = git_svc.list_schema_versions("cv-parser", pattern="v2\\..*")
            >>> print(f"Latest v2: {v2_versions[0]['tag']}")
            Latest v2: v2.1.1
        """
        schema_path = f"{self.schemas_dir}/{schema_name}.yaml"

        # Type guard: git provider exists (validated in __init__)
        assert self.fs._git_provider is not None

        versions = self.fs._git_provider.get_semantic_versions(
            schema_path,
            pattern=pattern
        )

        logger.info(
            f"Found {len(versions)} versions for schema '{schema_name}' "
            f"(pattern: {pattern or 'all'})"
        )

        return versions

    def load_schema(
        self,
        schema_name: str,
        version: str | None = None
    ) -> dict[str, Any]:
        """
        Load agent schema at specific version.

        Args:
            schema_name: Schema name (e.g., "cv-parser")
            version: Semantic version tag (e.g., "v2.1.0"), or None for latest

        Returns:
            Parsed schema content (dict from YAML)

        Raises:
            FileNotFoundError: If schema doesn't exist
            ValueError: If version is invalid

        Examples:
            >>> # Load latest version
            >>> schema = git_svc.load_schema("cv-parser")

            >>> # Load specific version
            >>> schema = git_svc.load_schema("cv-parser", version="v2.1.0")

            >>> # Use in agent factory
            >>> from rem.agentic.factory import create_agent
            >>> agent = create_agent(schema)
        """
        schema_path = f"{self.schemas_dir}/{schema_name}.yaml"

        if version:
            uri = f"git://{schema_path}?ref={version}"
        else:
            uri = f"git://{schema_path}"

        logger.info(f"Loading schema '{schema_name}' (version: {version or 'latest'})")

        return self.fs.read(uri)

    def compare_schemas(
        self,
        schema_name: str,
        version1: str,
        version2: str,
        unified: int = 3
    ) -> str:
        """
        Generate diff between two schema versions.

        Useful for:
        - Code review: What changed?
        - Migration planning: Breaking changes?
        - Audit trail: Who changed what?

        Args:
            schema_name: Schema name
            version1: First version (e.g., "v2.0.0")
            version2: Second version (e.g., "v2.1.0")
            unified: Number of context lines

        Returns:
            Unified diff string (Git format)

        Examples:
            >>> diff = git_svc.compare_schemas("cv-parser", "v2.0.0", "v2.1.0")
            >>> print(diff)
            --- a/schemas/cv-parser.yaml
            +++ b/schemas/cv-parser.yaml
            @@ -10,6 +10,7 @@
                 skills:
                   type: array
            +      description: Candidate technical skills

            >>> # Check for breaking changes
            >>> if "required:" in diff and "-" in diff:
            ...     print("⚠️  Breaking change: Required field removed")
        """
        schema_path = f"{self.schemas_dir}/{schema_name}.yaml"

        # Type guard: git provider exists (validated in __init__)
        assert self.fs._git_provider is not None

        diff = self.fs._git_provider.diff_versions(
            schema_path,
            version1,
            version2,
            unified=unified
        )

        logger.info(f"Generated diff for '{schema_name}' ({version1} → {version2})")

        return diff

    def has_breaking_changes(
        self,
        schema_name: str,
        version1: str,
        version2: str
    ) -> bool:
        """
        Check if upgrade contains breaking changes.

        Heuristics for breaking changes:
        - Required field removed
        - Field type changed
        - Enum values removed
        - Major version bump

        Args:
            schema_name: Schema name
            version1: Old version
            version2: New version

        Returns:
            True if breaking changes detected

        Examples:
            >>> has_breaking = git_svc.has_breaking_changes(
            ...     "cv-parser", "v1.2.0", "v2.0.0"
            ... )
            >>> if has_breaking:
            ...     print("⚠️  Manual migration required")
        """
        import re

        # Extract version numbers from tags (support both v2.1.0 and schemas/test/v2.1.0)
        semver_pattern = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

        v1_match = semver_pattern.search(version1)
        v2_match = semver_pattern.search(version2)

        if not v1_match or not v2_match:
            logger.warning(f"Could not parse versions: {version1}, {version2}")
            return False

        v1_major = int(v1_match.group(1))
        v2_major = int(v2_match.group(1))

        # Check major version bump
        if v2_major > v1_major:
            logger.warning(
                f"Major version bump detected: {version1} → {version2}"
            )
            return True

        # Check diff for breaking change patterns
        diff = self.compare_schemas(schema_name, version1, version2)

        breaking_patterns = [
            "- required:",  # Required field removed
            "- type:",  # Type changed
            "- enum:",  # Enum values removed
        ]

        for pattern in breaking_patterns:
            if pattern in diff:
                logger.warning(
                    f"Breaking change pattern '{pattern}' found in diff"
                )
                return True

        return False

    def load_experiment(
        self,
        experiment_name: str,
        version: str | None = None
    ) -> dict[str, Any]:
        """
        Load experiment configuration at specific version.

        Args:
            experiment_name: Experiment name (e.g., "hello-world")
            version: Version tag, or None for latest

        Returns:
            Experiment metadata and configuration

        Examples:
            >>> exp = git_svc.load_experiment("hello-world", version="v1.0.0")
            >>> ground_truth = exp["datasets"]["ground_truth"]
        """
        exp_path = f"{self.experiments_dir}/{experiment_name}/config.yaml"

        if version:
            uri = f"git://{exp_path}?ref={version}"
        else:
            uri = f"git://{exp_path}"

        logger.info(f"Loading experiment '{experiment_name}' (version: {version or 'latest'})")

        return self.fs.read(uri)

    def sync(self):
        """
        Sync repository (pull latest changes).

        Clears cache and forces fresh clone on next access.
        Useful for periodic updates or manual refresh.

        Examples:
            >>> # Cron job: sync every 5 minutes
            >>> git_svc.sync()

            >>> # Manual refresh after schema update
            >>> git_svc.sync()
            >>> schema = git_svc.load_schema("cv-parser")  # Gets latest
        """
        # Type guard: git provider exists (validated in __init__)
        assert self.fs._git_provider is not None

        self.fs._git_provider.clear_cache()
        logger.info("Cleared Git cache - next access will fetch latest changes")

    def get_commit(self, path: str, version: str) -> str:
        """
        Get commit hash for file at specific version.

        Useful for tracking exact version loaded for reproducibility.

        Args:
            path: File path in repository
            version: Version tag

        Returns:
            Full commit hash (40 characters)

        Examples:
            >>> commit = git_svc.get_commit("schemas/cv-parser.yaml", "v2.1.0")
            >>> print(f"Loaded from commit: {commit[:8]}")
            Loaded from commit: abc12345
        """
        # Type guard: git provider exists (validated in __init__)
        assert self.fs._git_provider is not None

        return self.fs._git_provider.get_current_commit(version)
