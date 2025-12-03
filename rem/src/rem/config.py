"""
REM Configuration Management.

Provides persistent configuration in ~/.rem/config.yaml with environment variable overrides.

Configuration Precedence (highest to lowest):
1. Environment variables (POSTGRES__CONNECTION_STRING, etc.)
2. ~/.rem/config.yaml (user configuration)
3. Default values (from settings.py)

File Format (~/.rem/config.yaml):
    postgres:
      connection_string: postgresql://user:pass@localhost:5432/rem
      pool_min_size: 5
      pool_max_size: 20

    llm:
      default_model: openai:gpt-4.1
      openai_api_key: sk-...
      anthropic_api_key: sk-ant-...

    s3:
      bucket_name: rem-storage
      region: us-east-1
      endpoint_url: http://localhost:9000

    # Additional custom environment variables
    env:
      MY_CUSTOM_VAR: value

Usage:
    from rem.config import load_config, get_config_path, ensure_config_dir

    # Load configuration and merge with environment
    config = load_config()

    # Get configuration file path
    config_path = get_config_path()

    # Ensure ~/.rem directory exists
    ensure_config_dir()
"""

import os
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


def get_rem_home() -> Path:
    """
    Get REM home directory (~/.rem).

    Returns:
        Path to ~/.rem directory
    """
    return Path.home() / ".rem"


def ensure_config_dir() -> Path:
    """
    Ensure ~/.rem directory exists.

    Returns:
        Path to ~/.rem directory
    """
    rem_home = get_rem_home()
    rem_home.mkdir(exist_ok=True, mode=0o700)  # User-only permissions
    return rem_home


def get_config_path() -> Path:
    """
    Get path to configuration file (~/.rem/config.yaml).

    Returns:
        Path to configuration file
    """
    return get_rem_home() / "config.yaml"


def config_exists() -> bool:
    """
    Check if configuration file exists.

    Returns:
        True if ~/.rem/config.yaml exists
    """
    return get_config_path().exists()


def load_config() -> dict[str, Any]:
    """
    Load configuration from ~/.rem/config.yaml.

    Set REM_SKIP_CONFIG=1 to skip loading the config file (useful when using .env files).

    Returns:
        Configuration dictionary (empty if file doesn't exist or skipped)
    """
    # Allow skipping config file via environment variable
    if os.environ.get("REM_SKIP_CONFIG", "").lower() in ("1", "true", "yes"):
        logger.debug("Skipping config file (REM_SKIP_CONFIG is set)")
        return {}

    config_path = get_config_path()

    if not config_path.exists():
        logger.debug(f"Configuration file not found: {config_path}")
        return {}

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}
            logger.debug(f"Loaded configuration from {config_path}")
            return config
    except Exception as e:
        logger.warning(f"Failed to load configuration from {config_path}: {e}")
        return {}


def save_config(config: dict[str, Any]) -> None:
    """
    Save configuration to ~/.rem/config.yaml.

    Args:
        config: Configuration dictionary to save
    """
    ensure_config_dir()
    config_path = get_config_path()

    try:
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Configuration saved to {config_path}")
    except Exception as e:
        logger.error(f"Failed to save configuration to {config_path}: {e}")
        raise


def merge_config_to_env(config: dict[str, Any]) -> None:
    """
    Merge configuration file into environment variables.

    This allows Pydantic Settings to pick up values from the config file
    by setting environment variables before settings initialization.

    Precedence:
    - Existing environment variables are NOT overwritten
    - Only sets env vars if they don't already exist

    Args:
        config: Configuration dictionary from ~/.rem/config.yaml

    Example:
        config = {"postgres": {"connection_string": "postgresql://..."}}
        merge_config_to_env(config)
        # Sets POSTGRES__CONNECTION_STRING if not already set
    """
    # Handle custom env vars first
    if "env" in config:
        for key, value in config["env"].items():
            if key not in os.environ:
                os.environ[key] = str(value)
                logger.debug(f"Set env var from config: {key}")

    # Convert nested config to environment variables
    for section, values in config.items():
        if section == "env":
            continue  # Already handled

        if not isinstance(values, dict):
            continue

        for key, value in values.items():
            # Convert to environment variable format (SECTION__KEY)
            env_key = f"{section.upper()}__{key.upper()}"

            # Only set if not already in environment
            if env_key not in os.environ:
                os.environ[env_key] = str(value)
                logger.debug(f"Set env var from config: {env_key}")


def validate_config(config: dict[str, Any]) -> list[str]:
    """
    Validate configuration for required fields.

    Args:
        config: Configuration dictionary

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Postgres connection is required
    postgres = config.get("postgres", {})
    if not postgres.get("connection_string"):
        errors.append("PostgreSQL connection string is required (postgres.connection_string)")

    # Validate connection string format
    conn_str = postgres.get("connection_string", "")
    if conn_str and not conn_str.startswith("postgresql://"):
        errors.append("PostgreSQL connection string must start with 'postgresql://'")

    return errors


def get_default_config() -> dict[str, Any]:
    """
    Get default configuration template for new installations.

    Returns:
        Default configuration dictionary
    """
    return {
        "postgres": {
            "connection_string": "postgresql://rem:rem@localhost:5432/rem",
            "pool_min_size": 5,
            "pool_max_size": 20,
        },
        "llm": {
            "default_model": "openai:gpt-4.1",
            "default_temperature": 0.5,
            # API keys will be prompted for in wizard
            # "openai_api_key": "",
            # "anthropic_api_key": "",
        },
        "s3": {
            "bucket_name": "rem-storage",
            "region": "us-east-1",
            # Optional fields
            # "endpoint_url": "http://localhost:9000",  # For MinIO
            # "access_key_id": "",
            # "secret_access_key": "",
        },
        "env": {
            # Custom environment variables
            # "MY_VAR": "value",
        },
    }
