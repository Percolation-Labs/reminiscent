"""
Centralized schema loading utility for agent schemas.

This module provides a single, consistent implementation for loading
agent schemas from YAML files across the entire codebase (API, CLI, agent factory).

Design Pattern:
- Search standard locations: schemas/agents/, schemas/evaluators/, schemas/
- Support short names: "contract-analyzer" → "schemas/agents/contract-analyzer.yaml"
- Support relative/absolute paths
- Consistent error messages and logging
i
Usage:
    # From API
    schema = load_agent_schema("rem")

    # From CLI with custom path
    schema = load_agent_schema("./my-agent.yaml")

    # From agent factory
    schema = load_agent_schema("contract-analyzer")

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
from typing import Any

import yaml
from loguru import logger


# Standard search paths for agent schemas (in priority order)
SCHEMA_SEARCH_PATHS = [
    "schemas/agents/{name}.yaml",
    "schemas/evaluators/{name}.yaml",
    "schemas/{name}.yaml",
]

# In-memory cache for filesystem schemas (no TTL - immutable)
_fs_schema_cache: dict[str, dict[str, Any]] = {}

# Future: Database schema cache (with TTL - mutable)
# Will be used when loading schemas from database (SchemaRepository)
# _db_schema_cache: dict[tuple[str, str], tuple[dict[str, Any], float]] = {}
# _db_schema_ttl: int = 300  # 5 minutes in seconds


def load_agent_schema(schema_name_or_path: str, use_cache: bool = True) -> dict[str, Any]:
    """
    Load agent schema from YAML file with unified search logic and caching.

    Filesystem schemas are cached indefinitely (immutable, versioned with code).
    Database schemas (future) will be cached with TTL for invalidation.

    Handles path resolution automatically:
    - "contract-analyzer" → searches schemas/agents/contract-analyzer.yaml
    - "agents/cv-parser" → searches schemas/agents/cv-parser.yaml
    - "/absolute/path.yaml" → loads directly
    - "relative/path.yaml" → loads relative to cwd

    Search Order:
    1. Check cache (if use_cache=True and schema found in FS cache)
    2. Exact path if it exists (absolute or relative)
    3. Package resources: schemas/agents/{name}.yaml
    4. Package resources: schemas/evaluators/{name}.yaml
    5. Package resources: schemas/{name}.yaml

    Args:
        schema_name_or_path: Schema name or file path
            Examples: "rem-query-agent", "contract-analyzer", "./my-schema.yaml"
        use_cache: If True, uses in-memory cache for filesystem schemas

    Returns:
        Agent schema as dictionary

    Raises:
        FileNotFoundError: If schema not found in any search location
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
    """
    # Normalize the name for cache key
    cache_key = str(schema_name_or_path).replace('agents/', '').replace('schemas/', '').replace('evaluators/', '')
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
        return schema

    # 2. Normalize name for package resource search
    base_name = cache_key

    # 3. Try package resources with standard search paths
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

                return schema
        except Exception as e:
            logger.debug(f"Could not load from {search_path}: {e}")
            continue

    # 4. Schema not found in any location
    searched_paths = [pattern.format(name=base_name) for pattern in SCHEMA_SEARCH_PATHS]
    raise FileNotFoundError(
        f"Schema not found: {schema_name_or_path}\n"
        f"Searched locations:\n"
        f"  - Exact path: {path}\n"
        f"  - Package resources: {', '.join(searched_paths)}"
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
