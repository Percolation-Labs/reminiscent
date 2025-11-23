"""
REM Query SQL Templates.

All SQL queries for REM operations are defined here with proper parameterization.
This separates query logic from business logic and makes queries easier to maintain.

Design Pattern:
- Each query is a named constant with $1, $2, etc. placeholders
- Query parameters are documented in docstrings
- Queries delegate to PostgreSQL functions for performance
- All queries include tenant isolation
"""

# LOOKUP Query
# Delegates to rem_lookup() PostgreSQL function
# Returns raw JSONB data for LLM consumption
LOOKUP_QUERY = """
SELECT
    entity_type,
    data
FROM rem_lookup($1, $2, $3)
"""
# Parameters:
# $1: entity_key (str)
# $2: tenant_id (str)
# $3: user_id (str | None)
# Returns:
# - entity_type: Table name (e.g., "resources", "users")
# - data: Complete entity record as JSONB


# FUZZY Query
# Delegates to rem_fuzzy() PostgreSQL function
# Returns raw JSONB data with similarity scores
FUZZY_QUERY = """
SELECT
    entity_type,
    similarity_score,
    data
FROM rem_fuzzy($1, $2, $3, $4, $5)
"""
# Parameters:
# $1: query_text (str)
# $2: tenant_id (str)
# $3: threshold (float)
# $4: limit (int)
# $5: user_id (str | None)
# Returns:
# - entity_type: Table name (e.g., "resources", "files")
# - similarity_score: Fuzzy match score (0.0-1.0)
# - data: Complete entity record as JSONB


# SEARCH Query
# Delegates to rem_search() PostgreSQL function
# Returns raw JSONB data with similarity scores
SEARCH_QUERY = """
SELECT
    entity_type,
    similarity_score,
    data
FROM rem_search($1, $2, $3, $4, $5, $6, $7, $8)
"""
# Parameters:
# $1: query_embedding (list[float])
# $2: table_name (str)
# $3: field_name (str)
# $4: tenant_id (str)
# $5: provider (str)
# $6: min_similarity (float)
# $7: limit (int)
# $8: user_id (str | None)
# Returns:
# - entity_type: Table name (e.g., "resources", "moments")
# - similarity_score: Vector similarity (0.0-1.0)
# - data: Complete entity record as JSONB


# TRAVERSE Query
# Delegates to rem_traverse() PostgreSQL function
TRAVERSE_QUERY = """
SELECT
    depth,
    entity_key,
    entity_type,
    entity_id,
    rel_type,
    rel_weight,
    path
FROM rem_traverse($1, $2, $3, $4, $5, $6)
"""
# Parameters:
# $1: start_key (str)
# $2: tenant_id (str)
# $3: user_id (str | None)
# $4: max_depth (int)
# $5: rel_type (str | None) - single type, not array
# $6: keys_only (bool)


# SQL Query Builder
# Direct SQL queries with tenant isolation
def build_sql_query(table_name: str, where_clause: str, tenant_id: str, limit: int | None = None) -> str:
    """
    Build SQL query with tenant isolation.

    Args:
        table_name: Table name (e.g., "resources", "moments")
        where_clause: WHERE clause (e.g., "moment_type='meeting'")
        tenant_id: Tenant identifier for isolation
        limit: Optional result limit

    Returns:
        Parameterized SQL query string

    Note:
        This builds a dynamic query. Consider using prepared statements
        or query builders like SQLAlchemy for production.
    """
    # Sanitize table name (basic validation)
    allowed_tables = ["resources", "moments", "messages", "users", "files"]
    if table_name not in allowed_tables:
        raise ValueError(f"Invalid table name: {table_name}")

    # Build query with tenant isolation
    where_clause = where_clause or "1=1"
    query = f"SELECT * FROM {table_name} WHERE tenant_id = $1 AND ({where_clause})"

    if limit:
        query += f" LIMIT {int(limit)}"

    return query


# Helper: Get query parameters for LOOKUP
def get_lookup_params(entity_key: str, tenant_id: str, user_id: str | None = None) -> tuple:
    """Get parameters for LOOKUP query."""
    return (entity_key, tenant_id, user_id)


# Helper: Get query parameters for FUZZY
def get_fuzzy_params(
    query_text: str,
    tenant_id: str,
    threshold: float = 0.7,
    limit: int = 10,
    user_id: str | None = None,
) -> tuple:
    """Get parameters for FUZZY query."""
    return (query_text, tenant_id, threshold, limit, user_id)


# Helper: Get query parameters for SEARCH
def get_search_params(
    query_embedding: list[float],
    table_name: str,
    field_name: str,
    tenant_id: str,
    provider: str,
    min_similarity: float = 0.7,
    limit: int = 10,
    user_id: str | None = None,
) -> tuple:
    """
    Get parameters for SEARCH query.

    Note: provider parameter is required (no default) - should come from settings.
    """
    return (
        str(query_embedding),
        table_name,
        field_name,
        tenant_id,
        provider,
        min_similarity,
        limit,
        user_id,
    )


# Helper: Get query parameters for TRAVERSE
def get_traverse_params(
    start_key: str,
    tenant_id: str,
    user_id: str | None,
    max_depth: int = 1,
    rel_type: str | None = None,
    keys_only: bool = False,
) -> tuple:
    """
    Get parameters for TRAVERSE query.

    Note: rel_type is singular (not array) - PostgreSQL function filters by single type.
    If you need multiple types, call traverse multiple times or update the function.
    """
    return (start_key, tenant_id, user_id, max_depth, rel_type, keys_only)
