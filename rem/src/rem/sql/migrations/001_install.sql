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
    graph_edges JSONB DEFAULT '[]'::jsonb,  -- Cached edges for fast graph traversal
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

-- GIN index for graph_edges JSONB queries (graph traversal)
CREATE INDEX IF NOT EXISTS idx_kv_store_graph_edges ON kv_store
USING gin (graph_edges);

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
--
-- IMPORTANT: You should NOT need to call this during normal operations!
-- KV store is automatically populated via triggers on INSERT/UPDATE/DELETE.
--
-- Only call this function after:
--   1. Database crash/restart (UNLOGGED table lost)
--   2. Backup restoration (UNLOGGED tables not backed up)
--   3. Bulk imports that bypass triggers (COPY, pg_restore --disable-triggers)
--
-- Usage: SELECT * FROM rebuild_kv_store();
CREATE OR REPLACE FUNCTION rebuild_kv_store()
RETURNS TABLE(table_name TEXT, rows_inserted BIGINT) AS $$
DECLARE
    table_rec RECORD;
    rows_affected BIGINT;
BEGIN
    -- Clear existing cache
    DELETE FROM kv_store;
    RAISE NOTICE 'Cleared KV_STORE cache';

    -- Rebuild from each entity table that has a KV store trigger
    -- This query finds all tables with _kv_store triggers
    FOR table_rec IN
        SELECT DISTINCT event_object_table as tbl
        FROM information_schema.triggers
        WHERE trigger_name LIKE '%_kv_store'
        AND trigger_schema = 'public'
        ORDER BY event_object_table
    LOOP
        -- Force trigger execution by updating all non-deleted rows
        -- This is more efficient than re-inserting
        EXECUTE format('
            UPDATE %I
            SET updated_at = updated_at
            WHERE deleted_at IS NULL
        ', table_rec.tbl);

        GET DIAGNOSTICS rows_affected = ROW_COUNT;

        table_name := table_rec.tbl;
        rows_inserted := rows_affected;
        RETURN NEXT;

        RAISE NOTICE 'Rebuilt % KV entries for %', rows_affected, table_rec.tbl;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rebuild_kv_store() IS
'Rebuild KV_STORE cache from all entity tables. Call after database restart.';

-- ============================================================================
-- REM QUERY FUNCTIONS
-- ============================================================================

-- REM LOOKUP: O(1) entity lookup by natural key
-- Returns structured columns extracted from entity records
-- Parameters: entity_key, tenant_id (for backward compat), user_id (actual filter)
-- Note: tenant_id parameter exists for backward compatibility but is ignored
CREATE OR REPLACE FUNCTION rem_lookup(
    p_entity_key VARCHAR(255),
    p_tenant_id VARCHAR(100),
    p_user_id VARCHAR(100)
)
RETURNS TABLE(
    entity_type VARCHAR(100),
    data JSONB
) AS $$
DECLARE
    entity_table VARCHAR(100);
    query_sql TEXT;
BEGIN
    -- Use p_user_id for filtering (p_tenant_id ignored for backward compat)
    -- First lookup in KV store to get entity_type (table name)
    SELECT kv.entity_type INTO entity_table
    FROM kv_store kv
    WHERE kv.user_id = p_user_id
    AND kv.entity_key = p_entity_key;

    -- If not found, return empty
    IF entity_table IS NULL THEN
        RETURN;
    END IF;

    -- Fetch raw record from underlying table as JSONB
    -- LLMs can handle unstructured JSON - no need for schema assumptions
    query_sql := format('
        SELECT
            %L::VARCHAR(100) AS entity_type,
            row_to_json(t)::jsonb AS data
        FROM %I t
        WHERE t.user_id = $1
        AND t.name = $2
        AND t.deleted_at IS NULL
    ', entity_table, entity_table);

    RETURN QUERY EXECUTE query_sql USING p_user_id, p_entity_key;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_lookup IS
'REM LOOKUP query: O(1) entity lookup by natural key. Returns raw entity data as JSONB for LLM consumption. tenant_id parameter exists for backward compatibility but filtering uses user_id.';

-- REM FETCH: Fetch full entity records from multiple tables
-- Takes JSONB mapping of {table_name: [entity_keys]}, fetches all records
-- Returns complete entity records as JSONB (not just KV store metadata)
CREATE OR REPLACE FUNCTION rem_fetch(
    p_entities_by_table JSONB,
    p_user_id VARCHAR(100)
)
RETURNS TABLE(
    entity_key TEXT,
    entity_type TEXT,
    entity_record JSONB
) AS $$
DECLARE
    table_name TEXT;
    entity_keys TEXT[];
    query_sql TEXT;
    result_record RECORD;
BEGIN
    -- Iterate over each table in the JSONB object
    FOR table_name IN SELECT jsonb_object_keys(p_entities_by_table)
    LOOP
        -- Extract array of keys for this table
        entity_keys := ARRAY(
            SELECT jsonb_array_elements_text(p_entities_by_table->table_name)
        );

        -- Build dynamic query for this table
        query_sql := format('
            SELECT
                t.name AS entity_key,
                %L AS entity_type,
                row_to_json(t)::jsonb AS entity_record
            FROM %I t
            WHERE t.user_id = $1
            AND t.name = ANY($2)
            AND t.deleted_at IS NULL
        ', table_name, table_name);

        -- Execute and return rows for this table
        FOR result_record IN EXECUTE query_sql USING p_user_id, entity_keys
        LOOP
            entity_key := result_record.entity_key;
            entity_type := result_record.entity_type;
            entity_record := result_record.entity_record;
            RETURN NEXT;
        END LOOP;
    END LOOP;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_fetch IS
'REM FETCH: Fetch full entity records (all columns as JSONB) from multiple tables. Takes JSONB mapping {table_name: [keys]}, fetches all records, returns unified result set. Use for hydrating LOOKUP, FUZZY, SEARCH, and TRAVERSE results.';

-- REM FUZZY: Fuzzy text search using pg_trgm similarity
-- Returns raw entity data as JSONB for LLM consumption
CREATE OR REPLACE FUNCTION rem_fuzzy(
    p_query TEXT,
    p_tenant_id VARCHAR(100),
    p_threshold REAL DEFAULT 0.3,
    p_limit INTEGER DEFAULT 10,
    p_user_id VARCHAR(100) DEFAULT NULL
)
RETURNS TABLE(
    entity_type VARCHAR(100),
    similarity_score REAL,
    data JSONB
) AS $$
DECLARE
    kv_matches RECORD;
    entities_by_table JSONB := '{}'::jsonb;
    table_keys JSONB;
BEGIN
    -- First, find matching keys in KV store with similarity scores
    -- Group by table to prepare for batch fetch
    FOR kv_matches IN
        SELECT
            kv.entity_key,
            kv.entity_type,
            similarity(kv.entity_key, p_query) AS sim_score
        FROM kv_store kv
        WHERE kv.user_id = COALESCE(p_user_id, p_tenant_id)
        AND kv.entity_key % p_query  -- Trigram similarity operator
        AND similarity(kv.entity_key, p_query) >= p_threshold
        ORDER BY sim_score DESC
        LIMIT p_limit
    LOOP
        -- Build JSONB mapping {table: [keys]}
        IF entities_by_table ? kv_matches.entity_type THEN
            table_keys := entities_by_table->kv_matches.entity_type;
            entities_by_table := jsonb_set(
                entities_by_table,
                ARRAY[kv_matches.entity_type],
                table_keys || jsonb_build_array(kv_matches.entity_key)
            );
        ELSE
            entities_by_table := jsonb_set(
                entities_by_table,
                ARRAY[kv_matches.entity_type],
                jsonb_build_array(kv_matches.entity_key)
            );
        END IF;
    END LOOP;

    -- Fetch full records using rem_fetch helper
    -- Return raw entity data as JSONB for LLM consumption
    -- Use p_user_id (not p_tenant_id) for actual filtering
    RETURN QUERY
    SELECT
        f.entity_type::VARCHAR(100),
        similarity(f.entity_key, p_query) AS similarity_score,
        f.entity_record AS data
    FROM rem_fetch(entities_by_table, COALESCE(p_user_id, p_tenant_id)) f
    ORDER BY similarity_score DESC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_fuzzy IS
'REM FUZZY query: Fuzzy text search using pg_trgm. Returns raw entity data as JSONB for LLM consumption. tenant_id parameter exists for backward compatibility but filtering uses user_id.';

-- REM TRAVERSE: Moved to 002_install_models.sql (after entity tables are created)
-- See 002_install_models.sql for the full rem_traverse function with keys_only parameter

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
    entity_type VARCHAR(100),
    similarity_score REAL,
    data JSONB
) AS $$
DECLARE
    embeddings_table VARCHAR(200);
    source_table VARCHAR(100);
    query_sql TEXT;
BEGIN
    -- Construct embeddings table name
    embeddings_table := 'embeddings_' || p_table_name;
    source_table := p_table_name;

    -- Dynamic query to join source table with embeddings table
    -- Returns raw entity data as JSONB for LLM consumption
    -- Note: Using inner product for OpenAI embeddings (normalized vectors)
    -- Inner product <#> returns negative value, so we negate it to get [0, 1]
    -- where 1 = perfect match, 0 = orthogonal
    query_sql := format('
        SELECT
            %L::VARCHAR(100) AS entity_type,
            (1.0 - (e.embedding <#> $1) * -1.0)::REAL AS similarity_score,
            row_to_json(t)::jsonb AS data
        FROM %I t
        JOIN %I e ON e.entity_id = t.id
        WHERE t.user_id = $2
        AND e.field_name = $3
        AND e.provider = $4
        AND (1.0 - (e.embedding <#> $1) * -1.0) >= $5
        AND t.deleted_at IS NULL
        ORDER BY e.embedding <#> $1 DESC
        LIMIT $6
    ', source_table, source_table, embeddings_table);

    RETURN QUERY EXECUTE query_sql
    USING p_query_embedding, p_user_id, p_field_name, p_provider, p_min_similarity, p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_search IS
'REM SEARCH query: Vector similarity search using inner product for OpenAI normalized embeddings. Returns raw entity data as JSONB for LLM consumption, scoped to user_id';

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
