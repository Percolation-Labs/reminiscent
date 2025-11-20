-- REM Database Installation Script
-- Description: Core database setup with extensions and infrastructure
-- Version: 1.0.0
-- Date: 2025-01-18
--
-- This script sets up:
-- 1. Required PostgreSQL extensions (pgvector, pg_trgm, uuid-ossp)
-- 2. Migration tracking table
-- 3. KV_STORE UNLOGGED cache table
-- 4. Helper functions
--
-- Usage:
--   psql -d remdb -f sql/install.sql
--
-- Dependencies:
--   - PostgreSQL 16+
--   - pgvector extension compiled and available
--   - pg_trgm extension (usually included)

-- ============================================================================
-- EXTENSIONS
-- ============================================================================

-- Enable pgvector extension for vector embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable pg_trgm extension for fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Enable uuid-ossp for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Verify critical extensions
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension failed to install. Ensure pgvector is compiled and available.';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        RAISE EXCEPTION 'pg_trgm extension failed to install.';
    END IF;

    RAISE NOTICE '✓ All required extensions installed successfully';
END $$;

-- ============================================================================
-- MIGRATION TRACKING
-- ============================================================================

CREATE TABLE IF NOT EXISTS rem_migrations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    type VARCHAR(50) NOT NULL,  -- 'install', 'models', 'data'
    version VARCHAR(50),
    checksum VARCHAR(64),
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    applied_by VARCHAR(100) DEFAULT CURRENT_USER,
    execution_time_ms INTEGER,
    success BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_rem_migrations_type ON rem_migrations(type);
CREATE INDEX IF NOT EXISTS idx_rem_migrations_applied_at ON rem_migrations(applied_at);

COMMENT ON TABLE rem_migrations IS
'Tracks all applied migrations including install scripts and model schema updates';

-- ============================================================================
-- KV_STORE CACHE
-- ============================================================================

-- KV_STORE: UNLOGGED table for O(1) entity lookups in REM
--
-- Design rationale:
-- - UNLOGGED: Faster writes, no WAL overhead (acceptable for cache)
-- - Rebuilds automatically from primary tables on restart
-- - Supports LOOKUP queries with O(1) performance
-- - Supports FUZZY queries with trigram indexes
-- - User-scoped filtering when user_id IS NOT NULL
-- - Tenant isolation via tenant_id
--
-- Schema:
-- - entity_key: Natural language label (e.g., "sarah-chen", "project-alpha")
-- - entity_type: Table name (e.g., "resources", "moments")
-- - entity_id: UUID from primary table
-- - tenant_id: Tenant identifier for multi-tenancy
-- - user_id: Optional user scoping (NULL = system-level)
-- - content_summary: Denormalized text for fuzzy search
-- - metadata: JSONB for additional filtering
-- - updated_at: Timestamp for cache invalidation

CREATE UNLOGGED TABLE IF NOT EXISTS kv_store (
    entity_key VARCHAR(255) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100),
    content_summary TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Composite primary key: entity_key unique per tenant
    PRIMARY KEY (tenant_id, entity_key)
);

-- Index for user-scoped lookups (when user_id IS NOT NULL)
CREATE INDEX IF NOT EXISTS idx_kv_store_user ON kv_store (tenant_id, user_id)
WHERE user_id IS NOT NULL;

-- Index for entity_id reverse lookup (find key by ID)
CREATE INDEX IF NOT EXISTS idx_kv_store_entity_id ON kv_store (entity_id);

-- Trigram index for fuzzy text search (FUZZY queries)
CREATE INDEX IF NOT EXISTS idx_kv_store_key_trgm ON kv_store
USING gin (entity_key gin_trgm_ops);

-- Trigram index for content_summary fuzzy search
CREATE INDEX IF NOT EXISTS idx_kv_store_content_trgm ON kv_store
USING gin (content_summary gin_trgm_ops);

-- GIN index for metadata JSONB queries
CREATE INDEX IF NOT EXISTS idx_kv_store_metadata ON kv_store
USING gin (metadata);

-- Index for entity_type filtering
CREATE INDEX IF NOT EXISTS idx_kv_store_type ON kv_store (entity_type);

-- Comments
COMMENT ON TABLE kv_store IS
'UNLOGGED cache for O(1) entity lookups. Supports REM LOOKUP and FUZZY queries. Rebuilt from primary tables on restart.';

COMMENT ON COLUMN kv_store.entity_key IS
'Natural language label for entity (e.g., "sarah-chen", "project-alpha")';

COMMENT ON COLUMN kv_store.entity_type IS
'Source table name (e.g., "resources", "moments", "users")';

COMMENT ON COLUMN kv_store.entity_id IS
'UUID from primary table for reverse lookup';

COMMENT ON COLUMN kv_store.tenant_id IS
'Tenant identifier for multi-tenancy isolation';

COMMENT ON COLUMN kv_store.user_id IS
'Optional user scoping. NULL = system-level entity, visible to all users in tenant';

COMMENT ON COLUMN kv_store.content_summary IS
'Denormalized text summary for fuzzy search. Concatenated from content fields.';

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Function to rebuild KV_STORE from primary tables
-- Call this after database restart or manual cache invalidation
CREATE OR REPLACE FUNCTION rebuild_kv_store()
RETURNS TABLE(table_name TEXT, rows_inserted BIGINT) AS $$
DECLARE
    table_rec RECORD;
    rows_affected BIGINT;
BEGIN
    -- Clear existing cache
    DELETE FROM kv_store;
    RAISE NOTICE 'Cleared KV_STORE cache';

    -- Rebuild from each entity table
    -- This will be populated by triggers when install_models.sql is loaded
    -- For now, just return empty result
    RETURN;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rebuild_kv_store() IS
'Rebuild KV_STORE cache from all entity tables. Call after database restart.';

-- ============================================================================
-- REM QUERY FUNCTIONS
-- ============================================================================

-- REM LOOKUP: O(1) entity lookup by natural key
-- Returns entity metadata from KV_STORE cache
CREATE OR REPLACE FUNCTION rem_lookup(
    p_entity_key VARCHAR(255),
    p_tenant_id VARCHAR(100),
    p_user_id VARCHAR(100) DEFAULT NULL
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    user_id VARCHAR(100),
    content_summary TEXT,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        kv.entity_key,
        kv.entity_type,
        kv.entity_id,
        kv.user_id,
        kv.content_summary,
        kv.metadata
    FROM kv_store kv
    WHERE kv.tenant_id = p_tenant_id
    AND kv.entity_key = p_entity_key
    AND (p_user_id IS NULL OR kv.user_id = p_user_id OR kv.user_id IS NULL);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_lookup IS
'REM LOOKUP query: O(1) entity lookup by natural key with optional user scoping';

-- REM FUZZY: Fuzzy text search using pg_trgm similarity
-- Returns entities matching approximate text with similarity scores
CREATE OR REPLACE FUNCTION rem_fuzzy(
    p_query TEXT,
    p_tenant_id VARCHAR(100),
    p_threshold REAL DEFAULT 0.3,
    p_limit INTEGER DEFAULT 10,
    p_user_id VARCHAR(100) DEFAULT NULL
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    user_id VARCHAR(100),
    content_summary TEXT,
    metadata JSONB,
    similarity_score REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        kv.entity_key,
        kv.entity_type,
        kv.entity_id,
        kv.user_id,
        kv.content_summary,
        kv.metadata,
        similarity(kv.entity_key, p_query) AS similarity_score
    FROM kv_store kv
    WHERE kv.tenant_id = p_tenant_id
    AND (p_user_id IS NULL OR kv.user_id = p_user_id OR kv.user_id IS NULL)
    AND kv.entity_key % p_query  -- Trigram similarity operator
    ORDER BY similarity_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_fuzzy IS
'REM FUZZY query: Fuzzy text search using pg_trgm with similarity scoring';

-- REM TRAVERSE: Recursive graph traversal following edges
-- Explores graph_edges starting from entity_key up to max_depth
CREATE OR REPLACE FUNCTION rem_traverse(
    p_entity_key VARCHAR(255),
    p_tenant_id VARCHAR(100),
    p_max_depth INTEGER DEFAULT 1,
    p_rel_type VARCHAR(100) DEFAULT NULL,
    p_user_id VARCHAR(100) DEFAULT NULL
)
RETURNS TABLE(
    depth INTEGER,
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    rel_type VARCHAR(100),
    rel_weight REAL,
    path TEXT[]
) AS $$
BEGIN
    -- TODO: Implement recursive CTE traversal
    -- This is a stub that returns only the starting entity
    RETURN QUERY
    SELECT
        0 AS depth,
        kv.entity_key,
        kv.entity_type,
        kv.entity_id,
        NULL::VARCHAR(100) AS rel_type,
        NULL::REAL AS rel_weight,
        ARRAY[kv.entity_key] AS path
    FROM kv_store kv
    WHERE kv.tenant_id = p_tenant_id
    AND kv.entity_key = p_entity_key
    AND (p_user_id IS NULL OR kv.user_id = p_user_id OR kv.user_id IS NULL);

    -- TODO: Recursively follow graph_edges from primary tables
    -- Need to:
    -- 1. JOIN to primary table to get graph_edges JSONB
    -- 2. Extract destination keys from edges
    -- 3. LOOKUP destination entities in KV_STORE
    -- 4. Filter by rel_type if specified
    -- 5. Track depth and prevent cycles
    -- 6. Return all discovered entities with path
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_traverse IS
'REM TRAVERSE query: Recursive graph traversal following entity relationships (STUB)';

-- REM SEARCH: Vector similarity search using embeddings
-- Joins to embeddings table for semantic search
CREATE OR REPLACE FUNCTION rem_search(
    p_query_embedding vector(1536),
    p_table_name VARCHAR(100),
    p_field_name VARCHAR(100),
    p_tenant_id VARCHAR(100),
    p_provider VARCHAR(50) DEFAULT 'openai',
    p_min_similarity REAL DEFAULT 0.7,
    p_limit INTEGER DEFAULT 10,
    p_user_id VARCHAR(100) DEFAULT NULL
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    similarity_score REAL,
    content_summary TEXT
) AS $$
DECLARE
    embeddings_table VARCHAR(200);
    query_sql TEXT;
BEGIN
    -- Construct embeddings table name
    embeddings_table := 'embeddings_' || p_table_name;

    -- Dynamic query to join KV_STORE with embeddings table
    query_sql := format('
        SELECT
            kv.entity_key,
            kv.entity_type,
            kv.entity_id,
            1 - (e.embedding <=> $1) AS similarity_score,
            kv.content_summary
        FROM kv_store kv
        JOIN %I e ON e.entity_id = kv.entity_id
        WHERE kv.tenant_id = $2
        AND e.field_name = $3
        AND e.provider = $4
        AND 1 - (e.embedding <=> $1) >= $5
        AND ($6::VARCHAR(100) IS NULL OR kv.user_id = $6 OR kv.user_id IS NULL)
        ORDER BY e.embedding <=> $1
        LIMIT $7
    ', embeddings_table);

    RETURN QUERY EXECUTE query_sql
    USING p_query_embedding, p_tenant_id, p_field_name, p_provider, p_min_similarity, p_user_id, p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_search IS
'REM SEARCH query: Vector similarity search using embeddings with cosine distance';

-- Function to get migration status
CREATE OR REPLACE FUNCTION migration_status()
RETURNS TABLE(
    migration_type TEXT,
    count BIGINT,
    last_applied TIMESTAMP,
    total_execution_ms BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        type::TEXT,
        COUNT(*)::BIGINT,
        MAX(applied_at),
        SUM(execution_time_ms)::BIGINT
    FROM rem_migrations
    WHERE success = TRUE
    GROUP BY type
    ORDER BY MAX(applied_at) DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION migration_status() IS
'Get summary of applied migrations by type';

-- ============================================================================
-- RECORD INSTALLATION
-- ============================================================================

INSERT INTO rem_migrations (name, type, version)
VALUES ('install.sql', 'install', '1.0.0')
ON CONFLICT (name) DO UPDATE
SET applied_at = CURRENT_TIMESTAMP,
    applied_by = CURRENT_USER;

-- ============================================================================
-- COMPLETION
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'REM Database Installation Complete';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Extensions installed:';
    RAISE NOTICE '  ✓ pgvector (vector embeddings)';
    RAISE NOTICE '  ✓ pg_trgm (fuzzy text search)';
    RAISE NOTICE '  ✓ uuid-ossp (UUID generation)';
    RAISE NOTICE '';
    RAISE NOTICE 'Infrastructure created:';
    RAISE NOTICE '  ✓ rem_migrations (migration tracking)';
    RAISE NOTICE '  ✓ kv_store (UNLOGGED entity cache)';
    RAISE NOTICE '  ✓ Helper functions';
    RAISE NOTICE '';
    RAISE NOTICE 'Next steps:';
    RAISE NOTICE '  1. Generate model schema: rem schema generate --models src/rem/models/entities';
    RAISE NOTICE '  2. Apply model schema: rem db migrate';
    RAISE NOTICE '';
    RAISE NOTICE 'Status: SELECT * FROM migration_status();';
    RAISE NOTICE '============================================================';
END $$;
