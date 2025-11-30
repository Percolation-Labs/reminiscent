"""
Cluster management commands for deploying REM to Kubernetes.

Usage:
    rem cluster init                       # Initialize cluster config
    rem cluster generate                   # Generate all manifests (including SQL ConfigMap)
    rem cluster setup-ssm                  # Create required SSM parameters
    rem cluster validate                   # Validate deployment prerequisites
    rem cluster env check                  # Validate .env for cluster deployment
"""

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen, Request

import click
import yaml
from loguru import logger

# Default GitHub repo for manifest releases
DEFAULT_MANIFESTS_REPO = "anthropics/remstack"
DEFAULT_MANIFESTS_ASSET = "manifests.tar.gz"


def get_current_version() -> str:
    """Get current installed version of remdb."""
    try:
        from importlib.metadata import version
        return version("remdb")
    except Exception:
        return "latest"


def download_manifests(version: str, output_dir: Path, repo: str = DEFAULT_MANIFESTS_REPO) -> bool:
    """
    Download manifests tarball from GitHub releases.

    Args:
        version: Release tag (e.g., "v1.2.3" or "latest")
        output_dir: Directory to extract manifests to
        repo: GitHub repo in "owner/repo" format

    Returns:
        True if successful, False otherwise
    """
    # Construct GitHub release URL
    # For "latest", GitHub redirects to the actual latest release
    if version == "latest":
        base_url = f"https://github.com/{repo}/releases/latest/download"
    else:
        # Ensure version has 'v' prefix for GitHub tags
        if not version.startswith("v"):
            version = f"v{version}"
        base_url = f"https://github.com/{repo}/releases/download/{version}"

    url = f"{base_url}/{DEFAULT_MANIFESTS_ASSET}"

    click.echo(f"Downloading manifests from: {url}")

    try:
        # Create request with user-agent (GitHub requires it)
        request = Request(url, headers={"User-Agent": "remdb-cli"})

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

            # Download with progress indication
            with urlopen(request, timeout=60) as response:
                total_size = response.headers.get("Content-Length")
                if total_size:
                    total_size = int(total_size)
                    click.echo(f"Size: {total_size / 1024 / 1024:.1f} MB")

                # Read in chunks
                chunk_size = 8192
                downloaded = 0
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    tmp_file.write(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        pct = (downloaded / total_size) * 100
                        click.echo(f"\r  Downloading: {pct:.0f}%", nl=False)

                click.echo()  # Newline after progress

        # Extract tarball
        click.echo(f"Extracting to: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(tmp_path, "r:gz") as tar:
            # Extract all files
            tar.extractall(output_dir)

        # Clean up temp file
        tmp_path.unlink()

        click.secho("✓ Manifests downloaded successfully", fg="green")
        return True

    except HTTPError as e:
        if e.code == 404:
            click.secho(f"✗ Release not found: {version}", fg="red")
            click.echo(f"  Check available releases at: https://github.com/{repo}/releases")
        else:
            click.secho(f"✗ Download failed: HTTP {e.code}", fg="red")
        return False
    except Exception as e:
        click.secho(f"✗ Download failed: {e}", fg="red")
        return False


def get_manifests_dir() -> Path:
    """Get the manifests directory from the remstack repo."""
    # Walk up from CLI to find manifests/
    current = Path(__file__).resolve()
    for parent in current.parents:
        manifests = parent / "manifests"
        if manifests.exists():
            return manifests
    # Try relative to cwd
    cwd_manifests = Path.cwd() / "manifests"
    if cwd_manifests.exists():
        return cwd_manifests
    raise click.ClickException("Could not find manifests directory. Run from remstack root.")


def load_cluster_config(config_path: Path | None) -> dict:
    """Load cluster configuration from YAML file or defaults."""
    if config_path and config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)

    # Try default location
    manifests = get_manifests_dir()
    default_config = manifests / "cluster-config.yaml"
    if default_config.exists():
        with open(default_config) as f:
            return yaml.safe_load(f)

    # Return minimal defaults
    return {
        "project": {"name": "rem", "environment": "staging", "namespace": "rem"},
        "aws": {"region": "us-east-1", "ssmPrefix": "/rem"},
    }


@click.command()
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output path for config file (default: ./manifests/cluster-config.yaml)",
)
@click.option(
    "--manifests-dir",
    "-m",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to manifests directory (default: ./manifests)",
)
@click.option(
    "--project-name",
    default="rem",
    help="Project name prefix (default: rem)",
)
@click.option(
    "--git-repo",
    default="https://github.com/anthropics/remstack.git",
    help="Git repository URL for ArgoCD",
)
@click.option(
    "--region",
    default="us-east-1",
    help="AWS region (default: us-east-1)",
)
@click.option(
    "--manifest-version",
    default=None,
    help="Manifest release version to download (e.g., v0.5.0). Default: latest",
)
@click.option(
    "-y", "--yes",
    is_flag=True,
    help="Auto-confirm manifest download without prompting",
)
def init(
    output: Path | None,
    manifests_dir: Path | None,
    project_name: str,
    git_repo: str,
    region: str,
    manifest_version: str | None,
    yes: bool,
):
    """
    Initialize a new cluster configuration file.

    Creates a cluster-config.yaml with your project settings that can be
    used with other `rem cluster` commands.

    If manifests are not found locally, offers to download them from
    the GitHub releases matching your installed remdb version.

    Examples:
        rem cluster init
        rem cluster init --project-name myapp --git-repo https://github.com/myorg/myrepo.git
        rem cluster init -o my-cluster.yaml
        rem cluster init -y  # Auto-download manifests without prompting
        rem cluster init --manifest-version v0.5.0  # Download specific manifest version
    """
    # Determine manifests directory
    if manifests_dir is None:
        manifests_dir = Path.cwd() / "manifests"

    # Check if manifests exist
    manifests_exist = manifests_dir.exists() and (manifests_dir / "cluster-config.yaml").exists()

    if not manifests_exist:
        # Manifests not found - offer to download
        click.echo()
        click.echo(f"Manifests not found at: {manifests_dir}")
        click.echo()

        # Determine version to download
        if manifest_version is None:
            manifest_version = "latest"

        click.echo(f"Manifest version: {manifest_version}")
        click.echo(f"remdb version: {get_current_version()}")

        # Prompt or auto-confirm
        if yes or click.confirm(f"Download manifests ({manifest_version})?", default=True):
            click.echo()
            success = download_manifests(manifest_version, manifests_dir.parent)
            if not success:
                click.echo()
                click.secho("Failed to download manifests. You can:", fg="yellow")
                click.echo("  1. Clone the repo: git clone https://github.com/anthropics/remstack.git")
                click.echo("  2. Download manually from: https://github.com/anthropics/remstack/releases")
                click.echo("  3. Specify existing manifests: rem cluster init --manifests-dir /path/to/manifests")
                raise click.Abort()
            click.echo()
        else:
            click.echo()
            click.secho("Skipping manifest download.", fg="yellow")
            click.echo("You can download later or specify a path with --manifests-dir")
            click.echo()

    # Set output path
    if output is None:
        output = manifests_dir / "cluster-config.yaml"

    # Check if config file exists
    if output.exists():
        if not click.confirm(f"{output} already exists. Overwrite?"):
            raise click.Abort()

    # Read template if it exists
    template_path = manifests_dir / "cluster-config.yaml"
    if template_path.exists() and template_path != output:
        with open(template_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Update with provided values
    if "project" not in config:
        config["project"] = {}
    config["project"]["name"] = project_name
    config["project"]["namespace"] = project_name

    if "git" not in config:
        config["git"] = {}
    config["git"]["repoURL"] = git_repo

    if "aws" not in config:
        config["aws"] = {}
    config["aws"]["region"] = region
    config["aws"]["ssmPrefix"] = f"/{project_name}"

    # Write config
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    click.secho(f"✓ Created cluster config: {output}", fg="green")
    click.echo()
    click.echo("Next steps:")
    click.echo(f"  1. Edit {output} to customize settings")
    click.echo("  2. Deploy CDK infrastructure: cd manifests/infra/cdk-eks && cdk deploy")
    click.echo("  3. Run: rem cluster setup-ssm")
    click.echo("  4. Run: rem cluster generate")
    click.echo("  5. Run: rem cluster validate")


@click.command("setup-ssm")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to cluster config file",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show commands without executing",
)
@click.option(
    "--force",
    is_flag=True,
    help="Overwrite existing parameters",
)
def setup_ssm(config: Path | None, dry_run: bool, force: bool):
    """
    Create required SSM parameters in AWS.

    Reads API keys from environment variables if set:
      - ANTHROPIC_API_KEY
      - OPENAI_API_KEY
      - GOOGLE_CLIENT_ID (optional)
      - GOOGLE_CLIENT_SECRET (optional)

    Creates the following parameters under the configured SSM prefix:
      - /postgres/username (String: remuser)
      - /postgres/password (SecureString, auto-generated)
      - /llm/anthropic-api-key (SecureString, from env or placeholder)
      - /llm/openai-api-key (SecureString, from env or placeholder)
      - /auth/session-secret (SecureString, auto-generated)
      - /auth/google-client-id (String, from env or placeholder)
      - /auth/google-client-secret (SecureString, from env or placeholder)
      - /phoenix/api-key (SecureString, auto-generated)
      - /phoenix/secret (SecureString, auto-generated)
      - /phoenix/admin-secret (SecureString, auto-generated)

    Examples:
        # With environment variables set
        export ANTHROPIC_API_KEY=sk-ant-...
        export OPENAI_API_KEY=sk-proj-...
        rem cluster setup-ssm

        # Using config file
        rem cluster setup-ssm --config my-cluster.yaml

        # Preview without creating
        rem cluster setup-ssm --dry-run
    """
    import secrets

    cfg = load_cluster_config(config)
    prefix = cfg.get("aws", {}).get("ssmPrefix", "/rem")
    region = cfg.get("aws", {}).get("region", "us-east-1")

    # Read API keys from environment
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "placeholder")
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "placeholder")

    click.echo()
    click.echo("SSM Parameter Setup")
    click.echo("=" * 60)
    click.echo(f"Prefix: {prefix}")
    click.echo(f"Region: {region}")
    click.echo()

    # Show env var status
    click.echo("Environment variables:")
    click.echo(f"  ANTHROPIC_API_KEY: {'✓ set' if anthropic_key else '✗ not set (will use placeholder)'}")
    click.echo(f"  OPENAI_API_KEY: {'✓ set' if openai_key else '✗ not set (will use placeholder)'}")
    click.echo(f"  GOOGLE_CLIENT_ID: {'✓ set' if google_client_id != 'placeholder' else '⚠ not set (OAuth disabled)'}")
    click.echo(f"  GOOGLE_CLIENT_SECRET: {'✓ set' if google_client_secret != 'placeholder' else '⚠ not set (OAuth disabled)'}")
    click.echo()

    # Define parameters to create
    parameters = [
        # PostgreSQL - username MUST be remuser to match CNPG cluster owner spec
        (f"{prefix}/postgres/username", "remuser", "String", "PostgreSQL username (must match CNPG owner)"),
        (f"{prefix}/postgres/password", secrets.token_urlsafe(24), "SecureString", "PostgreSQL password"),
        # LLM keys - from env or placeholder
        (f"{prefix}/llm/anthropic-api-key", anthropic_key or "REPLACE_WITH_YOUR_KEY", "SecureString", "Anthropic API key"),
        (f"{prefix}/llm/openai-api-key", openai_key or "REPLACE_WITH_YOUR_KEY", "SecureString", "OpenAI API key"),
        # Auth secrets
        (f"{prefix}/auth/session-secret", secrets.token_urlsafe(32), "SecureString", "Session signing secret"),
        (f"{prefix}/auth/google-client-id", google_client_id, "String", "Google OAuth client ID"),
        (f"{prefix}/auth/google-client-secret", google_client_secret, "SecureString", "Google OAuth client secret"),
        # Phoenix - auto-generated
        (f"{prefix}/phoenix/api-key", secrets.token_urlsafe(24), "SecureString", "Phoenix API key"),
        (f"{prefix}/phoenix/secret", secrets.token_urlsafe(32), "SecureString", "Phoenix session secret"),
        (f"{prefix}/phoenix/admin-secret", secrets.token_urlsafe(32), "SecureString", "Phoenix admin secret"),
    ]

    created = 0
    skipped = 0
    failed = 0

    for name, value, param_type, description in parameters:
        # Check if exists
        check_cmd = ["aws", "ssm", "get-parameter", "--name", name, "--region", region]

        if not dry_run:
            result = subprocess.run(check_cmd, capture_output=True)
            exists = result.returncode == 0

            if exists and not force:
                click.echo(f"  ⏭ {name} (exists, skipping)")
                skipped += 1
                continue

        # Create/update parameter
        put_cmd = [
            "aws", "ssm", "put-parameter",
            "--name", name,
            "--value", value,
            "--type", param_type,
            "--region", region,
            "--description", description,
        ]
        if force:
            put_cmd.append("--overwrite")

        if dry_run:
            display_value = "***" if param_type == "SecureString" else value
            if "REPLACE" in value or value == "placeholder":
                click.secho(f"  Would create: {name} = {display_value} (PLACEHOLDER)", fg="yellow")
            else:
                click.echo(f"  Would create: {name} = {display_value}")
        else:
            try:
                subprocess.run(put_cmd, check=True, capture_output=True)
                if "REPLACE" in value or value == "placeholder":
                    click.secho(f"  ⚠ {name} (placeholder - update later)", fg="yellow")
                else:
                    click.secho(f"  ✓ {name}", fg="green")
                created += 1
            except subprocess.CalledProcessError as e:
                if "ParameterAlreadyExists" in str(e.stderr):
                    click.echo(f"  ⏭ {name} (exists)")
                    skipped += 1
                else:
                    click.secho(f"  ✗ {name}: {e.stderr.decode()}", fg="red")
                    failed += 1

    click.echo()
    if dry_run:
        click.secho("Dry run - no parameters created", fg="yellow")
    else:
        click.secho(f"✓ SSM setup complete: {created} created, {skipped} skipped, {failed} failed", fg="green")

        # Show update instructions if placeholders were used
        if not anthropic_key or not openai_key:
            click.echo()
            click.secho("IMPORTANT: Update placeholder API keys:", fg="yellow")
            if not anthropic_key:
                click.echo(f"  aws ssm put-parameter --name {prefix}/llm/anthropic-api-key --value 'sk-ant-...' --type SecureString --overwrite --region {region}")
            if not openai_key:
                click.echo(f"  aws ssm put-parameter --name {prefix}/llm/openai-api-key --value 'sk-proj-...' --type SecureString --overwrite --region {region}")
            click.echo()
            click.echo("Or set environment variables and re-run with --force:")
            click.echo("  export ANTHROPIC_API_KEY=sk-ant-...")
            click.echo("  export OPENAI_API_KEY=sk-proj-...")
            click.echo("  rem cluster setup-ssm --force")


def _generate_sql_configmap(project_name: str, namespace: str, output_dir: Path) -> None:
    """
    Generate SQL init ConfigMap from migration files.

    Called by `cluster generate` to include SQL migrations in the manifest generation.
    """
    from ...utils.sql_paths import get_package_migrations_dir

    sql_dir = get_package_migrations_dir()

    if not sql_dir.exists():
        click.secho(f"  ⚠ SQL directory not found: {sql_dir}", fg="yellow")
        click.echo("    Run 'rem db schema generate' to create migrations")
        return

    # Read all SQL files in sorted order
    sql_files = {}
    for sql_file in sorted(sql_dir.glob("*.sql")):
        content = sql_file.read_text(encoding="utf-8")
        sql_files[sql_file.name] = content

    if not sql_files:
        click.secho("  ⚠ No SQL files found in migrations directory", fg="yellow")
        return

    # Generate ConfigMap YAML
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"{project_name}-postgres-init-sql",
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": f"{project_name}-postgres",
                "app.kubernetes.io/component": "init-sql",
            },
        },
        "data": sql_files,
    }

    output = output_dir / "application" / "rem-stack" / "components" / "postgres" / "postgres-init-configmap.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w") as f:
        f.write("# Auto-generated by: rem cluster generate\n")
        f.write("# Do not edit manually - regenerate with 'rem cluster generate'\n")
        f.write("#\n")
        f.write("# Source files:\n")
        for name in sql_files:
            f.write(f"#   - rem/sql/migrations/{name}\n")
        f.write("#\n")
        yaml.dump(configmap, f, default_flow_style=False, sort_keys=False)

    click.secho(f"  ✓ Generated {output.name} ({len(sql_files)} SQL files)", fg="green")


@click.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to cluster config file",
)
@click.option(
    "--pre-argocd",
    is_flag=True,
    help="Only check prerequisites needed before ArgoCD deployment",
)
def validate(config: Path | None, pre_argocd: bool):
    """
    Validate deployment prerequisites.

    Checks:
      1. Required tools (kubectl, aws, openssl)
      2. AWS credentials
      3. Kubernetes connectivity
      4. ArgoCD installation
      5. Environment variables (for setup-ssm)
      6. SSM parameters
      7. Platform operators (ESO, CNPG, KEDA) - skipped with --pre-argocd
      8. ClusterSecretStores - skipped with --pre-argocd

    Use --pre-argocd to validate only prerequisites needed before
    running 'rem cluster apply' for the first time.

    Examples:
        rem cluster validate                  # Full validation
        rem cluster validate --pre-argocd    # Pre-deployment checks only
        rem cluster validate --config my-cluster.yaml
    """
    cfg = load_cluster_config(config)
    project_name = cfg.get("project", {}).get("name", "rem")
    namespace = cfg.get("project", {}).get("namespace", project_name)
    region = cfg.get("aws", {}).get("region", "us-east-1")
    ssm_prefix = cfg.get("aws", {}).get("ssmPrefix", f"/{project_name}")

    click.echo()
    click.echo("REM Cluster Validation")
    click.echo("=" * 60)
    click.echo(f"Project: {project_name}")
    click.echo(f"Namespace: {namespace}")
    click.echo(f"Region: {region}")
    if pre_argocd:
        click.echo(f"Mode: Pre-ArgoCD (checking prerequisites only)")
    click.echo()

    errors = []
    warnings = []

    # 1. Check required tools
    click.echo("1. Required tools")
    tools = [
        ("kubectl", ["kubectl", "version", "--client", "-o", "json"]),
        ("aws", ["aws", "--version"]),
        ("openssl", ["openssl", "version"]),
    ]

    for tool, cmd in tools:
        if shutil.which(tool):
            click.secho(f"   ✓ {tool} installed", fg="green")
        else:
            errors.append(f"{tool} not installed")
            click.secho(f"   ✗ {tool} not installed", fg="red")

    # 2. Check AWS credentials
    click.echo()
    click.echo("2. AWS credentials")
    try:
        result = subprocess.run(
            ["aws", "sts", "get-caller-identity", "--region", region],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            import json
            identity = json.loads(result.stdout.decode())
            click.secho(f"   ✓ AWS credentials valid (account: {identity.get('Account', 'unknown')})", fg="green")
        else:
            errors.append("AWS credentials not configured")
            click.secho("   ✗ AWS credentials not configured", fg="red")
    except Exception as e:
        errors.append(f"AWS CLI error: {e}")
        click.secho(f"   ✗ AWS CLI error: {e}", fg="red")

    # 3. Check kubectl connectivity
    click.echo()
    click.echo("3. Kubernetes connectivity")
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0:
            # Get context name
            ctx_result = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True,
            )
            context = ctx_result.stdout.decode().strip() if ctx_result.returncode == 0 else "unknown"
            click.secho(f"   ✓ kubectl connected (context: {context})", fg="green")
        else:
            errors.append("kubectl not connected to cluster")
            click.secho("   ✗ kubectl not connected", fg="red")
    except Exception as e:
        errors.append(f"kubectl error: {e}")
        click.secho(f"   ✗ kubectl error: {e}", fg="red")

    # 4. Check ArgoCD installation
    click.echo()
    click.echo("4. ArgoCD installation")
    try:
        # Check namespace
        result = subprocess.run(
            ["kubectl", "get", "namespace", "argocd"],
            capture_output=True,
        )
        if result.returncode == 0:
            click.secho("   ✓ ArgoCD namespace exists", fg="green")

            # Check server deployment
            result = subprocess.run(
                ["kubectl", "get", "deployment", "argocd-server", "-n", "argocd", "-o", "jsonpath={.status.readyReplicas}"],
                capture_output=True,
            )
            if result.returncode == 0 and result.stdout.decode().strip():
                replicas = result.stdout.decode().strip()
                click.secho(f"   ✓ ArgoCD server running ({replicas} replica(s))", fg="green")
            else:
                warnings.append("ArgoCD server not ready")
                click.secho("   ⚠ ArgoCD server not ready", fg="yellow")
        else:
            errors.append("ArgoCD not installed")
            click.secho("   ✗ ArgoCD namespace not found", fg="red")
            click.echo("     Install with:")
            click.echo("       kubectl create namespace argocd")
            click.echo("       kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml")
    except Exception as e:
        errors.append(f"Could not check ArgoCD: {e}")
        click.secho(f"   ✗ Could not check ArgoCD: {e}", fg="red")

    # 5. Check environment variables
    click.echo()
    click.echo("5. Environment variables (for setup-ssm)")
    env_vars = [
        ("ANTHROPIC_API_KEY", True),
        ("OPENAI_API_KEY", True),
        ("GITHUB_PAT", True),
        ("GITHUB_USERNAME", True),
        ("GITHUB_REPO_URL", True),
        ("GOOGLE_CLIENT_ID", False),
        ("GOOGLE_CLIENT_SECRET", False),
    ]

    for var, required in env_vars:
        value = os.environ.get(var, "")
        if value:
            click.secho(f"   ✓ {var} is set", fg="green")
        elif required:
            warnings.append(f"Environment variable not set: {var}")
            click.secho(f"   ⚠ {var} not set (required for setup-ssm)", fg="yellow")
        else:
            click.echo(f"   - {var} not set (optional)")

    # 6. Check SSM parameters
    click.echo()
    click.echo("6. SSM parameters")
    required_params = [
        f"{ssm_prefix}/postgres/username",
        f"{ssm_prefix}/postgres/password",
    ]
    optional_params = [
        f"{ssm_prefix}/llm/anthropic-api-key",
        f"{ssm_prefix}/llm/openai-api-key",
    ]

    ssm_ok = True
    for param in required_params:
        try:
            result = subprocess.run(
                ["aws", "ssm", "get-parameter", "--name", param, "--region", region],
                capture_output=True,
            )
            if result.returncode == 0:
                click.secho(f"   ✓ {param}", fg="green")
            else:
                if pre_argocd:
                    click.echo(f"   - {param} (will be created by setup-ssm)")
                else:
                    errors.append(f"Required SSM parameter missing: {param}")
                    click.secho(f"   ✗ {param} (required)", fg="red")
                ssm_ok = False
        except Exception as e:
            errors.append(f"Could not check SSM: {e}")
            click.secho(f"   ✗ AWS CLI error: {e}", fg="red")
            ssm_ok = False
            break

    for param in optional_params:
        try:
            result = subprocess.run(
                ["aws", "ssm", "get-parameter", "--name", param, "--region", region],
                capture_output=True,
            )
            if result.returncode == 0:
                # Check if it's a placeholder
                output = result.stdout.decode()
                if "REPLACE_WITH" in output:
                    warnings.append(f"SSM parameter is placeholder: {param}")
                    click.secho(f"   ⚠ {param} (placeholder)", fg="yellow")
                else:
                    click.secho(f"   ✓ {param}", fg="green")
            else:
                if pre_argocd:
                    click.echo(f"   - {param} (will be created by setup-ssm)")
                else:
                    warnings.append(f"Optional SSM parameter missing: {param}")
                    click.secho(f"   ⚠ {param} (optional)", fg="yellow")
        except Exception:
            pass  # Already reported AWS CLI issues

    if not ssm_ok and pre_argocd:
        click.echo("   Run 'rem cluster setup-ssm' to create parameters")

    # Skip platform operator checks if --pre-argocd
    if not pre_argocd:
        # 7. Check platform operators
        click.echo()
        click.echo("7. Platform operators")
        operators = [
            ("external-secrets-system", "external-secrets", "External Secrets Operator"),
            ("cnpg-system", "cnpg-controller-manager", "CloudNativePG"),
            ("keda", "keda-operator", "KEDA"),
            ("cert-manager", "cert-manager", "cert-manager"),
        ]

        for ns, deployment, name in operators:
            try:
                result = subprocess.run(
                    ["kubectl", "get", "deployment", deployment, "-n", ns],
                    capture_output=True,
                )
                if result.returncode == 0:
                    click.secho(f"   ✓ {name}", fg="green")
                else:
                    warnings.append(f"{name} not found in {ns}")
                    click.secho(f"   ⚠ {name} not found", fg="yellow")
            except Exception:
                warnings.append(f"Could not check {name}")
                click.secho(f"   ⚠ Could not check {name}", fg="yellow")

        # 8. Check ClusterSecretStores
        click.echo()
        click.echo("8. ClusterSecretStores")
        stores = ["aws-parameter-store", "kubernetes-secrets"]

        for store in stores:
            try:
                result = subprocess.run(
                    ["kubectl", "get", "clustersecretstore", store],
                    capture_output=True,
                )
                if result.returncode == 0:
                    click.secho(f"   ✓ {store}", fg="green")
                else:
                    warnings.append(f"ClusterSecretStore {store} not found")
                    click.secho(f"   ⚠ {store} not found", fg="yellow")
            except Exception:
                warnings.append(f"Could not check ClusterSecretStore {store}")
                click.secho(f"   ⚠ Could not check {store}", fg="yellow")

    # Summary
    click.echo()
    click.echo("=" * 60)

    if errors:
        click.secho(f"✗ Validation failed with {len(errors)} error(s)", fg="red")
        for error in errors:
            click.echo(f"  - {error}")
        raise click.Abort()
    elif warnings:
        click.secho(f"⚠ Validation passed with {len(warnings)} warning(s)", fg="yellow")
        for warning in warnings[:5]:
            click.echo(f"  - {warning}")
        if len(warnings) > 5:
            click.echo(f"  ... and {len(warnings) - 5} more")
    else:
        click.secho("✓ All checks passed", fg="green")

    click.echo()
    if pre_argocd:
        click.echo("Next steps:")
        click.echo("  1. rem cluster setup-ssm     # Create SSM parameters")
        click.echo("  2. rem cluster apply         # Deploy ArgoCD apps")
    else:
        click.echo("Ready to deploy:")
        click.echo("  rem cluster apply")


@click.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to cluster config file",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for generated manifests",
)
def generate(config: Path | None, output_dir: Path | None):
    """
    Generate Kubernetes manifests from cluster config.

    Reads cluster-config.yaml and generates/updates:
      - ArgoCD Application manifests
      - ClusterSecretStore configurations
      - SQL init ConfigMap (from rem/sql/migrations/*.sql)
      - Kustomization patches

    Examples:
        rem cluster generate
        rem cluster generate --config my-cluster.yaml
    """
    cfg = load_cluster_config(config)
    project_name = cfg.get("project", {}).get("name", "rem")
    namespace = cfg.get("project", {}).get("namespace", project_name)
    region = cfg.get("aws", {}).get("region", "us-east-1")
    git_repo = cfg.get("git", {}).get("repoURL", "")
    git_branch = cfg.get("git", {}).get("targetRevision", "main")

    if output_dir is None:
        output_dir = get_manifests_dir()

    click.echo()
    click.echo("Generating Manifests from Config")
    click.echo("=" * 60)
    click.echo(f"Project: {project_name}")
    click.echo(f"Namespace: {namespace}")
    click.echo(f"Git: {git_repo}@{git_branch}")
    click.echo(f"Output: {output_dir}")
    click.echo()

    # Update ArgoCD application
    argocd_app = output_dir / "application" / "rem-stack" / "argocd-staging.yaml"
    if argocd_app.exists():
        with open(argocd_app) as f:
            content = f.read()

        # Update git repo URL
        if "repoURL:" in content:
            import re
            content = re.sub(
                r'repoURL:.*',
                f'repoURL: {git_repo}',
                content,
            )
            content = re.sub(
                r'namespace: rem\b',
                f'namespace: {namespace}',
                content,
            )

            with open(argocd_app, "w") as f:
                f.write(content)
            click.secho(f"  ✓ Updated {argocd_app.name}", fg="green")

    # Update ClusterSecretStore region
    css = output_dir / "platform" / "external-secrets" / "cluster-secret-store.yaml"
    if css.exists():
        with open(css) as f:
            content = f.read()

        if "region:" in content:
            import re
            content = re.sub(
                r'region:.*',
                f'region: {region}',
                content,
            )

            with open(css, "w") as f:
                f.write(content)
            click.secho(f"  ✓ Updated {css.name}", fg="green")

    # Generate SQL init ConfigMap from migrations
    _generate_sql_configmap(project_name, namespace, output_dir)

    click.echo()
    click.secho("✓ Manifests generated", fg="green")
    click.echo()
    click.echo("Next steps:")
    click.echo("  1. Review generated manifests")
    click.echo("  2. Commit changes to git")
    click.echo("  3. Deploy: rem cluster apply")


@click.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    help="Path to cluster config file",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deployed without executing",
)
@click.option(
    "--skip-platform",
    is_flag=True,
    help="Skip deploying platform-apps (only deploy rem-stack)",
)
def apply(config: Path | None, dry_run: bool, skip_platform: bool):
    """
    Deploy ArgoCD applications to the cluster.

    This command:
      1. Creates ArgoCD repository secret (for private repo access)
      2. Creates the application namespace
      3. Deploys platform-apps (app-of-apps for operators)
      4. Deploys rem-stack application

    Required environment variables:
      - GITHUB_REPO_URL: Git repository URL
      - GITHUB_PAT: GitHub Personal Access Token
      - GITHUB_USERNAME: GitHub username

    Examples:
        # Full deployment
        rem cluster apply

        # Preview what would be deployed
        rem cluster apply --dry-run

        # Only deploy rem-stack (platform already exists)
        rem cluster apply --skip-platform
    """
    cfg = load_cluster_config(config)
    project_name = cfg.get("project", {}).get("name", "rem")
    namespace = cfg.get("project", {}).get("namespace", project_name)
    git_repo = cfg.get("git", {}).get("repoURL", "")

    # Get credentials from environment, with fallback to gh CLI
    github_repo_url = os.environ.get("GITHUB_REPO_URL", git_repo)
    github_pat = os.environ.get("GITHUB_PAT", "")
    github_username = os.environ.get("GITHUB_USERNAME", "")

    # Auto-detect from gh CLI if not set
    if not github_pat or not github_username:
        try:
            # Try to get from gh CLI
            gh_user = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                capture_output=True, text=True, timeout=10
            )
            gh_token = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True, text=True, timeout=10
            )
            if gh_user.returncode == 0 and gh_token.returncode == 0:
                if not github_username:
                    github_username = gh_user.stdout.strip()
                if not github_pat:
                    github_pat = gh_token.stdout.strip()
                click.secho("  ℹ Using credentials from gh CLI", fg="cyan")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass  # gh CLI not available

    # Info about token type
    if github_pat:
        if github_pat.startswith("gho_"):
            click.secho("  ℹ Using OAuth token from gh CLI", fg="cyan")
        elif github_pat.startswith("ghp_"):
            click.secho("  ℹ Using Personal Access Token", fg="cyan")
        elif github_pat.startswith("github_pat_"):
            click.secho("  ℹ Using Fine-grained Personal Access Token", fg="cyan")

    # Auto-detect git remote if repo URL not set
    if not github_repo_url:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                github_repo_url = result.stdout.strip()
                click.secho(f"  ℹ Using repo URL from git remote: {github_repo_url}", fg="cyan")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    click.echo()
    click.echo("ArgoCD Application Deployment")
    click.echo("=" * 60)

    # Pre-validation
    click.echo("Pre-flight checks:")
    errors = 0

    # Check kubectl
    result = subprocess.run(["which", "kubectl"], capture_output=True)
    if result.returncode != 0:
        click.secho("  ✗ kubectl not found", fg="red")
        errors += 1
    else:
        click.secho("  ✓ kubectl available", fg="green")

    # Check cluster access
    result = subprocess.run(
        ["kubectl", "cluster-info"],
        capture_output=True,
        timeout=10,
    )
    if result.returncode != 0:
        click.secho("  ✗ Cannot connect to Kubernetes cluster", fg="red")
        click.echo("    Run: aws eks update-kubeconfig --name <cluster> --profile rem")
        errors += 1
    else:
        click.secho("  ✓ Kubernetes cluster accessible", fg="green")

    # Check argocd namespace exists
    result = subprocess.run(
        ["kubectl", "get", "namespace", "argocd"],
        capture_output=True,
    )
    if result.returncode != 0:
        click.secho("  ✗ argocd namespace not found", fg="red")
        click.echo("    ArgoCD should be installed by CDK (ENABLE_ARGOCD=true)")
        errors += 1
    else:
        click.secho("  ✓ argocd namespace exists", fg="green")

    if errors > 0:
        click.echo()
        click.secho(f"Pre-flight failed with {errors} error(s)", fg="red")
        raise click.Abort()

    click.echo()
    click.echo(f"Project: {project_name}")
    click.echo(f"Namespace: {namespace}")
    click.echo(f"Repository: {github_repo_url}")
    if dry_run:
        click.secho("Mode: DRY RUN (no changes will be made)", fg="yellow")
    click.echo()

    # Validate required values
    if not github_repo_url:
        click.secho("✗ GITHUB_REPO_URL not set", fg="red")
        click.echo("  Set via environment variable or cluster-config.yaml")
        raise click.Abort()

    if not github_pat or not github_username:
        click.secho("⚠ GITHUB_PAT or GITHUB_USERNAME not set", fg="yellow")
        click.echo("  Private repos will not be accessible without credentials")
        if not click.confirm("Continue without repo credentials?"):
            raise click.Abort()

    manifests_dir = get_manifests_dir()

    # Step 1: Create ArgoCD repository secret
    click.echo("1. ArgoCD repository secret")
    if github_pat and github_username:
        # Check if secret exists
        result = subprocess.run(
            ["kubectl", "get", "secret", "repo-reminiscent", "-n", "argocd"],
            capture_output=True,
        )
        secret_exists = result.returncode == 0

        if secret_exists:
            click.echo("   ⏭ Secret 'repo-reminiscent' exists (skipping)")
        else:
            if dry_run:
                click.echo("   Would create: secret/repo-reminiscent in argocd namespace")
            else:
                # Create the secret
                create_cmd = [
                    "kubectl", "create", "secret", "generic", "repo-reminiscent",
                    "--namespace", "argocd",
                    f"--from-literal=url={github_repo_url}",
                    f"--from-literal=username={github_username}",
                    f"--from-literal=password={github_pat}",
                    "--from-literal=type=git",
                    "--dry-run=client", "-o", "yaml",
                ]
                # Pipe to kubectl apply
                create_result = subprocess.run(create_cmd, capture_output=True)
                if create_result.returncode == 0:
                    apply_result = subprocess.run(
                        ["kubectl", "apply", "-f", "-"],
                        input=create_result.stdout,
                        capture_output=True,
                    )
                    if apply_result.returncode == 0:
                        # Label it as ArgoCD repo secret
                        subprocess.run([
                            "kubectl", "label", "secret", "repo-reminiscent",
                            "-n", "argocd",
                            "argocd.argoproj.io/secret-type=repository",
                            "--overwrite",
                        ], capture_output=True)
                        click.secho("   ✓ Created secret 'repo-reminiscent'", fg="green")
                    else:
                        click.secho(f"   ✗ Failed to create secret: {apply_result.stderr.decode()}", fg="red")
                        raise click.Abort()
    else:
        click.echo("   ⏭ Skipping (no credentials provided)")

    # Step 2: Create namespace
    click.echo()
    click.echo("2. Application namespace")
    result = subprocess.run(
        ["kubectl", "get", "namespace", namespace],
        capture_output=True,
    )
    if result.returncode == 0:
        click.echo(f"   ⏭ Namespace '{namespace}' exists")
    else:
        if dry_run:
            click.echo(f"   Would create: namespace/{namespace}")
        else:
            result = subprocess.run(
                ["kubectl", "create", "namespace", namespace],
                capture_output=True,
            )
            if result.returncode == 0:
                click.secho(f"   ✓ Created namespace '{namespace}'", fg="green")
            else:
                click.secho(f"   ✗ Failed to create namespace: {result.stderr.decode()}", fg="red")
                raise click.Abort()

    # Step 3: Deploy platform-apps (app-of-apps)
    if not skip_platform:
        click.echo()
        click.echo("3. Platform apps (app-of-apps)")
        platform_app = manifests_dir / "platform" / "argocd" / "app-of-apps.yaml"

        if not platform_app.exists():
            click.secho(f"   ✗ Not found: {platform_app}", fg="red")
            raise click.Abort()

        if dry_run:
            click.echo(f"   Would apply: {platform_app}")
        else:
            result = subprocess.run(
                ["kubectl", "apply", "-f", str(platform_app)],
                capture_output=True,
            )
            if result.returncode == 0:
                click.secho("   ✓ Applied platform-apps", fg="green")
            else:
                click.secho(f"   ✗ Failed: {result.stderr.decode()}", fg="red")
                raise click.Abort()

        # Wait for critical platform apps
        if not dry_run:
            click.echo()
            click.echo("   Waiting for cert-manager...")
            for _ in range(30):  # 5 minutes max
                result = subprocess.run(
                    ["kubectl", "get", "application", "cert-manager", "-n", "argocd",
                     "-o", "jsonpath={.status.health.status}"],
                    capture_output=True,
                )
                status = result.stdout.decode().strip()
                if status == "Healthy":
                    click.secho("   ✓ cert-manager is healthy", fg="green")
                    break
                click.echo(f"   ... cert-manager status: {status or 'Unknown'}")
                import time
                time.sleep(10)
            else:
                click.secho("   ⚠ cert-manager not healthy yet (continuing anyway)", fg="yellow")

    # Step 4: Deploy rem-stack
    click.echo()
    click.echo("4. REM stack application" if not skip_platform else "3. REM stack application")
    rem_stack_app = manifests_dir / "application" / "rem-stack" / "argocd-staging.yaml"

    if not rem_stack_app.exists():
        click.secho(f"   ✗ Not found: {rem_stack_app}", fg="red")
        raise click.Abort()

    if dry_run:
        click.echo(f"   Would apply: {rem_stack_app}")
    else:
        result = subprocess.run(
            ["kubectl", "apply", "-f", str(rem_stack_app)],
            capture_output=True,
        )
        if result.returncode == 0:
            click.secho("   ✓ Applied rem-stack-staging", fg="green")
        else:
            click.secho(f"   ✗ Failed: {result.stderr.decode()}", fg="red")
            raise click.Abort()

    # Summary
    click.echo()
    click.echo("=" * 60)
    if dry_run:
        click.secho("Dry run complete - no changes made", fg="yellow")
    else:
        click.secho("✓ Deployment initiated", fg="green")
        click.echo()
        click.echo("Monitor progress:")
        click.echo("  kubectl get applications -n argocd")
        click.echo("  watch kubectl get pods -n " + namespace)
        click.echo()
        click.echo("ArgoCD UI:")
        click.echo("  kubectl port-forward svc/argocd-server -n argocd 8080:443")
        click.echo("  # Get password: kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d")


# =============================================================================
# Environment Configuration Commands (rem cluster env ...)
# =============================================================================

@click.group()
def env():
    """
    Environment configuration management.

    Commands for validating and generating Kubernetes ConfigMaps
    from local .env files, ensuring consistency between local
    development and cluster deployments.

    Examples:
        rem cluster env check              # Validate .env for staging
        rem cluster env check --env prod   # Validate for production
        rem cluster env generate           # Generate ConfigMap from .env
        rem cluster env diff               # Compare .env with cluster
    """
    pass


# Patterns that indicate localhost/development values inappropriate for cluster
LOCALHOST_PATTERNS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "host.docker.internal",
]

# Required env vars for each environment
# These align with rem-config ConfigMap structure in manifests/application/rem-stack/base/kustomization.yaml
ENV_REQUIREMENTS = {
    "staging": {
        "required": [
            "ENVIRONMENT",
            "AWS_REGION",
            "S3__BUCKET_NAME",
        ],
        "recommended": [
            "LLM__ANTHROPIC_API_KEY",
            "LLM__OPENAI_API_KEY",
            "LLM__DEFAULT_MODEL",
            "OTEL_COLLECTOR_ENDPOINT",
            "OTEL__ENABLED",
            "LOG_LEVEL",
            "AUTH__ENABLED",
            "MODELS__IMPORT_MODULES",
        ],
        "no_localhost": [
            "POSTGRES__CONNECTION_STRING",
            "OTEL_COLLECTOR_ENDPOINT",
            "S3__ENDPOINT_URL",
        ],
    },
    "prod": {
        "required": [
            "ENVIRONMENT",
            "AWS_REGION",
            "S3__BUCKET_NAME",
            "AUTH__ENABLED",
        ],
        "recommended": [
            "LLM__ANTHROPIC_API_KEY",
            "LLM__OPENAI_API_KEY",
            "LLM__DEFAULT_MODEL",
            "OTEL_COLLECTOR_ENDPOINT",
            "OTEL__ENABLED",
            "LOG_LEVEL",
            "AUTH__SESSION_SECRET",
            "MODELS__IMPORT_MODULES",
        ],
        "no_localhost": [
            "POSTGRES__CONNECTION_STRING",
            "OTEL_COLLECTOR_ENDPOINT",
            "S3__ENDPOINT_URL",
            "AUTH__GOOGLE__REDIRECT_URI",
            "AUTH__MICROSOFT__REDIRECT_URI",
        ],
    },
    "local": {
        "required": [
            "ENVIRONMENT",
        ],
        "recommended": [
            "LLM__ANTHROPIC_API_KEY",
            "LLM__OPENAI_API_KEY",
            "MODELS__IMPORT_MODULES",
        ],
        "no_localhost": [],  # localhost is fine for local
    },
}


def load_env_file(env_path: Path) -> dict[str, str]:
    """Load environment variables from a .env file."""
    env_vars = {}
    if not env_path.exists():
        return env_vars

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue
            # Parse KEY=value
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Remove quotes if present
                if value and value[0] in ('"', "'") and value[-1] == value[0]:
                    value = value[1:-1]
                env_vars[key] = value

    return env_vars


def has_localhost(value: str) -> bool:
    """Check if a value contains localhost-like patterns."""
    value_lower = value.lower()
    return any(pattern in value_lower for pattern in LOCALHOST_PATTERNS)


@env.command("check")
@click.option(
    "--env-file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to .env file (default: .env in current directory)",
)
@click.option(
    "--environment",
    "--env",
    "-e",
    type=click.Choice(["local", "staging", "prod"]),
    default="staging",
    help="Target environment to validate against (default: staging)",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Treat warnings as errors",
)
def env_check(env_file: Path | None, environment: str, strict: bool):
    """
    Validate .env file for a target environment.

    Checks that environment variables are appropriate for the target
    deployment environment (local, staging, prod).

    Validates:
    - Required variables are set
    - No localhost values in cluster configs
    - Recommended variables for the environment
    - Placeholder values that need updating

    Examples:
        rem cluster env check                    # Check .env for staging
        rem cluster env check --env prod         # Check for production
        rem cluster env check -f backend/.env    # Check specific file
        rem cluster env check --strict           # Fail on warnings
    """
    # Find .env file
    if env_file is None:
        # Try common locations
        for candidate in [Path(".env"), Path("application/backend/.env"), Path("backend/.env")]:
            if candidate.exists():
                env_file = candidate
                break

    if env_file is None or not env_file.exists():
        click.secho("✗ No .env file found", fg="red")
        click.echo()
        click.echo("Specify path with: rem cluster env check -f /path/to/.env")
        raise click.Abort()

    click.echo()
    click.echo(f"Environment Config Check: {environment}")
    click.echo("=" * 60)
    click.echo(f"File: {env_file}")
    click.echo()

    # Load env vars
    env_vars = load_env_file(env_file)

    if not env_vars:
        click.secho("✗ No environment variables found in file", fg="red")
        raise click.Abort()

    click.echo(f"Found {len(env_vars)} variables")
    click.echo()

    requirements = ENV_REQUIREMENTS.get(environment, ENV_REQUIREMENTS["staging"])
    errors = []
    warnings = []

    # Check required variables
    click.echo("Required variables:")
    for var in requirements["required"]:
        if var in env_vars and env_vars[var]:
            click.secho(f"  ✓ {var}", fg="green")
        else:
            errors.append(f"Missing required: {var}")
            click.secho(f"  ✗ {var} (missing or empty)", fg="red")

    # Check for localhost in cluster configs
    if requirements["no_localhost"]:
        click.echo()
        click.echo("Localhost check (should not contain localhost for cluster):")
        for var in requirements["no_localhost"]:
            if var in env_vars:
                value = env_vars[var]
                if has_localhost(value):
                    errors.append(f"Localhost value in {var}: {value}")
                    click.secho(f"  ✗ {var} contains localhost: {value[:50]}...", fg="red")
                else:
                    click.secho(f"  ✓ {var}", fg="green")
            else:
                click.echo(f"  - {var} (not set)")

    # Check recommended variables
    click.echo()
    click.echo("Recommended variables:")
    for var in requirements["recommended"]:
        if var in env_vars:
            value = env_vars[var]
            # Check for placeholder values
            if "REPLACE" in value or "YOUR_" in value or value == "":
                warnings.append(f"Placeholder value: {var}")
                click.secho(f"  ⚠ {var} (placeholder value)", fg="yellow")
            else:
                click.secho(f"  ✓ {var}", fg="green")
        else:
            warnings.append(f"Missing recommended: {var}")
            click.secho(f"  ⚠ {var} (not set)", fg="yellow")

    # Check ENVIRONMENT value matches target
    click.echo()
    click.echo("Environment consistency:")
    env_value = env_vars.get("ENVIRONMENT", "")
    if env_value == environment or (environment == "local" and env_value == "development"):
        click.secho(f"  ✓ ENVIRONMENT={env_value} (matches target)", fg="green")
    elif env_value:
        warnings.append(f"ENVIRONMENT mismatch: {env_value} != {environment}")
        click.secho(f"  ⚠ ENVIRONMENT={env_value} (target is {environment})", fg="yellow")

    # Summary
    click.echo()
    click.echo("=" * 60)

    if errors:
        click.secho(f"✗ Check failed with {len(errors)} error(s)", fg="red")
        for error in errors:
            click.echo(f"  - {error}")
        raise click.Abort()
    elif warnings:
        if strict:
            click.secho(f"✗ Check failed with {len(warnings)} warning(s) (strict mode)", fg="red")
            for warning in warnings:
                click.echo(f"  - {warning}")
            raise click.Abort()
        else:
            click.secho(f"⚠ Check passed with {len(warnings)} warning(s)", fg="yellow")
    else:
        click.secho(f"✓ All checks passed for {environment}", fg="green")


@env.command("generate")
@click.option(
    "--env-file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to .env file",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output path for ConfigMap YAML",
)
@click.option(
    "--name",
    default="rem-config",
    help="ConfigMap name (default: rem-config)",
)
@click.option(
    "--namespace",
    "-n",
    default="rem",
    help="Kubernetes namespace (default: rem)",
)
@click.option(
    "--exclude-secrets",
    is_flag=True,
    default=True,
    help="Exclude secret values (API keys, passwords) - default: True",
)
@click.option(
    "--apply",
    is_flag=True,
    help="Apply ConfigMap directly to cluster",
)
def env_generate(
    env_file: Path | None,
    output: Path | None,
    name: str,
    namespace: str,
    exclude_secrets: bool,
    apply: bool,
):
    """
    Generate Kubernetes ConfigMap from .env file.

    Converts local .env file to a Kubernetes ConfigMap YAML,
    optionally excluding sensitive values (API keys, passwords).

    Secret values should be managed via ExternalSecrets/SSM, not ConfigMaps.

    Examples:
        rem cluster env generate                    # Generate from .env
        rem cluster env generate -o configmap.yaml  # Custom output path
        rem cluster env generate --apply            # Apply to cluster
    """
    # Secret patterns to exclude
    secret_patterns = [
        "API_KEY",
        "SECRET",
        "PASSWORD",
        "TOKEN",
        "CREDENTIAL",
    ]

    # Find .env file
    if env_file is None:
        for candidate in [Path(".env"), Path("application/backend/.env"), Path("backend/.env")]:
            if candidate.exists():
                env_file = candidate
                break

    if env_file is None or not env_file.exists():
        click.secho("✗ No .env file found", fg="red")
        raise click.Abort()

    click.echo()
    click.echo("Generate ConfigMap from .env")
    click.echo("=" * 60)
    click.echo(f"Source: {env_file}")
    click.echo(f"ConfigMap: {name}")
    click.echo(f"Namespace: {namespace}")
    click.echo()

    # Load env vars
    env_vars = load_env_file(env_file)

    # Filter out secrets if requested
    config_data = {}
    excluded = []

    for key, value in env_vars.items():
        # Check if this looks like a secret
        is_secret = any(pattern in key.upper() for pattern in secret_patterns)

        if exclude_secrets and is_secret:
            excluded.append(key)
        else:
            config_data[key] = value

    click.echo(f"Variables to include: {len(config_data)}")
    if excluded:
        click.echo(f"Excluded (secrets): {len(excluded)}")
        for key in excluded[:5]:
            click.echo(f"  - {key}")
        if len(excluded) > 5:
            click.echo(f"  ... and {len(excluded) - 5} more")

    # Generate ConfigMap
    configmap = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/managed-by": "rem-cli",
            },
        },
        "data": config_data,
    }

    # Output
    if output is None:
        output = Path(f"{name}-configmap.yaml")

    with open(output, "w") as f:
        f.write(f"# Generated by: rem cluster env generate\n")
        f.write(f"# Source: {env_file}\n")
        f.write(f"# Date: {__import__('datetime').datetime.utcnow().isoformat()}Z\n")
        f.write("#\n")
        if excluded:
            f.write("# Excluded secrets (use ExternalSecrets for these):\n")
            for key in excluded:
                f.write(f"#   - {key}\n")
            f.write("#\n")
        yaml.dump(configmap, f, default_flow_style=False, sort_keys=False)

    click.echo()
    click.secho(f"✓ Generated: {output}", fg="green")

    if apply:
        click.echo()
        click.echo("Applying to cluster...")
        try:
            subprocess.run(["kubectl", "apply", "-f", str(output)], check=True)
            click.secho("✓ ConfigMap applied", fg="green")
        except subprocess.CalledProcessError as e:
            click.secho(f"✗ Failed to apply: {e}", fg="red")
            raise click.Abort()


@env.command("diff")
@click.option(
    "--env-file",
    "-f",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to .env file",
)
@click.option(
    "--configmap",
    "-c",
    default="rem-config",
    help="ConfigMap name to compare (default: rem-config)",
)
@click.option(
    "--namespace",
    "-n",
    default="rem",
    help="Kubernetes namespace (default: rem)",
)
def env_diff(env_file: Path | None, configmap: str, namespace: str):
    """
    Compare local .env with cluster ConfigMap.

    Shows differences between local environment configuration
    and what's deployed in the Kubernetes cluster.

    Examples:
        rem cluster env diff                       # Compare with rem-config
        rem cluster env diff -c my-config          # Compare with custom ConfigMap
        rem cluster env diff -n production         # Compare in different namespace
    """
    # Find .env file
    if env_file is None:
        for candidate in [Path(".env"), Path("application/backend/.env"), Path("backend/.env")]:
            if candidate.exists():
                env_file = candidate
                break

    if env_file is None or not env_file.exists():
        click.secho("✗ No .env file found", fg="red")
        raise click.Abort()

    click.echo()
    click.echo("Compare .env with Cluster ConfigMap")
    click.echo("=" * 60)
    click.echo(f"Local: {env_file}")
    click.echo(f"Cluster: {configmap} (namespace: {namespace})")
    click.echo()

    # Load local env
    local_vars = load_env_file(env_file)

    # Get cluster ConfigMap
    try:
        result = subprocess.run(
            ["kubectl", "get", "configmap", configmap, "-n", namespace, "-o", "yaml"],
            capture_output=True,
            check=True,
        )
        cluster_cm = yaml.safe_load(result.stdout.decode())
        cluster_vars = cluster_cm.get("data", {})
    except subprocess.CalledProcessError:
        click.secho(f"✗ ConfigMap {configmap} not found in {namespace}", fg="red")
        click.echo()
        click.echo("Generate and apply with:")
        click.echo(f"  rem cluster env generate --name {configmap} --namespace {namespace} --apply")
        raise click.Abort()

    # Compare
    local_keys = set(local_vars.keys())
    cluster_keys = set(cluster_vars.keys())

    only_local = local_keys - cluster_keys
    only_cluster = cluster_keys - local_keys
    common = local_keys & cluster_keys

    # Check for differences in common keys
    different = []
    for key in common:
        if local_vars[key] != cluster_vars[key]:
            different.append(key)

    # Report
    if only_local:
        click.echo(f"Only in local .env ({len(only_local)}):")
        for key in sorted(only_local)[:10]:
            click.secho(f"  + {key}", fg="green")
        if len(only_local) > 10:
            click.echo(f"  ... and {len(only_local) - 10} more")
        click.echo()

    if only_cluster:
        click.echo(f"Only in cluster ({len(only_cluster)}):")
        for key in sorted(only_cluster)[:10]:
            click.secho(f"  - {key}", fg="red")
        if len(only_cluster) > 10:
            click.echo(f"  ... and {len(only_cluster) - 10} more")
        click.echo()

    if different:
        click.echo(f"Different values ({len(different)}):")
        for key in sorted(different)[:10]:
            click.secho(f"  ~ {key}", fg="yellow")
            # Show truncated values (hide secrets)
            if "SECRET" not in key.upper() and "KEY" not in key.upper() and "PASSWORD" not in key.upper():
                local_val = local_vars[key][:30] + "..." if len(local_vars[key]) > 30 else local_vars[key]
                cluster_val = cluster_vars[key][:30] + "..." if len(cluster_vars[key]) > 30 else cluster_vars[key]
                click.echo(f"      local:   {local_val}")
                click.echo(f"      cluster: {cluster_val}")
        if len(different) > 10:
            click.echo(f"  ... and {len(different) - 10} more")
        click.echo()

    # Summary
    click.echo("=" * 60)
    if not only_local and not only_cluster and not different:
        click.secho("✓ Local .env matches cluster ConfigMap", fg="green")
    else:
        total_diff = len(only_local) + len(only_cluster) + len(different)
        click.secho(f"⚠ Found {total_diff} difference(s)", fg="yellow")
        click.echo()
        click.echo("To sync local → cluster:")
        click.echo(f"  rem cluster env generate --name {configmap} --namespace {namespace} --apply")


def register_commands(cluster_group):
    """Register all cluster commands."""
    cluster_group.add_command(init)
    cluster_group.add_command(setup_ssm)
    cluster_group.add_command(validate)
    cluster_group.add_command(generate)
    cluster_group.add_command(apply)
    cluster_group.add_command(env)
