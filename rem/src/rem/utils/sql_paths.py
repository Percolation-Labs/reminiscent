"""Utilities for resolving SQL file paths.

Handles package SQL directory resolution and user migrations.

Convention for user migrations:
    Place custom SQL files in `./sql/migrations/` relative to your project root.
    Files should be numbered (e.g., `100_custom_table.sql`) to control execution order.
    Package migrations (001-099) run first, then user migrations (100+).
"""

from pathlib import Path
from typing import List, Optional
import importlib.resources

# Convention: Default location for user-maintained migrations
USER_SQL_DIR_CONVENTION = "sql"


def get_package_sql_dir() -> Path:
    """Get the SQL directory from the installed rem package.

    Returns:
        Path to the package's sql directory

    Raises:
        FileNotFoundError: If the SQL directory cannot be found
    """
    try:
        # Use importlib.resources for Python 3.9+
        sql_ref = importlib.resources.files("rem") / "sql"
        package_sql = Path(str(sql_ref))
        if package_sql.exists():
            return package_sql
    except (AttributeError, TypeError):
        pass

    # Fallback: use __file__ to find package location
    try:
        import rem
        package_sql = Path(rem.__file__).parent / "sql"
        if package_sql.exists():
            return package_sql
    except (ImportError, AttributeError):
        pass

    # Development fallback: check relative to cwd
    dev_sql = Path("src/rem/sql")
    if dev_sql.exists():
        return dev_sql

    raise FileNotFoundError(
        "Could not locate rem SQL directory. "
        "Ensure remdb is properly installed or run from the source directory."
    )


def get_package_migrations_dir() -> Path:
    """Get the migrations directory from the installed rem package.

    Returns:
        Path to the package's migrations directory
    """
    return get_package_sql_dir() / "migrations"


def get_user_sql_dir() -> Optional[Path]:
    """Get the conventional user SQL directory if it exists.

    Looks for `./sql/` relative to the current working directory.
    This follows the convention for user-maintained migrations.

    Returns:
        Path to user sql directory if it exists, None otherwise
    """
    user_sql = Path.cwd() / USER_SQL_DIR_CONVENTION
    if user_sql.exists() and user_sql.is_dir():
        return user_sql
    return None


def list_package_migrations() -> List[Path]:
    """List all migration files in the package.

    Returns:
        Sorted list of migration file paths
    """
    try:
        migrations_dir = get_package_migrations_dir()
        if migrations_dir.exists():
            return sorted(
                f for f in migrations_dir.glob("*.sql")
                if f.name[0].isdigit()  # Only numbered migrations
            )
    except FileNotFoundError:
        pass

    return []


def list_user_migrations() -> List[Path]:
    """List all migration files in the user's sql/migrations directory.

    Returns:
        Sorted list of user migration file paths
    """
    user_sql = get_user_sql_dir()
    if user_sql:
        migrations_dir = user_sql / "migrations"
        if migrations_dir.exists():
            return sorted(
                f for f in migrations_dir.glob("*.sql")
                if f.name[0].isdigit()  # Only numbered migrations
            )
    return []


def list_all_migrations() -> List[Path]:
    """List all migration files from package and user directories.

    Collects migrations from:
    1. Package migrations directory
    2. User directory (./sql/migrations/) if it exists

    Files are sorted by name, so use numbered prefixes to control order:
    - 001-099: Reserved for package migrations
    - 100+: Recommended for user migrations

    Returns:
        Sorted list of all migration file paths (by filename)
    """
    all_migrations = []
    seen_names = set()

    # Package migrations first
    for f in list_package_migrations():
        if f.name not in seen_names:
            all_migrations.append(f)
            seen_names.add(f.name)

    # User migrations second
    for f in list_user_migrations():
        if f.name not in seen_names:
            all_migrations.append(f)
            seen_names.add(f.name)

    return sorted(all_migrations, key=lambda p: p.name)
