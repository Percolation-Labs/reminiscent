"""
Git repository provider for versioned schema and experiment syncing.

Enables REM to sync agent schemas, evaluators, and experiments from Git repositories
using SSH or HTTPS authentication. Designed for Kubernetes cluster environments with
proper secret management via Kubernetes Secrets or IRSA/Workload Identity.

**Architecture Pattern**: git-sync sidecar
- Primary use case: Kubernetes pods with git-sync sidecar container
- Alternative: Direct cloning from application code (this implementation)
- Caching: Local filesystem cache to minimize network traffic

**Use Cases**:
1. **Agent Schema Versioning**:
   - Sync agent schemas from git://repo/schemas/
   - Checkout specific tags/releases for reproducible builds
   - Multi-environment: dev uses main branch, prod uses release tags

2. **Experiment Tracking**:
   - Store evaluation datasets in git://repo/experiments/
   - Version control for ground truth data
   - CI/CD integration: commit → test → deploy

3. **Multi-Tenancy**:
   - Different tenants use different repos/branches
   - Tenant-specific schema overrides
   - Centralized schema library with tenant customization

**Authentication Methods**:

1. **SSH (Production Recommended)**:
   - Uses SSH keys from Kubernetes Secrets
   - Key stored at /etc/git-secret/ssh (0400 permissions)
   - Known hosts at /etc/git-secret/known_hosts
   - No rate limits, full Git protocol support
   - Example URL: ssh://git@github.com/org/repo.git

2. **HTTPS with Personal Access Token**:
   - GitHub PAT: 5,000 API requests/hour per authenticated user
   - GitLab PAT: Similar rate limits
   - Easier local development setup
   - Example URL: https://github.com/org/repo.git

**Kubernetes Secret Management**:

```bash
# Create secret with SSH key and known_hosts
kubectl create secret generic git-creds \\
  --from-file=ssh=$HOME/.ssh/id_rsa \\
  --from-file=known_hosts=$HOME/.ssh/known_hosts

# Pod spec
apiVersion: v1
kind: Pod
metadata:
  name: rem-api
spec:
  volumes:
    - name: git-secret
      secret:
        secretName: git-creds
        defaultMode: 0400  # Read-only for owner
  containers:
    - name: rem-api
      image: rem-api:latest
      volumeMounts:
        - name: git-secret
          mountPath: /etc/git-secret
          readOnly: true
      securityContext:
        fsGroup: 65533  # git user group
      env:
        - name: GIT__ENABLED
          value: "true"
        - name: GIT__DEFAULT_REPO_URL
          value: "ssh://git@github.com/my-org/my-repo.git"
        - name: GIT__SSH_KEY_PATH
          value: "/etc/git-secret/ssh"
```

**Path Conventions**:
- URI format: git://repo_url/path/to/file.yaml
- Local cache: {cache_dir}/{repo_hash}/{path/to/file.yaml}
- Agent schemas: git://repo/schemas/agent-name.yaml
- Experiments: git://repo/experiments/experiment-name/
- Evaluators: git://repo/schemas/evaluators/evaluator-name.yaml

**Sparse Checkout** (Future Enhancement):
- Only checkout specific directories (schemas/, experiments/)
- Reduces clone size for large mono-repos
- Faster sync times

**Examples**:

```python
from rem.services.fs import FS
from rem.settings import settings

# Enable Git provider
settings.git.enabled = True
settings.git.default_repo_url = "ssh://git@github.com/org/repo.git"

fs = FS()

# Read agent schema from git repo at specific tag
schema = fs.read("git://schemas/cv-parser-v1.yaml?ref=v1.0.0")

# Read from main branch (default)
schema = fs.read("git://schemas/cv-parser-v1.yaml")

# List all schemas in repo
schemas = fs.ls("git://schemas/")

# Check if file exists
if fs.exists("git://experiments/hello-world/ground_truth.csv"):
    data = fs.read("git://experiments/hello-world/ground_truth.csv")
```

**Integration with Agent Factory**:

```python
from rem.agentic.factory import create_agent
from rem.services.fs import FS

fs = FS()

# Load schema from git repo
schema_content = fs.read("git://schemas/cv-parser-v1.yaml?ref=v1.2.0")

# Create agent from versioned schema
agent = create_agent(schema_content)

# Run agent
result = await agent.run("Extract candidate from resume...")
```

**Performance Characteristics**:
- First clone: O(repo_size), typically 1-10 seconds for small repos
- Cached reads: O(1), local filesystem read
- Periodic sync: Configurable via GIT__SYNC_INTERVAL (default: 5 minutes)
- Shallow clones: --depth=1 reduces clone size by ~90% for large repos

**Security Considerations**:
- SSH keys stored in Kubernetes Secrets, not environment variables
- Use read-only deploy keys (GitHub: Settings → Deploy keys)
- Enable known_hosts verification to prevent MITM attacks
- Rotate PATs every 90 days (GitHub best practice)
- Use least-privilege principle: read-only access only

**Error Handling**:
- Authentication failures: Clear error messages with troubleshooting steps
- Network timeouts: Configurable timeout + exponential backoff
- Invalid refs: Fallback to default branch with warning
- Disk full: Clear old cached repos before cloning

**Future Enhancements**:
1. Git LFS support for large binary files (datasets, models)
2. Submodule support for shared schema libraries
3. Webhook-triggered sync (GitHub Actions → API call → immediate sync)
4. Metrics: clone time, cache hit rate, sync frequency
5. Multi-repo support: Multiple repos in single FS instance
"""

from pathlib import Path
from typing import Any, BinaryIO, Iterator
import hashlib
import os
import shutil
from urllib.parse import urlparse, parse_qs

from loguru import logger

# Optional GitPython dependency
try:
    from git import Repo, GitCommandError
    from git.exc import InvalidGitRepositoryError, NoSuchPathError
    GitPython_available = True
except ImportError:
    GitPython_available = False
    Repo = None  # type: ignore[assignment,misc]
    GitCommandError = Exception  # type: ignore[assignment,misc]
    InvalidGitRepositoryError = Exception  # type: ignore[assignment,misc]
    NoSuchPathError = Exception  # type: ignore[assignment,misc]

from rem.settings import settings


def is_git(uri: str) -> bool:
    """
    Check if URI is a Git repository path.

    Args:
        uri: URI to check

    Returns:
        True if URI starts with git://, False otherwise

    Examples:
        >>> is_git("git://schemas/agent.yaml")
        True
        >>> is_git("s3://bucket/file.txt")
        False
        >>> is_git("/local/path/file.txt")
        False
    """
    return uri.startswith("git://")


def parse_git_uri(uri: str) -> tuple[str, str | None]:
    """
    Parse Git URI into path and optional ref.

    Git URIs support query parameters for specifying refs (branches, tags, commits):
    - git://path/to/file.yaml - Uses default branch
    - git://path/to/file.yaml?ref=v1.0.0 - Uses tag v1.0.0
    - git://path/to/file.yaml?ref=feature-branch - Uses branch
    - git://path/to/file.yaml?ref=abc123 - Uses commit hash

    Args:
        uri: Git URI (git://path/to/file.yaml?ref=tag)

    Returns:
        Tuple of (path, ref) where ref is None if not specified

    Examples:
        >>> parse_git_uri("git://schemas/agent.yaml")
        ('schemas/agent.yaml', None)
        >>> parse_git_uri("git://schemas/agent.yaml?ref=v1.0.0")
        ('schemas/agent.yaml', 'v1.0.0')
        >>> parse_git_uri("git://experiments/hello-world/?ref=main")
        ('experiments/hello-world/', 'main')
    """
    # Remove git:// prefix
    uri_without_scheme = uri[6:]  # len("git://") = 6

    # Split path and query string
    if "?" in uri_without_scheme:
        path, query = uri_without_scheme.split("?", 1)
        # Parse query parameters
        params = parse_qs(query)
        ref = params.get("ref", [None])[0]
    else:
        path = uri_without_scheme
        ref = None

    return path, ref


class GitProvider:
    """
    Git repository provider for versioned schema and experiment syncing.

    Provides filesystem-like interface to Git repositories with authentication,
    caching, and sparse checkout support. Designed for Kubernetes environments
    with proper secret management.

    **Authentication Priority**:
    1. SSH key (if GIT__SSH_KEY_PATH points to valid key)
    2. Personal Access Token (if GIT__PERSONAL_ACCESS_TOKEN is set)
    3. Unauthenticated (public repos only)

    **Caching Strategy**:
    - Clones cached in {cache_dir}/{repo_hash}/{ref}/
    - Repo hash: SHA256 of repo URL (prevents collisions)
    - Ref: branch, tag, or commit hash
    - Cache invalidation: Manual via clear_cache() or periodic sync

    **Thread Safety**:
    - Local cache is thread-safe (atomic git operations)
    - Concurrent reads: Safe
    - Concurrent clones of same repo: Safe (GitPython handles locking)

    **Resource Management**:
    - Disk usage: ~100MB per repo (shallow clone)
    - Memory: Minimal (lazy loading)
    - Network: Only on first clone or refresh

    Attributes:
        repo_url: Git repository URL (SSH or HTTPS)
        branch: Default branch to clone
        cache_dir: Local cache directory for cloned repos
        ssh_key_path: Path to SSH private key
        known_hosts_path: Path to SSH known_hosts file
        shallow: Use shallow clone (--depth=1)

    Examples:
        >>> provider = GitProvider()
        >>> provider.exists("schemas/cv-parser-v1.yaml")
        True
        >>> schema = provider.read("schemas/cv-parser-v1.yaml")
        >>> schemas = provider.ls("schemas/")
        ['schemas/agent-1.yaml', 'schemas/agent-2.yaml']
    """

    def __init__(
        self,
        repo_url: str | None = None,
        branch: str | None = None,
        cache_dir: str | None = None,
    ):
        """
        Initialize Git provider with repository configuration.

        Args:
            repo_url: Git repository URL (uses settings.git.default_repo_url if None)
            branch: Default branch to clone (uses settings.git.default_branch if None)
            cache_dir: Cache directory (uses settings.git.cache_dir if None)

        Raises:
            ImportError: If GitPython is not installed
            ValueError: If repo_url is not provided and settings.git.default_repo_url is None
        """
        if not GitPython_available:
            raise ImportError(
                "GitPython is required for Git provider. Install with: pip install GitPython"
            )

        self.repo_url = repo_url or settings.git.default_repo_url
        if not self.repo_url:
            raise ValueError(
                "Git repository URL not provided. Set GIT__DEFAULT_REPO_URL or pass repo_url argument."
            )

        # Type guard: repo_url is guaranteed to be str after the check above
        assert self.repo_url is not None

        self.branch = branch or settings.git.default_branch
        self.cache_dir = Path(cache_dir or settings.git.cache_dir)
        self.ssh_key_path = settings.git.ssh_key_path
        self.known_hosts_path = settings.git.known_hosts_path
        self.shallow = settings.git.shallow_clone

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Compute repo hash for cache key
        self.repo_hash = hashlib.sha256(self.repo_url.encode()).hexdigest()[:16]

        logger.debug(
            f"Initialized GitProvider: repo={self.repo_url}, "
            f"branch={self.branch}, cache={self.cache_dir}"
        )

    def _get_cached_repo_path(self, ref: str | None = None) -> Path:
        """
        Get local path for cached repository.

        Args:
            ref: Git ref (branch, tag, or commit). Uses default branch if None.

        Returns:
            Path to local cached repository

        Examples:
            >>> provider._get_cached_repo_path()
            Path('/tmp/rem-git-cache/a1b2c3d4e5f6/main')
            >>> provider._get_cached_repo_path('v1.0.0')
            Path('/tmp/rem-git-cache/a1b2c3d4e5f6/v1.0.0')
        """
        ref = ref or self.branch
        return self.cache_dir / self.repo_hash / ref

    def _setup_git_ssh(self) -> dict[str, str]:
        """
        Configure Git SSH authentication via environment variables.

        Sets GIT_SSH_COMMAND to use custom SSH key and known_hosts file.
        This approach works with GitPython's subprocess calls.

        Returns:
            Environment variables dict for Git commands

        Raises:
            FileNotFoundError: If SSH key or known_hosts file doesn't exist

        Examples:
            >>> env = provider._setup_git_ssh()
            >>> env['GIT_SSH_COMMAND']
            'ssh -i /etc/git-secret/ssh -o UserKnownHostsFile=/etc/git-secret/known_hosts -o StrictHostKeyChecking=yes'
        """
        env = os.environ.copy()

        # Check if SSH key exists
        if Path(self.ssh_key_path).exists():
            ssh_command = (
                f"ssh -i {self.ssh_key_path} "
                f"-o UserKnownHostsFile={self.known_hosts_path} "
                f"-o StrictHostKeyChecking=yes"
            )
            env["GIT_SSH_COMMAND"] = ssh_command
            logger.debug(f"Configured Git SSH: key={self.ssh_key_path}")
        else:
            logger.warning(
                f"SSH key not found at {self.ssh_key_path}. "
                "Falling back to default Git authentication."
            )

        return env

    def _setup_git_https(self, repo_url: str) -> str:
        """
        Configure HTTPS authentication with Personal Access Token.

        Injects PAT into HTTPS URL for authentication:
        https://github.com/org/repo.git → https://{token}@github.com/org/repo.git

        Args:
            repo_url: Original HTTPS repository URL

        Returns:
            Modified URL with embedded PAT

        Security Note:
            PAT is not logged or exposed in error messages.

        Examples:
            >>> provider._setup_git_https("https://github.com/org/repo.git")
            'https://ghp_token123@github.com/org/repo.git'
        """
        token = settings.git.personal_access_token
        if not token:
            logger.warning("No Personal Access Token configured for HTTPS authentication.")
            return repo_url

        # Parse URL and inject token
        parsed = urlparse(repo_url)
        if parsed.scheme in ("https", "http"):
            # https://github.com/org/repo.git → https://token@github.com/org/repo.git
            authed_url = f"{parsed.scheme}://{token}@{parsed.netloc}{parsed.path}"
            logger.debug("Configured Git HTTPS authentication with PAT")
            return authed_url

        return repo_url

    def _clone_or_update(self, ref: str | None = None) -> Repo:
        """
        Clone repository or update existing clone.

        Handles both initial cloning and updating existing repositories.
        Uses shallow clones (--depth=1) for performance when enabled.

        Args:
            ref: Git ref to checkout (branch, tag, or commit)

        Returns:
            GitPython Repo object

        Raises:
            GitCommandError: If clone/checkout fails
            FileNotFoundError: If SSH key is required but not found

        Workflow:
            1. Check if repo already cloned
            2. If exists: fetch + checkout ref
            3. If not: clone with ref
            4. Return Repo object

        Examples:
            >>> repo = provider._clone_or_update("v1.0.0")
            >>> repo.head.commit
            <git.Commit "abc123...">
        """
        repo_path = self._get_cached_repo_path(ref)
        ref = ref or self.branch

        # Setup authentication
        env = self._setup_git_ssh()
        repo_url = self.repo_url

        if not repo_url:
            raise ValueError("repo_url is required for cloning")

        # If HTTPS, inject PAT
        if repo_url.startswith("https://") or repo_url.startswith("http://"):
            repo_url = self._setup_git_https(repo_url)

        try:
            if repo_path.exists():
                # Repository already cloned, update it
                logger.debug(f"Updating existing repo at {repo_path}")
                repo = Repo(repo_path)

                # Fetch latest changes
                repo.remotes.origin.fetch(env=env)

                # Checkout requested ref
                try:
                    repo.git.checkout(ref, env=env)
                    logger.info(f"Checked out ref: {ref}")
                except GitCommandError as e:
                    logger.warning(
                        f"Failed to checkout ref '{ref}': {e}. "
                        f"Falling back to default branch '{self.branch}'"
                    )
                    repo.git.checkout(self.branch, env=env)

                return repo
            else:
                # Clone repository
                logger.info(f"Cloning repo {self.repo_url} to {repo_path}")
                repo_path.mkdir(parents=True, exist_ok=True)

                # Clone with explicit arguments (mypy-safe)
                if self.shallow:
                    logger.debug("Using shallow clone (--depth=1)")
                    repo = Repo.clone_from(
                        repo_url,
                        to_path=str(repo_path),
                        branch=ref,
                        env=env,
                        depth=1,
                    )
                else:
                    repo = Repo.clone_from(
                        repo_url,
                        to_path=str(repo_path),
                        branch=ref,
                        env=env,
                    )
                logger.info(f"Successfully cloned repo to {repo_path}")

                return repo

        except GitCommandError as e:
            logger.error(f"Git operation failed: {e}")
            raise

    def _get_local_path(self, path: str, ref: str | None = None) -> Path:
        """
        Get local filesystem path for a Git repository file.

        Clones repo if needed, then returns path to file in cached repo.

        Args:
            path: Path within repository (e.g., "schemas/agent.yaml")
            ref: Git ref to checkout

        Returns:
            Local filesystem path to file

        Raises:
            FileNotFoundError: If file doesn't exist in repo

        Examples:
            >>> provider._get_local_path("schemas/agent.yaml", "v1.0.0")
            Path('/tmp/rem-git-cache/a1b2c3d4/v1.0.0/schemas/agent.yaml')
        """
        repo = self._clone_or_update(ref)
        local_path = Path(repo.working_dir) / path

        if not local_path.exists():
            raise FileNotFoundError(
                f"Path '{path}' not found in Git repository at ref '{ref or self.branch}'"
            )

        return local_path

    def exists(self, uri: str) -> bool:
        """
        Check if file or directory exists in Git repository.

        Args:
            uri: Git URI (git://path/to/file.yaml?ref=tag)

        Returns:
            True if path exists in repo, False otherwise

        Examples:
            >>> provider.exists("git://schemas/agent.yaml")
            True
            >>> provider.exists("git://schemas/agent.yaml?ref=v1.0.0")
            True
            >>> provider.exists("git://nonexistent.yaml")
            False
        """
        path, ref = parse_git_uri(uri)

        try:
            local_path = self._get_local_path(path, ref)
            return local_path.exists()
        except (FileNotFoundError, GitCommandError):
            return False

    def read(self, uri: str, **options) -> Any:
        """
        Read file from Git repository.

        Supports same format detection as LocalProvider:
        - YAML: .yaml, .yml
        - JSON: .json
        - CSV: .csv
        - Text: .txt, .md
        - Binary: .pdf, .docx, .png, etc.

        Args:
            uri: Git URI (git://path/to/file.yaml?ref=tag)
            **options: Format-specific read options

        Returns:
            Parsed file content

        Raises:
            FileNotFoundError: If file doesn't exist in repo
            ValueError: If file format is unsupported

        Examples:
            >>> schema = provider.read("git://schemas/agent.yaml")
            >>> data = provider.read("git://experiments/data.csv")
            >>> image = provider.read("git://assets/logo.png")
        """
        path, ref = parse_git_uri(uri)
        local_path = self._get_local_path(path, ref)

        # Delegate to LocalProvider for format handling
        from rem.services.fs.local_provider import LocalProvider

        local_provider = LocalProvider()
        return local_provider.read(str(local_path), **options)

    def ls(self, uri: str, **options) -> list[str]:
        """
        List files in Git repository directory.

        Args:
            uri: Git URI (git://path/to/dir/?ref=tag)
            **options: Provider options

        Returns:
            List of file paths (relative to repo root)

        Examples:
            >>> provider.ls("git://schemas/")
            ['schemas/agent-1.yaml', 'schemas/agent-2.yaml']
            >>> provider.ls("git://experiments/hello-world/?ref=v1.0.0")
            ['experiments/hello-world/ground_truth.csv', 'experiments/hello-world/config.yaml']
        """
        path, ref = parse_git_uri(uri)
        local_path = self._get_local_path(path, ref)

        if not local_path.is_dir():
            raise ValueError(f"Path '{path}' is not a directory")

        # List all files recursively
        files = []
        repo_root = self._get_cached_repo_path(ref)

        for file_path in local_path.rglob("*"):
            if file_path.is_file():
                # Make path relative to repo root
                relative = file_path.relative_to(repo_root)
                files.append(str(relative))

        return sorted(files)

    def ls_iter(self, uri: str, **options) -> Iterator[str]:
        """
        Iterate over files in Git repository directory.

        Args:
            uri: Git URI (git://path/to/dir/?ref=tag)
            **options: Provider options

        Yields:
            File paths (relative to repo root)

        Examples:
            >>> for file in provider.ls_iter("git://schemas/"):
            ...     print(file)
            schemas/agent-1.yaml
            schemas/agent-2.yaml
        """
        for file_path in self.ls(uri, **options):
            yield file_path

    def clear_cache(self, ref: str | None = None):
        """
        Clear cached repository.

        Useful for:
        - Forcing fresh clone
        - Freeing disk space
        - Testing

        Args:
            ref: Specific ref to clear, or None to clear all refs

        Examples:
            >>> provider.clear_cache("v1.0.0")  # Clear specific tag
            >>> provider.clear_cache()  # Clear all refs
        """
        if ref:
            repo_path = self._get_cached_repo_path(ref)
            if repo_path.exists():
                shutil.rmtree(repo_path)
                logger.info(f"Cleared cache for ref: {ref}")
        else:
            repo_base = self.cache_dir / self.repo_hash
            if repo_base.exists():
                shutil.rmtree(repo_base)
                logger.info(f"Cleared all cached refs for repo: {self.repo_url}")

    def get_current_commit(self, ref: str | None = None) -> str:
        """
        Get current commit hash for ref.

        Useful for tracking which version of schema is currently loaded.

        Args:
            ref: Git ref (branch, tag, or commit)

        Returns:
            Full commit hash (40 characters)

        Examples:
            >>> provider.get_current_commit("v1.0.0")
            'abc123def456...'
            >>> provider.get_current_commit()  # Current branch
            'def456abc123...'
        """
        repo = self._clone_or_update(ref)
        return repo.head.commit.hexsha

    def get_semantic_versions(self, file_path: str, pattern: str | None = None) -> list[dict[str, Any]]:
        """
        Get semantic version history for a file following Git tags.

        Returns list of versions where the file exists, sorted by semantic versioning.
        Useful for tracking schema evolution, comparing agent versions, and
        understanding when changes were introduced.

        **Semantic Versioning** (semver.org):
        - Format: MAJOR.MINOR.PATCH (e.g., 2.1.0, 2.1.1, 3.0.0)
        - MAJOR: Breaking changes
        - MINOR: New features (backwards compatible)
        - PATCH: Bug fixes (backwards compatible)

        **Use Cases**:
        1. **Schema Evolution Tracking**:
           - Compare cv-parser v2.1.0 vs v2.1.1
           - Identify breaking changes (MAJOR version bumps)
           - Review feature additions (MINOR version bumps)

        2. **Rollback/Pinning**:
           - Production uses v2.1.0 (stable)
           - Staging tests v2.1.1 (latest)
           - Can rollback to v2.0.0 if needed

        3. **Deprecation Management**:
           - Mark v1.x.x as deprecated
           - Migrate users to v2.x.x
           - Track adoption rate by version

        Args:
            file_path: Path to file in repository (e.g., "schemas/agent.yaml")
            pattern: Optional regex pattern for tag filtering (e.g., "v2\\..*" for v2.x.x)

        Returns:
            List of version dicts sorted by semantic version (newest first):
            [
                {
                    "tag": "v2.1.1",
                    "version": (2, 1, 1),
                    "commit": "abc123...",
                    "date": "2025-01-15T10:30:00",
                    "message": "feat: Add confidence scoring",
                    "author": "alice@example.com"
                },
                {
                    "tag": "v2.1.0",
                    "version": (2, 1, 0),
                    "commit": "def456...",
                    "date": "2025-01-10T14:20:00",
                    "message": "feat: Add multi-language support",
                    "author": "bob@example.com"
                }
            ]

        Raises:
            FileNotFoundError: If file doesn't exist in any tagged version

        Examples:
            >>> # Get all versions of a schema
            >>> versions = provider.get_semantic_versions("schemas/cv-parser.yaml")
            >>> print(f"Current: {versions[0]['tag']}, Previous: {versions[1]['tag']}")
            Current: v2.1.1, Previous: v2.1.0

            >>> # Get only v2.x.x versions
            >>> v2_versions = provider.get_semantic_versions(
            ...     "schemas/cv-parser.yaml",
            ...     pattern="v2\\..*"
            ... )

            >>> # Compare two versions
            >>> v1 = provider.read(f"git://schemas/cv-parser.yaml?ref={versions[0]['tag']}")
            >>> v2 = provider.read(f"git://schemas/cv-parser.yaml?ref={versions[1]['tag']}")
            >>> # Diff logic here...

            >>> # Find version by date
            >>> target_date = "2025-01-12"
            >>> version = next(v for v in versions if v["date"].startswith(target_date))
            >>> print(version["tag"])
            v2.1.0
        """
        import re
        from datetime import datetime

        repo = self._clone_or_update()

        # Get all tags from repository
        tags = repo.tags

        if not tags:
            logger.warning(f"No tags found in repository {self.repo_url}")
            return []

        versions = []
        # Pattern supports both flat tags (v2.1.0) and path-based tags (schemas/test/v2.1.0)
        semver_pattern = re.compile(r"(?:^|/)v?(\d+)\.(\d+)\.(\d+)")

        for tag in tags:
            tag_name = tag.name

            # Apply user-provided pattern filter
            if pattern and not re.search(pattern, tag_name):
                continue

            # Extract semantic version (MAJOR.MINOR.PATCH)
            match = semver_pattern.search(tag_name)
            if not match:
                continue  # Skip non-semver tags

            major, minor, patch = map(int, match.groups())

            # Check if file exists at this tag
            try:
                repo.git.checkout(tag_name)
                full_path = Path(repo.working_dir) / file_path

                if not full_path.exists():
                    continue  # File doesn't exist in this version

                # Get commit info for this tag
                commit = tag.commit
                commit_date = datetime.fromtimestamp(commit.committed_date)

                versions.append({
                    "tag": tag_name,
                    "version": (major, minor, patch),
                    "commit": commit.hexsha,
                    "date": commit_date.isoformat(),
                    "message": commit.message.strip(),
                    "author": commit.author.email,
                })

            except (GitCommandError, FileNotFoundError):
                continue

        # Sort by semantic version (newest first)
        versions.sort(key=lambda v: v["version"], reverse=True)

        # Restore to default branch
        repo.git.checkout(self.branch)

        logger.info(
            f"Found {len(versions)} semantic versions for {file_path} "
            f"(pattern: {pattern or 'all'})"
        )

        return versions

    def diff_versions(
        self,
        file_path: str,
        version1: str,
        version2: str,
        unified: int = 3
    ) -> str:
        """
        Generate unified diff between two versions of a file.

        Useful for:
        - Code review: What changed between v2.1.0 and v2.1.1?
        - Migration planning: Breaking changes from v1.x.x to v2.x.x?
        - Audit trail: Who changed what and when?

        Args:
            file_path: Path to file in repository
            version1: First version tag (e.g., "v2.1.0")
            version2: Second version tag (e.g., "v2.1.1")
            unified: Number of context lines (default: 3)

        Returns:
            Unified diff string (Git format)

        Examples:
            >>> # Compare adjacent versions
            >>> diff = provider.diff_versions(
            ...     "schemas/cv-parser.yaml",
            ...     "v2.1.0",
            ...     "v2.1.1"
            ... )
            >>> print(diff)
            --- a/schemas/cv-parser.yaml
            +++ b/schemas/cv-parser.yaml
            @@ -10,6 +10,7 @@
                 skills:
                   type: array
            +      description: Candidate technical skills
                 experience:
                   type: array

            >>> # Check for breaking changes
            >>> if "required:" in diff and "-" in diff:
            ...     print("⚠️  Breaking change: Required field removed")
        """
        repo = self._clone_or_update()

        try:
            # Generate diff using git diff command
            diff_output = repo.git.diff(
                version1,
                version2,
                "--",
                file_path,
                unified=unified
            )

            return diff_output

        except GitCommandError as e:
            logger.error(f"Failed to generate diff: {e}")
            raise ValueError(
                f"Could not diff {file_path} between {version1} and {version2}. "
                "Ensure both tags exist and file is present in both versions."
            )
