"""
Centralized schema loading utility for agent schemas.

This module provides a single, consistent implementation for loading
agent schemas from YAML files across the entire codebase (API, CLI, agent factory).

Design Pattern:
- Search standard locations: schemas/agents/, schemas/evaluators/, schemas/
- Support short names: "contract-analyzer" → "schemas/agents/contract-analyzer.yaml"
- Support relative/absolute paths
- Consistent error messages and logging

Usage:
    # From API
    schema = load_agent_schema("rem")

    # From CLI with custom path
    schema = load_agent_schema("./my-agent.yaml")

    # From agent factory
    schema = load_agent_schema("contract-analyzer")

TODO: Git FS Integration
    The schema loader currently uses importlib.resources for package schemas
    and direct filesystem access for custom paths. The FS abstraction layer
    (rem.services.fs.FS) could be used to abstract storage backends:

    - Local filesystem (current)
    - Git repositories (GitService)
    - S3 (via FS provider)

    This would enable loading schemas from versioned Git repos or S3 buckets
    without changing the API. The FS provider pattern already exists and just
    needs integration testing with the schema loader.

    Example future usage:
        # Load from Git at specific version
        schema = load_agent_schema("git://rem/schemas/agents/rem.yaml?ref=v1.0.0")

        # Load from S3
        schema = load_agent_schema("s3://rem-schemas/agents/cv-parser.yaml")

Schema Caching Status:

    ✅ IMPLEMENTED: Filesystem Schema Caching (2025-11-22)
       - Schemas loaded from package resources cached indefinitely in _fs_schema_cache
       - No TTL needed (immutable, versioned with code)
       - Lazy-loaded on first access
       - Custom paths not cached (may change during development)

    TODO: Database Schema Caching (Future)
       - Schemas loaded from schemas table (SchemaRepository)
       - Will require TTL for cache invalidation (5-15 minutes)
       - May change at runtime via admin updates
       - Cache key: (schema_name, version) → (schema_dict, timestamp)
       - Implementation ready in _db_schema_cache and _db_schema_ttl

    Benefits Achieved:
    - ✅ Eliminated disk I/O for repeated schema loads
    - ✅ Faster agent creation (critical for API latency)
    - 🔲 Database query reduction (pending DB schema implementation)

    Future Enhancement (when database schemas are implemented):
        import time

        _db_schema_cache: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
        _db_schema_ttl: int = 300  # 5 minutes

        async def load_agent_schema_from_db(name: str, version: str | None = None):
            cache_key = (name, version or "latest")
            if cache_key in _db_schema_cache:
                schema, timestamp = _db_schema_cache[cache_key]
                if time.time() - timestamp < _db_schema_ttl:
                    return schema
            # Load from DB and cache with TTL
            from rem.services.repositories import schema_repository
            schema = await schema_repository.get_by_name(name, version)
            _db_schema_cache[cache_key] = (schema, time.time())
            return schema

    Related:
    - rem/src/rem/agentic/providers/pydantic_ai.py (create_agent factory)
    - rem/src/rem/services/repositories/schema_repository.py (database schemas)
"""

import importlib.resources
from pathlib import Path
from typing import Any, cast

import yaml
from loguru import logger


# Standard search paths for agent/evaluator schemas (in priority order)
SCHEMA_SEARCH_PATHS = [
    "schemas/agents/{name}.yaml",          # Top-level agents (e.g., rem.yaml)
    "schemas/agents/core/{name}.yaml",     # Core system agents
    "schemas/agents/examples/{name}.yaml", # Example agents
    "schemas/evaluators/{name}.yaml",      # Nested evaluators (e.g., hello-world/default)
    "schemas/evaluators/rem/{name}.yaml",  # REM evaluators (e.g., lookup-correctness)
    "schemas/{name}.yaml",                 # Generic schemas
]

# In-memory cache for filesystem schemas (no TTL - immutable)
_fs_schema_cache: dict[str, dict[str, Any]] = {}

# Future: Database schema cache (with TTL - mutable)
# Will be used when loading schemas from database (SchemaRepository)
# _db_schema_cache: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
# _db_schema_ttl: int = 300  # 5 minutes in seconds


def _load_schema_from_database(schema_name: str, user_id: str) -> dict[str, Any] | None:
    """
    Load schema from database using LOOKUP query.

    This function is synchronous but calls async database operations.
    It's designed to be called from load_agent_schema() which is sync.

    Args:
        schema_name: Schema name to lookup
        user_id: User ID for data scoping

    Returns:
        Schema spec (dict) if found, None otherwise

    Raises:
        RuntimeError: If database connection fails
    """
    import asyncio

    # Check if we're already in an async context
    try:
        loop = asyncio.get_running_loop()
        # We're in an async context - can't use asyncio.run()
        # This shouldn't happen in normal usage since load_agent_schema is called from sync contexts
        logger.warning(
            "Database schema lookup called from async context. "
            "This may cause issues. Consider using async version of load_agent_schema."
        )
        return None
    except RuntimeError:
        # Not in async context - safe to use asyncio.run()
        pass

    async def _async_lookup():
        """Async helper to query database."""
        from rem.services.postgres import get_postgres_service
        from rem.models.entities import Schema

        db = get_postgres_service()
        if not db:
            logger.debug("PostgreSQL service not available for schema lookup")
            return None

        try:
            await db.connect()

            # Use REM LOOKUP query to find schema
            query = f"LOOKUP '{schema_name}' FROM schemas"
            logger.debug(f"Executing: {query} (user_id={user_id})")

            result = await db.execute_rem_query(
                query=query,
                user_id=user_id,
            )

            if result and isinstance(result, dict):
                # LOOKUP returns single entity or None
                # Extract spec field (JSON Schema)
                spec = result.get("spec")
                if spec and isinstance(spec, dict):
                    logger.debug(f"Found schema in database: {schema_name}")
                    return spec

            logger.debug(f"Schema not found in database: {schema_name}")
            return None

        except Exception as e:
            logger.debug(f"Database schema lookup error: {e}")
            return None
        finally:
            await db.disconnect()

    # Run async lookup in new event loop
    return asyncio.run(_async_lookup())


def load_agent_schema(
    schema_name_or_path: str,
    use_cache: bool = True,
    user_id: str | None = None,
    enable_db_fallback: bool = True,
) -> dict[str, Any]:
    """
    Load agent schema from YAML file with unified search logic and caching.

    Filesystem schemas are cached indefinitely (immutable, versioned with code).
    Database schemas (future) will be cached with TTL for invalidation.

    Handles path resolution automatically:
    - "rem" → searches schemas/agents/rem.yaml (top-level)
    - "moment-builder" → searches schemas/agents/core/moment-builder.yaml
    - "contract-analyzer" → searches schemas/agents/examples/contract-analyzer.yaml
    - "core/moment-builder" → searches schemas/agents/core/moment-builder.yaml
    - "/absolute/path.yaml" → loads directly
    - "relative/path.yaml" → loads relative to cwd

    Search Order:
    1. Check cache (if use_cache=True and schema found in FS cache)
    2. Exact path if it exists (absolute or relative)
    3. Custom paths from rem.register_schema_path() and SCHEMA__PATHS env var
    4. Package resources: schemas/agents/{name}.yaml (top-level)
    5. Package resources: schemas/agents/core/{name}.yaml
    6. Package resources: schemas/agents/examples/{name}.yaml
    7. Package resources: schemas/evaluators/{name}.yaml
    8. Package resources: schemas/{name}.yaml
    9. Database LOOKUP: schemas table (if enable_db_fallback=True and user_id provided)

    Args:
        schema_name_or_path: Schema name or file path
            Examples: "rem-query-agent", "contract-analyzer", "./my-schema.yaml"
        use_cache: If True, uses in-memory cache for filesystem schemas
        user_id: User ID for database schema lookup (required for DB fallback)
        enable_db_fallback: If True, falls back to database LOOKUP when file not found

    Returns:
        Agent schema as dictionary

    Raises:
        FileNotFoundError: If schema not found in any search location (filesystem + database)
        yaml.YAMLError: If schema file is invalid YAML

    Examples:
        >>> # Load by short name (cached after first load)
        >>> schema = load_agent_schema("contract-analyzer")
        >>>
        >>> # Load from custom path (not cached - custom paths may change)
        >>> schema = load_agent_schema("./my-agent.yaml")
        >>>
        >>> # Load evaluator schema (cached)
        >>> schema = load_agent_schema("rem-lookup-correctness")
        >>>
        >>> # Load custom user schema from database
        >>> schema = load_agent_schema("my-custom-agent", user_id="user-123")
    """
    # Normalize the name for cache key
    cache_key = str(schema_name_or_path).replace('agents/', '').replace('schemas/', '').replace('evaluators/', '').replace('core/', '').replace('examples/', '')
    if cache_key.endswith('.yaml') or cache_key.endswith('.yml'):
        cache_key = cache_key.rsplit('.', 1)[0]

    # Check cache first (only for package resources, not custom paths)
    path = Path(schema_name_or_path)
    is_custom_path = path.exists() or '/' in str(schema_name_or_path) or '\\' in str(schema_name_or_path)

    if use_cache and not is_custom_path and cache_key in _fs_schema_cache:
        logger.debug(f"Loading schema from cache: {cache_key}")
        return _fs_schema_cache[cache_key]

    # 1. Try exact path first (absolute or relative to cwd)
    if path.exists():
        logger.debug(f"Loading schema from exact path: {path}")
        with open(path, "r") as f:
            schema = yaml.safe_load(f)
        logger.debug(f"Loaded schema with keys: {list(schema.keys())}")
        # Don't cache custom paths (they may change)
        return cast(dict[str, Any], schema)

    # 2. Normalize name for package resource search
    base_name = cache_key

    # 3. Try custom schema paths (from registry + SCHEMA__PATHS env var)
    from ..registry import get_schema_paths

    custom_paths = get_schema_paths()
    for custom_dir in custom_paths:
        # Try various patterns within each custom directory
        for pattern in [
            f"{base_name}.yaml",
            f"{base_name}.yml",
            f"agents/{base_name}.yaml",
            f"evaluators/{base_name}.yaml",
        ]:
            custom_path = Path(custom_dir) / pattern
            if custom_path.exists():
                logger.debug(f"Loading schema from custom path: {custom_path}")
                with open(custom_path, "r") as f:
                    schema = yaml.safe_load(f)
                logger.debug(f"Loaded schema with keys: {list(schema.keys())}")
                # Don't cache custom paths (they may change during development)
                return cast(dict[str, Any], schema)

    # 4. Try package resources with standard search paths
    for search_pattern in SCHEMA_SEARCH_PATHS:
        search_path = search_pattern.format(name=base_name)

        try:
            # Use importlib.resources to find schema in installed package
            schema_ref = importlib.resources.files("rem") / search_path
            schema_path = Path(str(schema_ref))

            if schema_path.exists():
                logger.debug(f"Loading schema from package: {search_path}")
                with open(schema_path, "r") as f:
                    schema = yaml.safe_load(f)
                logger.debug(f"Loaded schema with keys: {list(schema.keys())}")

                # Cache filesystem schemas (immutable, safe to cache indefinitely)
                if use_cache:
                    _fs_schema_cache[cache_key] = schema
                    logger.debug(f"Cached schema: {cache_key}")

                return cast(dict[str, Any], schema)
        except Exception as e:
            logger.debug(f"Could not load from {search_path}: {e}")
            continue

    # 5. Try database LOOKUP fallback (if enabled and user_id provided)
    if enable_db_fallback and user_id:
        try:
            logger.debug(f"Attempting database LOOKUP for schema: {base_name} (user_id={user_id})")
            db_schema = _load_schema_from_database(base_name, user_id)
            if db_schema:
                logger.info(f"✅ Loaded schema from database: {base_name} (user_id={user_id})")
                return db_schema
        except Exception as e:
            logger.debug(f"Database schema lookup failed: {e}")
            # Fall through to error below

    # 6. Schema not found in any location
    searched_paths = [pattern.format(name=base_name) for pattern in SCHEMA_SEARCH_PATHS]

    custom_paths_note = ""
    if custom_paths:
        custom_paths_note = f"\n  - Custom paths: {', '.join(custom_paths)}"

    db_search_note = ""
    if enable_db_fallback:
        if user_id:
            db_search_note = f"\n  - Database: LOOKUP '{base_name}' FROM schemas WHERE user_id='{user_id}' (no match)"
        else:
            db_search_note = "\n  - Database: (skipped - no user_id provided)"

    raise FileNotFoundError(
        f"Schema not found: {schema_name_or_path}\n"
        f"Searched locations:\n"
        f"  - Exact path: {path}"
        f"{custom_paths_note}\n"
        f"  - Package resources: {', '.join(searched_paths)}"
        f"{db_search_note}"
    )


def validate_agent_schema(schema: dict[str, Any]) -> bool:
    """
    Validate agent schema structure.

    Basic validation checks:
    - Has 'type' field (should be 'object')
    - Has 'description' field (system prompt)
    - Has 'properties' field (output schema)

    Args:
        schema: Agent schema dict

    Returns:
        True if valid

    Raises:
        ValueError: If schema is invalid
    """
    if not isinstance(schema, dict):
        raise ValueError(f"Schema must be a dict, got {type(schema)}")

    if schema.get('type') != 'object':
        raise ValueError(f"Schema type must be 'object', got {schema.get('type')}")

    if 'description' not in schema:
        raise ValueError("Schema must have 'description' field (system prompt)")

    if 'properties' not in schema:
        logger.warning("Schema missing 'properties' field - agent will have no structured output")

    logger.debug("Schema validation passed")
    return True
