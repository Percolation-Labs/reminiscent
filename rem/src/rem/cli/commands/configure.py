"""
REM configuration wizard.

Interactive setup wizard for configuring REM on a new installation.

Usage:
    rem configure               # Interactive wizard
    rem configure --install     # Run wizard + install database tables
    rem configure --show        # Show current configuration
    rem configure --edit        # Open config file in editor
"""

import os
import subprocess
from pathlib import Path

import click
from loguru import logger

from rem.config import (
    config_exists,
    ensure_config_dir,
    get_config_path,
    get_default_config,
    load_config,
    save_config,
    validate_config,
)


def prompt_postgres_config(use_defaults: bool = False) -> dict:
    """
    Prompt user for PostgreSQL configuration.

    Args:
        use_defaults: If True, use all default values without prompting

    Returns:
        PostgreSQL configuration dictionary
    """
    click.echo("\n" + "=" * 60)
    click.echo("PostgreSQL Configuration")
    click.echo("=" * 60)

    # Parse existing config if available
    existing_conn = os.environ.get(
        "POSTGRES__CONNECTION_STRING", "postgresql://rem:rem@localhost:5051/rem"
    )

    # Default values
    host = "localhost"
    port = 5051
    database = "rem"
    username = "rem"
    password = "rem"
    pool_min_size = 5
    pool_max_size = 20

    if use_defaults:
        click.echo("\nUsing default PostgreSQL configuration:")
        click.echo(f"  Host: {host}")
        click.echo(f"  Port: {port}")
        click.echo(f"  Database: {database}")
        click.echo(f"  Username: {username}")
        click.echo(f"  Pool: {pool_min_size}-{pool_max_size} connections")
    else:
        # Prompt for components
        click.echo(
            "\nEnter PostgreSQL connection details (press Enter to use default):"
        )
        click.echo("Default: Package users on port 5051 (docker compose -f docker-compose.prebuilt.yml up -d)")
        click.echo("Developers: Change port to 5050 if using docker-compose.yml (local build)")
        click.echo("Custom DB: Enter your own host/port below")

        host = click.prompt("Host", default=host)
        port = click.prompt("Port", default=port, type=int)
        database = click.prompt("Database name", default=database)
        username = click.prompt("Username", default=username)
        password = click.prompt("Password", default=password, hide_input=True)

        # Additional pool settings
        click.echo("\nConnection pool settings:")
        pool_min_size = click.prompt("Pool minimum size", default=pool_min_size, type=int)
        pool_max_size = click.prompt("Pool maximum size", default=pool_max_size, type=int)

    # Build connection string
    connection_string = f"postgresql://{username}:{password}@{host}:{port}/{database}"

    return {
        "connection_string": connection_string,
        "pool_min_size": pool_min_size,
        "pool_max_size": pool_max_size,
    }


def prompt_llm_config(use_defaults: bool = False) -> dict:
    """
    Prompt user for LLM provider configuration.

    Args:
        use_defaults: If True, use all default values without prompting

    Returns:
        LLM configuration dictionary
    """
    click.echo("\n" + "=" * 60)
    click.echo("LLM Provider Configuration")
    click.echo("=" * 60)

    config = {}

    # Default values
    default_model = "openai:gpt-4.1"
    default_temperature = 0.5

    if use_defaults:
        click.echo("\nUsing default LLM configuration:")
        click.echo(f"  Model: {default_model}")
        click.echo(f"  Temperature: {default_temperature}")
        click.echo("  API Keys: Not configured (set via environment variables)")
        config["default_model"] = default_model
        config["default_temperature"] = default_temperature
    else:
        # Default model
        click.echo("\nDefault LLM model (format: provider:model-id)")
        click.echo("Examples:")
        click.echo("  - openai:gpt-4.1")
        click.echo("  - anthropic:claude-sonnet-4-5-20250929")
        click.echo("  - openai:gpt-4.1-mini")

        config["default_model"] = click.prompt(
            "Default model", default=default_model
        )

        # Temperature
        config["default_temperature"] = click.prompt(
            "Default temperature (0.0-1.0)", default=default_temperature, type=float
        )

        # API keys
        click.echo("\nAPI Keys (optional - leave empty to skip):")

        openai_key = click.prompt("OpenAI API key", default="", show_default=False)
        if openai_key:
            config["openai_api_key"] = openai_key

        anthropic_key = click.prompt("Anthropic API key", default="", show_default=False)
        if anthropic_key:
            config["anthropic_api_key"] = anthropic_key

    return config


def prompt_s3_config(use_defaults: bool = False) -> dict:
    """
    Prompt user for S3 storage configuration.

    Args:
        use_defaults: If True, skip S3 configuration (optional feature)

    Returns:
        S3 configuration dictionary
    """
    click.echo("\n" + "=" * 60)
    click.echo("S3 Storage Configuration")
    click.echo("=" * 60)

    config = {}

    if use_defaults:
        click.echo("\nSkipping S3 configuration (optional - configure later if needed)")
        return {}

    click.echo("\nS3 storage is used for file uploads and processed content.")
    use_s3 = click.confirm("Configure S3 storage?", default=False)

    if not use_s3:
        return {}

    config["bucket_name"] = click.prompt("S3 bucket name", default="rem-storage")
    config["region"] = click.prompt("AWS region", default="us-east-1")

    # Optional: MinIO or LocalStack endpoint
    use_custom_endpoint = click.confirm(
        "Use custom S3 endpoint (MinIO, LocalStack)?", default=False
    )
    if use_custom_endpoint:
        config["endpoint_url"] = click.prompt(
            "Endpoint URL", default="http://localhost:9000"
        )
        config["access_key_id"] = click.prompt("Access key ID", default="minioadmin")
        config["secret_access_key"] = click.prompt(
            "Secret access key", default="minioadmin", hide_input=True
        )

    return config


def prompt_additional_env_vars(use_defaults: bool = False) -> dict:
    """
    Prompt user for additional environment variables.

    Args:
        use_defaults: If True, skip additional env vars (optional feature)

    Returns:
        Dictionary of custom environment variables
    """
    click.echo("\n" + "=" * 60)
    click.echo("Additional Environment Variables")
    click.echo("=" * 60)

    env_vars: dict[str, str] = {}

    if use_defaults:
        click.echo("\nSkipping additional environment variables (configure later if needed)")
        return env_vars

    add_env = click.confirm(
        "Add custom environment variables?", default=False
    )

    if not add_env:
        return env_vars

    click.echo("\nEnter environment variables (empty name to finish):")
    while True:
        name = click.prompt("Variable name", default="", show_default=False)
        if not name:
            break

        value = click.prompt(f"Value for {name}")
        env_vars[name] = value

    return env_vars


@click.command("configure")
@click.option(
    "--install",
    is_flag=True,
    help="Install database tables after configuration",
)
@click.option(
    "--claude-desktop",
    is_flag=True,
    help="Register REM MCP server with Claude Desktop",
)
@click.option(
    "--show",
    is_flag=True,
    help="Show current configuration",
)
@click.option(
    "--edit",
    is_flag=True,
    help="Open configuration file in editor",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Accept all defaults without prompting (non-interactive mode)",
)
def configure_command(install: bool, claude_desktop: bool, show: bool, edit: bool, yes: bool):
    """
    Configure REM installation.

    Interactive wizard for setting up PostgreSQL, LLM providers, S3, and more.
    Configuration is saved to ~/.rem/config.yaml and merged with environment variables.

    Examples:
        rem configure                    # Run interactive wizard
        rem configure --yes              # Accept all defaults (non-interactive)
        rem configure --yes --install    # Quick setup with defaults + install tables
        rem configure --install          # Run wizard + install database tables
        rem configure --show             # Show current configuration
        rem configure --edit             # Open config in $EDITOR
    """
    config_path = get_config_path()

    # Show current configuration
    if show:
        if not config_exists():
            click.echo(f"No configuration file found at {config_path}")
            click.echo("Run 'rem configure' to create one.")
            return

        config = load_config()
        click.echo(f"\nConfiguration file: {config_path}")
        click.echo("=" * 60)

        import yaml

        click.echo(yaml.dump(config, default_flow_style=False, sort_keys=False))
        return

    # Edit configuration file
    if edit:
        if not config_exists():
            click.echo(f"No configuration file found at {config_path}")
            click.echo("Run 'rem configure' to create one first.")
            return

        editor = os.environ.get("EDITOR", "vim")
        try:
            subprocess.run([editor, str(config_path)], check=True)
            click.echo(f"\nConfiguration saved to {config_path}")
        except Exception as e:
            click.echo(f"Error opening editor: {e}", err=True)
            click.echo(f"Manually edit: {config_path}")
        return

    # Run interactive wizard
    click.echo("\n" + "=" * 60)
    click.echo("REM Configuration Wizard")
    click.echo("=" * 60)

    if yes:
        click.echo("\nRunning in non-interactive mode (--yes flag)")
        click.echo("Using default configuration values...")
    else:
        click.echo("\nThis wizard will help you configure REM for first-time use.")

    click.echo(f"Configuration will be saved to: {config_path}")

    # Check if config already exists
    if config_exists():
        click.echo(f"\nConfiguration file already exists at {config_path}")
        if yes:
            # In non-interactive mode, skip configuration creation
            click.echo("Skipping configuration creation (file already exists)")
            config = None  # Will not save/validate
        elif not click.confirm("Overwrite existing configuration?", default=False):
            click.echo("Configuration unchanged.")
            config = None  # Will not save/validate
        else:
            # User confirmed overwrite - create new config
            config = {}
            config["postgres"] = prompt_postgres_config(use_defaults=yes)
            config["llm"] = prompt_llm_config(use_defaults=yes)
            s3_config = prompt_s3_config(use_defaults=yes)
            if s3_config:
                config["s3"] = s3_config
            env_vars = prompt_additional_env_vars(use_defaults=yes)
            if env_vars:
                config["env"] = env_vars
    else:
        # No existing config - create new one
        config = {}
        config["postgres"] = prompt_postgres_config(use_defaults=yes)
        config["llm"] = prompt_llm_config(use_defaults=yes)
        s3_config = prompt_s3_config(use_defaults=yes)
        if s3_config:
            config["s3"] = s3_config
        env_vars = prompt_additional_env_vars(use_defaults=yes)
        if env_vars:
            config["env"] = env_vars

    # Validate and save configuration (only if we created one)
    if config is not None:
        click.echo("\n" + "=" * 60)
        click.echo("Validating Configuration")
        click.echo("=" * 60)

        errors = validate_config(config)
        if errors:
            click.echo("\nConfiguration validation failed:")
            for error in errors:
                click.echo(f"  ❌ {error}", err=True)
            click.echo("\nPlease fix these errors and try again.")
            return

        click.echo("✅ Configuration is valid")

        # Save configuration
        try:
            save_config(config)
            click.echo(f"\n✅ Configuration saved to {config_path}")
        except Exception as e:
            click.echo(f"\n❌ Failed to save configuration: {e}", err=True)
            return
    else:
        # Load existing config for use in install step
        config = load_config() if config_exists() else {}

    # Install database tables if requested
    if install:
        click.echo("\n" + "=" * 60)
        click.echo("Database Installation")
        click.echo("=" * 60)

        if yes or click.confirm("\nInstall database tables?", default=True):
            try:
                # Import here to ensure config is loaded first
                from rem.config import merge_config_to_env

                # Merge config into environment before running migrations
                merge_config_to_env(config)

                click.echo("\nRunning database migrations...")

                # Import and run migrations
                from rem.cli.commands.db import migrate

                # Create a context for the command and invoke it
                ctx = click.Context(migrate)
                ctx.invoke(migrate, background_indexes=False)

                click.echo("✅ Database installation complete")

            except Exception as e:
                click.echo(f"\n❌ Database installation failed: {e}", err=True)
                click.echo("\nYou can manually install tables later with:")
                click.echo("  rem db migrate")

    # Register with Claude Desktop if requested
    if claude_desktop:
        click.echo("\n" + "=" * 60)
        click.echo("Claude Desktop Integration")
        click.echo("=" * 60)

        try:
            import shutil
            from fastmcp.mcp_config import update_config_file, StdioMCPServer

            # Find Claude Desktop config path
            if os.name == "nt":  # Windows
                config_dir = Path.home() / "AppData/Roaming/Claude"
            elif os.name == "posix":
                macos_path = Path.home() / "Library/Application Support/Claude"
                if macos_path.exists():
                    config_dir = macos_path
                else:
                    config_dir = Path.home() / ".config/Claude"
            else:
                config_dir = Path.home() / ".config/Claude"

            config_path = config_dir / "claude_desktop_config.json"

            # Find rem executable
            rem_executable = shutil.which("rem")
            if not rem_executable:
                click.echo("❌ 'rem' command not found in PATH", err=True)
                return

            # Create server config with all necessary env vars
            env_vars = {
                "POSTGRES__CONNECTION_STRING": config.get("postgres", {}).get("connection_string", "")
            }

            # Add LLM API keys if present
            llm_config = config.get("llm", {})
            if llm_config.get("openai_api_key"):
                env_vars["LLM__OPENAI_API_KEY"] = llm_config["openai_api_key"]
            if llm_config.get("anthropic_api_key"):
                env_vars["LLM__ANTHROPIC_API_KEY"] = llm_config["anthropic_api_key"]

            server_config = StdioMCPServer(
                command=rem_executable,
                args=["mcp"],
                env=env_vars
            )

            # Update config file using FastMCP utility
            update_config_file(config_path, "rem", server_config)

            click.echo(f"✅ Registered REM MCP server with Claude Desktop")
            click.echo(f"Config: {config_path}")
            click.echo("\nRestart Claude Desktop to use the REM server.")

        except Exception as e:
            click.echo(f"❌ Failed: {e}", err=True)

    # Next steps
    click.echo("\n" + "=" * 60)
    click.echo("Next Steps")
    click.echo("=" * 60)
    click.echo("\n1. Verify configuration:")
    click.echo("     rem configure --show")
    click.echo("\n2. Edit configuration (if needed):")
    click.echo("     rem configure --edit")
    if not install:
        click.echo("\n3. Install database tables:")
        click.echo("     rem db migrate")
    click.echo("\n4. Start the API server:")
    click.echo("     rem dev run-server")
    click.echo("\n5. Test the installation:")
    click.echo("     rem ask 'Hello, REM!'")
    click.echo()


def register_command(cli_group):
    """Register the configure command."""
    cli_group.add_command(configure_command)
