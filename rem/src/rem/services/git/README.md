# Git Provider for Versioned Schema & Experiment Syncing

REM's Git provider enables syncing of agent schemas, evaluators, and experiments from Git repositories with full semantic versioning support. Designed for Kubernetes cluster environments with proper secret management.

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Authentication](#authentication)
- [URI Format](#uri-format)
- [Semantic Versioning](#semantic-versioning)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Use Cases](#use-cases)
- [API Reference](#api-reference)
- [Security Best Practices](#security-best-practices)
- [Performance & Caching](#performance--caching)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

### Installation

```bash
# Add GitPython dependency
cd rem
uv add GitPython

# Or with pip
pip install GitPython
```

### Configuration

```bash
# Enable Git provider
export GIT__ENABLED=true
export GIT__DEFAULT_REPO_URL="ssh://git@github.com/my-org/my-repo.git"

# Optional: Configure cache and SSH paths
export GIT__CACHE_DIR="/tmp/rem-git-cache"
export GIT__SSH_KEY_PATH="/etc/git-secret/ssh"
export GIT__KNOWN_HOSTS_PATH="/etc/git-secret/known_hosts"
```

### Basic Usage

```python
from rem.services.fs import FS
from rem.services.git_service import GitService

# Filesystem interface (low-level)
fs = FS()
schema = fs.read("git://schemas/cv-parser.yaml?ref=v2.1.0")
schemas = fs.ls("git://schemas/")

# GitService interface (high-level, recommended)
git_svc = GitService()

# List schema versions
versions = git_svc.list_schema_versions("cv-parser")
print(f"Latest: {versions[0]['tag']}")  # v2.1.1

# Load specific version
schema = git_svc.load_schema("cv-parser", version="v2.1.0")

# Compare versions
diff = git_svc.compare_schemas("cv-parser", "v2.0.0", "v2.1.0")
print(diff)

# Check for breaking changes
if git_svc.has_breaking_changes("cv-parser", "v2.0.0", "v2.1.0"):
    print("⚠️  Manual migration required")
```

---

## Architecture

### Component Overview

```
GitService (High-level semantic operations)
    ↓
FS.git_provider (Thin wrapper for FS interface)
    ↓
GitProvider (Git operations with caching)
    ↓
GitPython (Git CLI wrapper)
    ↓
Git CLI (System git command)
```

### Path Conventions

```
Repository Structure:
  repo/
  ├── schemas/                      # Agent schemas
  │   ├── cv-parser.yaml           # git://schemas/cv-parser.yaml
  │   ├── contract-analyzer.yaml
  │   └── evaluators/              # Evaluator schemas
  │       ├── cv-correctness.yaml
  │       └── contract-risk.yaml
  └── experiments/                  # Evaluation experiments
      ├── hello-world/
      │   ├── config.yaml
      │   └── ground_truth.csv
      └── cv-parser-test/
          ├── config.yaml
          └── resumes/
```

### Caching Strategy

```
Local Cache Structure:
  /tmp/rem-git-cache/
  └── {repo_hash}/              # SHA256 hash of repo URL
      ├── main/                 # Default branch
      │   ├── schemas/
      │   └── experiments/
      ├── v2.1.0/              # Tag
      │   └── schemas/
      └── v2.1.1/              # Tag
          └── schemas/

Cache Invalidation:
- Manual: git_svc.sync() or provider.clear_cache()
- Automatic: Configurable sync interval (default: 5 minutes)
- Per-ref: Cache cleared per tag/branch
```

---

## Authentication

### Method 1: SSH Keys (Recommended for Production)

**Setup**:
```bash
# Generate SSH key (if needed)
ssh-keygen -t ed25519 -C "rem-cluster@example.com" -f ~/.ssh/rem_deploy_key

# Add public key as deploy key in GitHub/GitLab
# Settings → Deploy keys → Add deploy key
# ✓ Read-only access
# ✗ Write access (not needed)

# Configure REM
export GIT__SSH_KEY_PATH="$HOME/.ssh/rem_deploy_key"
export GIT__KNOWN_HOSTS_PATH="$HOME/.ssh/known_hosts"
```

**Advantages**:
- ✅ No rate limits
- ✅ Full Git protocol support
- ✅ Works with private repos
- ✅ More secure (no token in environment)

**Known Hosts Setup**:
```bash
# Add GitHub to known_hosts
ssh-keyscan github.com >> ~/.ssh/known_hosts

# Add GitLab to known_hosts
ssh-keyscan gitlab.com >> ~/.ssh/known_hosts

# Add self-hosted Git server
ssh-keyscan git.example.com >> ~/.ssh/known_hosts
```

### Method 2: HTTPS with Personal Access Token

**Setup**:
```bash
# Create PAT in GitHub/GitLab
# GitHub: Settings → Developer settings → Personal access tokens → Fine-grained tokens
# Permissions: Contents (read-only)

export GIT__PERSONAL_ACCESS_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"
export GIT__DEFAULT_REPO_URL="https://github.com/my-org/my-repo.git"
```

**Rate Limits**:
- GitHub: 5,000 API requests/hour per authenticated user
- GitLab: 2,000 API requests/hour per user
- Bitbucket: 1,000 API requests/hour per user

**Advantages**:
- ✅ Easier local development setup
- ✅ Works with corporate proxies
- ✅ Fine-grained permissions (GitHub)

**Disadvantages**:
- ❌ Rate limits apply
- ❌ Token in environment variable
- ❌ Token rotation required

---

## URI Format

### Syntax

```
git://{path}[?ref={version}]

Where:
- path: Path within repository (e.g., "schemas/cv-parser.yaml")
- ref: Optional Git reference (branch, tag, or commit hash)
```

### Examples

```python
# Read from default branch (main)
fs.read("git://schemas/cv-parser.yaml")

# Read from specific tag
fs.read("git://schemas/cv-parser.yaml?ref=v2.1.0")

# Read from branch
fs.read("git://schemas/cv-parser.yaml?ref=feature-branch")

# Read from commit hash
fs.read("git://schemas/cv-parser.yaml?ref=abc123def456")

# List directory
fs.ls("git://schemas/")
fs.ls("git://experiments/hello-world/?ref=v1.0.0")

# Check existence
fs.exists("git://schemas/cv-parser.yaml?ref=v2.1.0")
```

---

## Semantic Versioning

### Version Tracking

REM follows [Semantic Versioning 2.0.0](https://semver.org/):

```
MAJOR.MINOR.PATCH

Examples:
- v2.1.0 → v2.1.1: PATCH (bug fix, backwards compatible)
- v2.1.1 → v2.2.0: MINOR (new feature, backwards compatible)
- v2.2.0 → v3.0.0: MAJOR (breaking change, not backwards compatible)
```

### Get Version History

```python
from rem.services.git_service import GitService

git_svc = GitService()

# Get all versions
versions = git_svc.list_schema_versions("cv-parser")

for v in versions:
    print(f"{v['tag']}: {v['message']} by {v['author']} on {v['date']}")

# Output:
# v2.1.1: feat: Add confidence scoring by alice@example.com on 2025-01-15T10:30:00
# v2.1.0: feat: Add multi-language support by bob@example.com on 2025-01-10T14:20:00
# v2.0.0: feat!: Redesign output schema by alice@example.com on 2025-01-05T09:00:00
```

### Filter by Version Pattern

```python
# Get only v2.x.x versions
v2_versions = git_svc.list_schema_versions("cv-parser", pattern="v2\\..*")

# Get only v2.1.x versions
v2_1_versions = git_svc.list_schema_versions("cv-parser", pattern="v2\\.1\\..*")
```

### Compare Versions

```python
# Get diff between versions
diff = git_svc.compare_schemas("cv-parser", "v2.1.0", "v2.1.1")
print(diff)

# Output:
# --- a/schemas/cv-parser.yaml
# +++ b/schemas/cv-parser.yaml
# @@ -10,6 +10,8 @@
#      skills:
#        type: array
# +      items:
# +        type: string
```

### Breaking Change Detection

```python
# Check for breaking changes
has_breaking = git_svc.has_breaking_changes("cv-parser", "v2.1.0", "v3.0.0")

if has_breaking:
    print("⚠️  Breaking changes detected!")
    print("Manual migration required.")

    # Show diff
    diff = git_svc.compare_schemas("cv-parser", "v2.1.0", "v3.0.0")
    print(diff)
```

---

## Kubernetes Deployment

### Secret Creation

```bash
# Create Kubernetes Secret with SSH key
kubectl create secret generic git-creds \
  --from-file=ssh=$HOME/.ssh/rem_deploy_key \
  --from-file=known_hosts=$HOME/.ssh/known_hosts \
  --namespace rem-app

# Verify secret
kubectl get secret git-creds -n rem-app -o yaml
```

### Deployment YAML

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rem-api
  namespace: rem-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rem-api
  template:
    metadata:
      labels:
        app: rem-api
    spec:
      # Security context for SSH key permissions
      securityContext:
        fsGroup: 65533  # git user group

      volumes:
        # Mount Git credentials from Secret
        - name: git-secret
          secret:
            secretName: git-creds
            defaultMode: 0400  # Read-only for owner

      containers:
        - name: rem-api
          image: percolationlabs/rem:latest

          env:
            # Enable Git provider
            - name: GIT__ENABLED
              value: "true"
            - name: GIT__DEFAULT_REPO_URL
              value: "ssh://git@github.com/my-org/my-repo.git"
            - name: GIT__SSH_KEY_PATH
              value: "/etc/git-secret/ssh"
            - name: GIT__KNOWN_HOSTS_PATH
              value: "/etc/git-secret/known_hosts"
            - name: GIT__CACHE_DIR
              value: "/app/git-cache"
            - name: GIT__SHALLOW_CLONE
              value: "true"

          volumeMounts:
            # Mount Git credentials
            - name: git-secret
              mountPath: /etc/git-secret
              readOnly: true

          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
```

### Git-Sync Sidecar Pattern (Alternative)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rem-api-with-git-sync
spec:
  template:
    spec:
      volumes:
        - name: git-secret
          secret:
            secretName: git-creds
        - name: git-repo
          emptyDir: {}

      containers:
        # Main application container
        - name: rem-api
          image: percolationlabs/rem:latest
          env:
            - name: GIT__ENABLED
              value: "false"  # Use git-sync instead
          volumeMounts:
            - name: git-repo
              mountPath: /app/git-repo
              readOnly: true

        # Git-sync sidecar (keeps repo in sync)
        - name: git-sync
          image: registry.k8s.io/git-sync/git-sync:v4.0.0
          env:
            - name: GITSYNC_REPO
              value: "ssh://git@github.com/my-org/my-repo.git"
            - name: GITSYNC_ROOT
              value: "/git"
            - name: GITSYNC_DEST
              value: "repo"
            - name: GITSYNC_PERIOD
              value: "30s"  # Sync every 30 seconds
            - name: GITSYNC_SSH_KEY_FILE
              value: "/etc/git-secret/ssh"
          volumeMounts:
            - name: git-repo
              mountPath: /git
            - name: git-secret
              mountPath: /etc/git-secret
              readOnly: true
```

---

## Use Cases

### 1. Schema Versioning

**Problem**: Need to track agent schema evolution and compare versions.

```python
from rem.services.git_service import GitService

git_svc = GitService()

# Production uses v2.1.0
prod_schema = git_svc.load_schema("cv-parser", version="v2.1.0")

# Staging tests v2.1.1
staging_schema = git_svc.load_schema("cv-parser", version="v2.1.1")

# Compare to see what changed
diff = git_svc.compare_schemas("cv-parser", "v2.1.0", "v2.1.1")
print("Changes in staging:")
print(diff)
```

### 2. Reproducible Evaluations

**Problem**: Need to ensure evaluations use exact same schema version.

```python
from rem.services.git_service import GitService
from rem.agentic.factory import create_pydantic_ai_agent

git_svc = GitService()

# Load pinned versions
schema = git_svc.load_schema("cv-parser", version="v2.1.0")
experiment = git_svc.load_experiment("cv-eval", version="v1.0.0")

# Create agent from versioned schema
agent = create_pydantic_ai_agent(schema)

# Log exact versions for reproducibility
metadata = {
    "schema_version": "v2.1.0",
    "schema_commit": git_svc.get_commit("schemas/cv-parser.yaml", "v2.1.0"),
    "experiment_version": "v1.0.0",
    "timestamp": datetime.now().isoformat()
}

# Run evaluation
result = await agent.run(experiment["test_input"])
```

### 3. Multi-Tenant Schema Management

**Problem**: Different tenants need different schema versions.

```python
from rem.services.git_service import GitService

git_svc = GitService()

# Tenant configuration
TENANT_SCHEMA_VERSIONS = {
    "acme-corp": "v2.0.0",      # Conservative, stable
    "beta-corp": "v2.1.0",       # Early adopter
    "enterprise-corp": "v1.5.0", # Custom version
}

def get_tenant_schema(tenant_id: str):
    version = TENANT_SCHEMA_VERSIONS.get(tenant_id, "v2.1.0")  # Default latest
    return git_svc.load_schema("cv-parser", version=version)

# Load tenant-specific schema
acme_schema = get_tenant_schema("acme-corp")  # Gets v2.0.0
beta_schema = get_tenant_schema("beta-corp")  # Gets v2.1.0
```

### 4. Migration Planning

**Problem**: Need to understand impact of upgrading to new schema version.

```python
from rem.services.git_service import GitService

git_svc = GitService()

current_version = "v2.1.0"
target_version = "v3.0.0"

# Check for breaking changes
if git_svc.has_breaking_changes("cv-parser", current_version, target_version):
    print(f"⚠️  Breaking changes in {target_version}")

    # Get detailed diff
    diff = git_svc.compare_schemas("cv-parser", current_version, target_version)

    # Analyze diff for specific patterns
    if "- required:" in diff:
        print("❌ Required fields removed")
    if "- type:" in diff:
        print("❌ Field types changed")

    print("\nFull diff:")
    print(diff)

    # Create migration plan
    print("\nMigration steps:")
    print("1. Update agent to handle new schema")
    print("2. Test with sample data")
    print("3. Deploy to staging")
    print("4. Gradual rollout to production")
else:
    print(f"✅ No breaking changes in {target_version}")
    print("Safe to upgrade")
```

### 5. Cluster Jobs with Versioned Schemas

**Problem**: Kubernetes jobs need to pull specific schema versions.

```yaml
# evaluation-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: cv-parser-eval-v2-1-0
spec:
  template:
    spec:
      restartPolicy: Never
      volumes:
        - name: git-secret
          secret:
            secretName: git-creds
      containers:
        - name: eval-runner
          image: percolationlabs/rem:latest
          command: ["python", "-m", "rem.cli.eval"]
          args:
            - "run"
            - "--schema=cv-parser"
            - "--version=v2.1.0"
            - "--experiment=cv-eval"
            - "--experiment-version=v1.0.0"
          env:
            - name: GIT__ENABLED
              value: "true"
            - name: GIT__DEFAULT_REPO_URL
              value: "ssh://git@github.com/my-org/schemas.git"
          volumeMounts:
            - name: git-secret
              mountPath: /etc/git-secret
```

---

## API Reference

### GitService

High-level semantic operations.

```python
from rem.services.git_service import GitService

git_svc = GitService(
    fs=None,                    # FS instance (creates new if None)
    schemas_dir="schemas",      # Schemas directory in repo
    experiments_dir="experiments"  # Experiments directory
)
```

#### Methods

**`list_schema_versions(schema_name, pattern=None)`**
```python
versions = git_svc.list_schema_versions("cv-parser")
versions = git_svc.list_schema_versions("cv-parser", pattern="v2\\..*")

# Returns: list[dict]
# [
#     {
#         "tag": "v2.1.1",
#         "version": (2, 1, 1),
#         "commit": "abc123...",
#         "date": "2025-01-15T10:30:00",
#         "message": "feat: Add confidence",
#         "author": "alice@example.com"
#     },
#     ...
# ]
```

**`load_schema(schema_name, version=None)`**
```python
schema = git_svc.load_schema("cv-parser")  # Latest
schema = git_svc.load_schema("cv-parser", version="v2.1.0")  # Specific

# Returns: dict (parsed YAML)
```

**`compare_schemas(schema_name, version1, version2, unified=3)`**
```python
diff = git_svc.compare_schemas("cv-parser", "v2.0.0", "v2.1.0")

# Returns: str (unified diff format)
```

**`has_breaking_changes(schema_name, version1, version2)`**
```python
has_breaking = git_svc.has_breaking_changes("cv-parser", "v2.0.0", "v3.0.0")

# Returns: bool
```

**`load_experiment(experiment_name, version=None)`**
```python
exp = git_svc.load_experiment("hello-world", version="v1.0.0")

# Returns: dict (parsed YAML)
```

**`sync()`**
```python
git_svc.sync()  # Clear cache, force fresh clone

# Returns: None
```

**`get_commit(path, version)`**
```python
commit = git_svc.get_commit("schemas/cv-parser.yaml", "v2.1.0")

# Returns: str (40-character commit hash)
```

### GitProvider

Low-level Git operations (usually accessed via FS).

```python
from rem.services.fs.git_provider import GitProvider

provider = GitProvider(
    repo_url="ssh://git@github.com/org/repo.git",
    branch="main",
    cache_dir="/tmp/rem-git-cache"
)
```

#### Methods

**`exists(uri)`**
```python
exists = provider.exists("git://schemas/cv-parser.yaml?ref=v2.1.0")
# Returns: bool
```

**`read(uri, **options)`**
```python
content = provider.read("git://schemas/cv-parser.yaml?ref=v2.1.0")
# Returns: Any (format-specific)
```

**`ls(uri, **options)`**
```python
files = provider.ls("git://schemas/?ref=v2.1.0")
# Returns: list[str]
```

**`get_semantic_versions(file_path, pattern=None)`**
```python
versions = provider.get_semantic_versions("schemas/cv-parser.yaml")
versions = provider.get_semantic_versions("schemas/cv-parser.yaml", pattern="v2\\..*")
# Returns: list[dict]
```

**`diff_versions(file_path, version1, version2, unified=3)`**
```python
diff = provider.diff_versions("schemas/cv-parser.yaml", "v2.0.0", "v2.1.0")
# Returns: str
```

**`clear_cache(ref=None)`**
```python
provider.clear_cache("v2.1.0")  # Clear specific version
provider.clear_cache()  # Clear all versions
# Returns: None
```

**`get_current_commit(ref=None)`**
```python
commit = provider.get_current_commit("v2.1.0")
# Returns: str (40-character hash)
```

---

## Security Best Practices

### 1. Use Read-Only Deploy Keys

```bash
# GitHub: Settings → Deploy keys
# ✓ Read access
# ✗ Write access

# GitLab: Settings → Repository → Deploy keys
# ✓ Read repository
# ✗ Write repository
```

### 2. Store Secrets in Kubernetes Secrets

```bash
# ✅ GOOD: Kubernetes Secret
kubectl create secret generic git-creds \
  --from-file=ssh=$HOME/.ssh/deploy_key

# ❌ BAD: Environment variable
export GIT__SSH_KEY="-----BEGIN OPENSSH PRIVATE KEY-----\n..."
```

### 3. Enable Known Hosts Verification

```bash
# Generate known_hosts
ssh-keyscan github.com >> ~/.ssh/known_hosts

# Configure REM
export GIT__KNOWN_HOSTS_PATH="$HOME/.ssh/known_hosts"

# This prevents MITM attacks
```

### 4. Rotate PATs Regularly

```bash
# GitHub: Set expiration to 90 days
# GitLab: Set expiration to 90 days

# Rotate before expiration
# Update Kubernetes Secret
kubectl create secret generic git-creds \
  --from-literal=token=ghp_NEW_TOKEN \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 5. Use Least Privilege

```bash
# GitHub Fine-grained PAT:
# Permissions → Contents → Read-only ✓
# Permissions → Contents → Read and write ✗

# SSH Deploy Key:
# Read access ✓
# Write access ✗
```

### 6. Audit Access

```bash
# Monitor Git access logs
kubectl logs -l app=rem-api | grep "Git"

# GitHub/GitLab audit logs
# Settings → Security → Audit log
```

---

## Performance & Caching

### Cache Hit Rates

```
Typical Performance:
- First clone: 1-10 seconds (depends on repo size)
- Cached read: <10ms (local filesystem)
- Shallow clone: 90% size reduction

Cache Efficiency:
- Same version, multiple reads: 100% cache hit
- Different versions: Separate cache entries
- Branch updates: Manual sync required
```

### Shallow Clones

```python
# Enable shallow clones (default)
export GIT__SHALLOW_CLONE=true

# Benefits:
# - Faster clone (only latest commit)
# - Less disk space (no history)
# - Recommended for production

# Disable for full history
export GIT__SHALLOW_CLONE=false
```

### Cache Management

```python
from rem.services.git_service import GitService

git_svc = GitService()

# Manual sync (clear cache, pull latest)
git_svc.sync()

# Periodic sync (configure interval)
export GIT__SYNC_INTERVAL=300  # 5 minutes
```

### Monitoring

```python
import os
from pathlib import Path

cache_dir = Path(os.environ.get("GIT__CACHE_DIR", "/tmp/rem-git-cache"))

# Check cache size
def get_cache_size():
    total = sum(
        f.stat().st_size
        for f in cache_dir.rglob("*")
        if f.is_file()
    )
    return total / (1024 ** 2)  # MB

print(f"Git cache size: {get_cache_size():.2f} MB")

# List cached repos
for repo_dir in cache_dir.iterdir():
    if repo_dir.is_dir():
        print(f"Repo: {repo_dir.name}")
        for ref_dir in repo_dir.iterdir():
            if ref_dir.is_dir():
                print(f"  - {ref_dir.name}")
```

---

## Troubleshooting

### SSH Key Not Found

**Error**:
```
FileNotFoundError: SSH key not found at /etc/git-secret/ssh
```

**Solution**:
```bash
# Check if secret is mounted
kubectl describe pod rem-api-xxx | grep git-secret

# Verify secret exists
kubectl get secret git-creds -n rem-app

# Check file permissions
kubectl exec rem-api-xxx -- ls -la /etc/git-secret/

# Expected:
# -r-------- 1 rem rem 464 Jan 15 10:30 ssh
# -r-------- 1 rem rem 444 Jan 15 10:30 known_hosts
```

### Authentication Failed

**Error**:
```
GitCommandError: Permission denied (publickey)
```

**Solution**:
```bash
# Test SSH key locally
ssh -i /path/to/key git@github.com

# Check deploy key in GitHub
# Settings → Deploy keys → Verify key is added

# Verify known_hosts contains host
grep github.com ~/.ssh/known_hosts

# Regenerate known_hosts if needed
ssh-keyscan github.com > ~/.ssh/known_hosts
```

### Rate Limit Exceeded (HTTPS)

**Error**:
```
API rate limit exceeded for user
```

**Solution**:
```bash
# Switch to SSH authentication
export GIT__DEFAULT_REPO_URL="ssh://git@github.com/org/repo.git"

# Or use a GitHub App token (higher limits)
export GIT__PERSONAL_ACCESS_TOKEN="ghp_..."
```

### Repo Clone Timeout

**Error**:
```
GitCommandError: timeout after 60s
```

**Solution**:
```bash
# Enable shallow clone
export GIT__SHALLOW_CLONE=true

# Or increase Git timeout
git config --global http.postBuffer 524288000

# Check network connectivity
kubectl exec rem-api-xxx -- ping github.com
```

### Cache Corruption

**Error**:
```
InvalidGitRepositoryError: /tmp/rem-git-cache/xxx is not a git repository
```

**Solution**:
```python
from rem.services.git_service import GitService

git_svc = GitService()

# Clear corrupted cache
git_svc.sync()

# Or manually delete cache
rm -rf /tmp/rem-git-cache/*
```

### File Not Found at Version

**Error**:
```
FileNotFoundError: Path 'schemas/agent.yaml' not found at ref 'v2.1.0'
```

**Solution**:
```python
from rem.services.git_service import GitService

git_svc = GitService()

# List available versions
versions = git_svc.list_schema_versions("agent")

# Check if file exists at tag
# File may have been renamed or moved
```

### Known Hosts Verification Failed

**Error**:
```
Host key verification failed
```

**Solution**:
```bash
# Add host to known_hosts
ssh-keyscan github.com >> ~/.ssh/known_hosts

# Update Kubernetes Secret
kubectl create secret generic git-creds \
  --from-file=ssh=$HOME/.ssh/deploy_key \
  --from-file=known_hosts=$HOME/.ssh/known_hosts \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart pods
kubectl rollout restart deployment/rem-api -n rem-app
```

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GIT__ENABLED` | `false` | Enable Git provider |
| `GIT__DEFAULT_REPO_URL` | `None` | Git repository URL (ssh:// or https://) |
| `GIT__DEFAULT_BRANCH` | `main` | Default branch to clone |
| `GIT__SSH_KEY_PATH` | `/etc/git-secret/ssh` | Path to SSH private key |
| `GIT__KNOWN_HOSTS_PATH` | `/etc/git-secret/known_hosts` | Path to known_hosts file |
| `GIT__PERSONAL_ACCESS_TOKEN` | `None` | PAT for HTTPS authentication |
| `GIT__CACHE_DIR` | `/tmp/rem-git-cache` | Local cache directory |
| `GIT__SHALLOW_CLONE` | `true` | Use shallow clone (--depth=1) |
| `GIT__VERIFY_SSL` | `true` | Verify SSL certificates |
| `GIT__SYNC_INTERVAL` | `300` | Sync interval in seconds |

---

## Additional Resources

- [GitPython Documentation](https://gitpython.readthedocs.io/)
- [Semantic Versioning Spec](https://semver.org/)
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [GitHub Deploy Keys](https://docs.github.com/en/developers/overview/managing-deploy-keys)
- [GitLab Deploy Keys](https://docs.gitlab.com/ee/user/project/deploy_keys/)
- [git-sync Sidecar](https://github.com/kubernetes/git-sync)

---

## Support

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review logs: `kubectl logs -l app=rem-api | grep Git`
3. Open issue: https://github.com/your-org/rem/issues
