"""
Alembic environment configuration for REM.

This module configures Alembic to:
1. Load database URL from REM settings (environment variables)
2. Build SQLAlchemy metadata from Pydantic models
3. Enable autogenerate for migration diffs
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Import REM settings
from rem.settings import settings

# Import Pydantic to SQLAlchemy converter
from rem.services.postgres.pydantic_to_sqlalchemy import get_target_metadata

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Get the database URL from REM settings
def get_url() -> str:
    """Build PostgreSQL URL from REM settings."""
    pg = settings.postgres

    # Build connection URL
    url = f"postgresql://{pg.user}"
    if pg.password:
        url += f":{pg.password}"
    url += f"@{pg.host}:{pg.port}/{pg.database}"

    return url

# Override the sqlalchemy.url in config
config.set_main_option("sqlalchemy.url", get_url())

# Build metadata from Pydantic models
target_metadata = get_target_metadata()


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
