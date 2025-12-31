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
-- NORMALIZATION HELPER
-- ============================================================================

-- Normalize entity keys to lower-kebab-case for consistent lookups
-- "Mood Disorder" -> "mood-disorder"
-- "mood_disorder" -> "mood-disorder"
-- "MoodDisorder" -> "mood-disorder"
CREATE OR REPLACE FUNCTION normalize_key(input TEXT)
RETURNS TEXT AS $$
BEGIN
    RETURN lower(
        regexp_replace(
            regexp_replace(
                regexp_replace(input, '([a-z])([A-Z])', '\1-\2', 'g'),  -- camelCase -> kebab
                '[_\s]+', '-', 'g'  -- underscores/spaces -> hyphens
            ),
            '-+', '-', 'g'  -- collapse multiple hyphens
        )
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION normalize_key IS
'Normalizes entity keys to lower-kebab-case for consistent lookups.
Examples: "Mood Disorder" -> "mood-disorder", "mood_disorder" -> "mood-disorder"';

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
    tenant_id VARCHAR(100),  -- NULL = public/shared data
    user_id VARCHAR(100),
    content_summary TEXT,
    metadata JSONB DEFAULT '{}',
    graph_edges JSONB DEFAULT '[]'::jsonb,  -- Cached edges for fast graph traversal
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Unique constraint on (tenant_id, entity_key) using COALESCE to handle NULL tenant_id
CREATE UNIQUE INDEX IF NOT EXISTS idx_kv_store_tenant_key ON kv_store (COALESCE(tenant_id, ''), entity_key);

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
'Tenant identifier for multi-tenancy isolation. NULL = public/shared data visible to all.';

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
-- Note: Includes user-owned AND public (NULL user_id) resources
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
    effective_user_id VARCHAR(100);
BEGIN
    effective_user_id := COALESCE(p_user_id, p_tenant_id);

    -- First lookup in KV store to get entity_type (table name)
    -- Include user-owned AND public (NULL user_id) entries
    -- Normalize input key for consistent matching
    SELECT kv.entity_type INTO entity_table
    FROM kv_store kv
    WHERE (kv.user_id = effective_user_id OR kv.user_id IS NULL)
    AND kv.entity_key = normalize_key(p_entity_key)
    LIMIT 1;

    -- If not found, check if cache is empty and maybe trigger rebuild
    IF entity_table IS NULL THEN
        -- SELF-HEALING: Check if this is because cache is empty
        IF rem_kv_store_empty(effective_user_id) THEN
            PERFORM maybe_trigger_kv_rebuild(effective_user_id, 'rem_lookup');
        END IF;
        RETURN;
    END IF;

    -- Fetch raw record from underlying table as JSONB
    -- LLMs can handle unstructured JSON - no need for schema assumptions
    query_sql := format('
        SELECT
            %L::VARCHAR(100) AS entity_type,
            row_to_json(t)::jsonb AS data
        FROM %I t
        WHERE (t.user_id = $1 OR t.user_id IS NULL)
        AND t.name = $2
        AND t.deleted_at IS NULL
    ', entity_table, entity_table);

    RETURN QUERY EXECUTE query_sql USING effective_user_id, p_entity_key;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_lookup IS
'REM LOOKUP: O(1) entity lookup. Returns user-owned AND public (NULL user_id) entities.';

-- REM FETCH: Fetch full entity records from multiple tables
-- Takes JSONB mapping of {table_name: [entity_keys]}, fetches all records
-- Returns complete entity records as JSONB (not just KV store metadata)
-- Note: Includes user-owned AND public (NULL user_id) resources
CREATE OR REPLACE FUNCTION rem_fetch(
    p_entities_by_table JSONB,
    p_user_id VARCHAR(100)
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_record JSONB
) AS $$
DECLARE
    table_name TEXT;
    entity_keys JSONB;
    query_sql TEXT;
BEGIN
    -- For each table in the input JSONB
    FOR table_name, entity_keys IN SELECT * FROM jsonb_each(p_entities_by_table)
    LOOP
        -- Dynamic query to fetch records from the table
        -- Include user-owned AND public (NULL user_id)
        query_sql := format('
            SELECT
                t.name::VARCHAR(255) AS entity_key,
                %L::VARCHAR(100) AS entity_type,
                row_to_json(t)::jsonb AS entity_record
            FROM %I t
            WHERE t.name = ANY(SELECT jsonb_array_elements_text($1))
            AND (t.user_id = $2 OR t.user_id IS NULL)
            AND t.deleted_at IS NULL
        ', table_name, table_name);

        RETURN QUERY EXECUTE query_sql USING entity_keys, p_user_id;
    END LOOP;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_fetch IS
'REM FETCH: Batch fetch entities. Returns user-owned AND public (NULL user_id) entities.';

-- REM FUZZY: Fuzzy text search using pg_trgm similarity
-- Returns raw entity data as JSONB for LLM consumption
-- Note: Includes user-owned AND public (NULL user_id) resources
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
    effective_user_id VARCHAR(100);
    v_found_any BOOLEAN := FALSE;
BEGIN
    effective_user_id := COALESCE(p_user_id, p_tenant_id);

    -- Find matching keys in KV store (user-owned AND public)
    FOR kv_matches IN
        SELECT
            kv.entity_key,
            kv.entity_type,
            similarity(kv.entity_key, p_query) AS sim_score
        FROM kv_store kv
        WHERE (kv.user_id = effective_user_id OR kv.user_id IS NULL)
        AND kv.entity_key % p_query  -- Trigram similarity operator
        AND similarity(kv.entity_key, p_query) >= p_threshold
        ORDER BY sim_score DESC
        LIMIT p_limit
    LOOP
        v_found_any := TRUE;
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

    -- SELF-HEALING: If no matches and cache is empty, trigger rebuild
    IF NOT v_found_any AND rem_kv_store_empty(effective_user_id) THEN
        PERFORM maybe_trigger_kv_rebuild(effective_user_id, 'rem_fuzzy');
    END IF;

    -- Fetch full records using rem_fetch (which now supports NULL user_id)
    RETURN QUERY
    SELECT
        f.entity_type::VARCHAR(100),
        similarity(f.entity_key, p_query) AS similarity_score,
        f.entity_record AS data
    FROM rem_fetch(entities_by_table, effective_user_id) f
    ORDER BY similarity_score DESC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_fuzzy IS
'REM FUZZY: Fuzzy text search. Returns user-owned AND public (NULL user_id) entities.';

-- ============================================================================
-- REM TRAVERSE (Graph Traversal)
-- ============================================================================

-- REM TRAVERSE: Recursive graph traversal following edges
-- Explores graph_edges starting from entity_key up to max_depth
-- Uses cached kv_store.graph_edges for fast traversal (no polymorphic view!)
-- When keys_only=false, automatically fetches full entity records
-- Note: Includes user-owned AND public (NULL user_id) resources
CREATE OR REPLACE FUNCTION rem_traverse(
    p_entity_key VARCHAR(255),
    p_tenant_id VARCHAR(100),  -- Backward compat parameter (not used for filtering)
    p_user_id VARCHAR(100),
    p_max_depth INTEGER DEFAULT 1,
    p_rel_type VARCHAR(100) DEFAULT NULL,
    p_keys_only BOOLEAN DEFAULT FALSE
)
RETURNS TABLE(
    depth INTEGER,
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    rel_type VARCHAR(100),
    rel_weight REAL,
    path TEXT[],
    entity_record JSONB
) AS $$
DECLARE
    graph_keys RECORD;
    entities_by_table JSONB := '{}'::jsonb;
    table_keys JSONB;
    effective_user_id VARCHAR(100);
    v_found_start BOOLEAN := FALSE;
BEGIN
    effective_user_id := COALESCE(p_user_id, p_tenant_id);

    -- Check if start entity exists in kv_store
    SELECT TRUE INTO v_found_start
    FROM kv_store kv
    WHERE (kv.user_id = effective_user_id OR kv.user_id IS NULL)
    AND kv.entity_key = normalize_key(p_entity_key)
    LIMIT 1;

    -- SELF-HEALING: If start not found and cache is empty, trigger rebuild
    IF NOT COALESCE(v_found_start, FALSE) THEN
        IF rem_kv_store_empty(effective_user_id) THEN
            PERFORM maybe_trigger_kv_rebuild(effective_user_id, 'rem_traverse');
        END IF;
        RETURN;
    END IF;

    FOR graph_keys IN
        WITH RECURSIVE graph_traversal AS (
            -- Base case: Find starting entity (user-owned OR public)
            -- Normalize input key for consistent matching
            SELECT
                0 AS depth,
                kv.entity_key,
                kv.entity_type,
                kv.entity_id,
                NULL::VARCHAR(100) AS rel_type,
                NULL::REAL AS rel_weight,
                ARRAY[kv.entity_key]::TEXT[] AS path
            FROM kv_store kv
            WHERE (kv.user_id = effective_user_id OR kv.user_id IS NULL)
            AND kv.entity_key = normalize_key(p_entity_key)

            UNION ALL

            -- Recursive case: Follow outbound edges
            SELECT
                gt.depth + 1,
                target_kv.entity_key,
                target_kv.entity_type,
                target_kv.entity_id,
                (edge->>'rel_type')::VARCHAR(100) AS rel_type,
                COALESCE((edge->>'weight')::REAL, 1.0) AS rel_weight,
                gt.path || target_kv.entity_key AS path
            FROM graph_traversal gt
            JOIN kv_store source_kv ON source_kv.entity_key = gt.entity_key
                AND (source_kv.user_id = effective_user_id OR source_kv.user_id IS NULL)
            CROSS JOIN LATERAL jsonb_array_elements(COALESCE(source_kv.graph_edges, '[]'::jsonb)) AS edge
            JOIN kv_store target_kv ON target_kv.entity_key = normalize_key((edge->>'dst')::VARCHAR(255))
                AND (target_kv.user_id = effective_user_id OR target_kv.user_id IS NULL)
            WHERE gt.depth < p_max_depth
            AND (p_rel_type IS NULL OR (edge->>'rel_type')::VARCHAR(100) = p_rel_type)
            AND NOT (target_kv.entity_key = ANY(gt.path))
        )
        SELECT DISTINCT ON (entity_key)
            gt.depth,
            gt.entity_key,
            gt.entity_type,
            gt.entity_id,
            gt.rel_type,
            gt.rel_weight,
            gt.path
        FROM graph_traversal gt
        WHERE gt.depth > 0
        ORDER BY gt.entity_key, gt.depth
    LOOP
        IF p_keys_only THEN
            depth := graph_keys.depth;
            entity_key := graph_keys.entity_key;
            entity_type := graph_keys.entity_type;
            entity_id := graph_keys.entity_id;
            rel_type := graph_keys.rel_type;
            rel_weight := graph_keys.rel_weight;
            path := graph_keys.path;
            entity_record := NULL;
            RETURN NEXT;
        ELSE
            IF entities_by_table ? graph_keys.entity_type THEN
                table_keys := entities_by_table->graph_keys.entity_type;
                entities_by_table := jsonb_set(
                    entities_by_table,
                    ARRAY[graph_keys.entity_type],
                    table_keys || jsonb_build_array(graph_keys.entity_key)
                );
            ELSE
                entities_by_table := jsonb_set(
                    entities_by_table,
                    ARRAY[graph_keys.entity_type],
                    jsonb_build_array(graph_keys.entity_key)
                );
            END IF;
        END IF;
    END LOOP;

    IF NOT p_keys_only AND entities_by_table != '{}'::jsonb THEN
        RETURN QUERY
        SELECT
            NULL::INTEGER AS depth,
            f.entity_key::VARCHAR(255),
            f.entity_type::VARCHAR(100),
            NULL::UUID AS entity_id,
            NULL::VARCHAR(100) AS rel_type,
            NULL::REAL AS rel_weight,
            NULL::TEXT[] AS path,
            f.entity_record
        FROM rem_fetch(entities_by_table, effective_user_id) f;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_traverse IS
'REM TRAVERSE: Graph traversal. Returns user-owned AND public (NULL user_id) entities.';

-- REM SEARCH: Vector similarity search using embeddings
-- Joins to embeddings table for semantic search
-- Note: Includes user-owned AND public (NULL user_id) resources
CREATE OR REPLACE FUNCTION rem_search(
    p_query_embedding vector,
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
    effective_user_id VARCHAR(100);
BEGIN
    embeddings_table := 'embeddings_' || p_table_name;
    source_table := p_table_name;
    effective_user_id := COALESCE(p_user_id, p_tenant_id);

    -- Uses cosine distance <=> operator (0-2 range, 0=identical)
    -- Similarity = 1 - distance gives 0-1 range where 1 = most similar
    -- Includes user-owned AND public (NULL user_id) resources
    query_sql := format('
        SELECT
            %L::VARCHAR(100) AS entity_type,
            (1.0 - (e.embedding <=> $1))::REAL AS similarity_score,
            row_to_json(t)::jsonb AS data
        FROM %I t
        JOIN %I e ON e.entity_id = t.id
        WHERE (t.user_id = $2 OR t.user_id IS NULL)
        AND e.field_name = $3
        AND e.provider = $4
        AND (1.0 - (e.embedding <=> $1)) >= $5
        AND t.deleted_at IS NULL
        ORDER BY e.embedding <=> $1
        LIMIT $6
    ', source_table, source_table, embeddings_table);

    RETURN QUERY EXECUTE query_sql
    USING p_query_embedding, effective_user_id, p_field_name, p_provider, p_min_similarity, p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_search IS
'REM SEARCH: Vector similarity search. Returns user-owned AND public (NULL user_id) resources.';

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
-- RATE LIMITS (UNLOGGED for performance)
-- ============================================================================
-- High-performance rate limiting table. Uses UNLOGGED for speed - counts may
-- be lost on database crash/restart, which is acceptable (fail-open on error).

CREATE UNLOGGED TABLE IF NOT EXISTS rate_limits (
    key VARCHAR(512) PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 1,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rate_limits_expires ON rate_limits (expires_at);

COMMENT ON TABLE rate_limits IS
'UNLOGGED rate limiting table. Counts may be lost on crash (acceptable for rate limiting).';

-- ============================================================================
-- SHARED SESSIONS HELPER FUNCTIONS
-- ============================================================================
-- Note: The shared_sessions TABLE is created by 002_install_models.sql (auto-generated)
-- These functions provide aggregate queries for the session sharing workflow.

-- Count distinct users sharing sessions with the current user
CREATE OR REPLACE FUNCTION fn_count_shared_with_me(
    p_tenant_id VARCHAR(100),
    p_user_id VARCHAR(256)
)
RETURNS BIGINT AS $$
BEGIN
    RETURN (
        SELECT COUNT(DISTINCT owner_user_id)
        FROM shared_sessions
        WHERE tenant_id = p_tenant_id
          AND shared_with_user_id = p_user_id
          AND deleted_at IS NULL
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION fn_count_shared_with_me IS
'Count distinct users sharing sessions with the specified user.';

-- Get aggregated summary of users sharing sessions with current user
CREATE OR REPLACE FUNCTION fn_get_shared_with_me(
    p_tenant_id VARCHAR(100),
    p_user_id VARCHAR(256),
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE(
    user_id VARCHAR(256),
    name VARCHAR(256),
    email VARCHAR(256),
    session_count BIGINT,
    message_count BIGINT,
    first_message_at TIMESTAMP,
    last_message_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        ss.owner_user_id AS user_id,
        COALESCE(u.name, ss.owner_user_id) AS name,
        u.email AS email,
        COUNT(DISTINCT ss.session_id)::BIGINT AS session_count,
        COALESCE(SUM(msg_counts.msg_count), 0)::BIGINT AS message_count,
        MIN(msg_counts.first_msg)::TIMESTAMP AS first_message_at,
        MAX(msg_counts.last_msg)::TIMESTAMP AS last_message_at
    FROM shared_sessions ss
    LEFT JOIN users u ON u.id::text = ss.owner_user_id AND u.tenant_id = ss.tenant_id
    LEFT JOIN (
        SELECT
            m.session_id,
            m.user_id,
            COUNT(*)::BIGINT AS msg_count,
            MIN(m.created_at) AS first_msg,
            MAX(m.created_at) AS last_msg
        FROM messages m
        WHERE m.tenant_id = p_tenant_id
          AND m.deleted_at IS NULL
        GROUP BY m.session_id, m.user_id
    ) msg_counts ON msg_counts.session_id = ss.session_id AND msg_counts.user_id = ss.owner_user_id
    WHERE ss.tenant_id = p_tenant_id
      AND ss.shared_with_user_id = p_user_id
      AND ss.deleted_at IS NULL
    GROUP BY ss.owner_user_id, u.name, u.email
    ORDER BY MAX(msg_counts.last_msg) DESC NULLS LAST
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION fn_get_shared_with_me IS
'Get aggregated summary of users sharing sessions with the specified user.';

-- Count messages in sessions shared by a specific user
CREATE OR REPLACE FUNCTION fn_count_shared_messages(
    p_tenant_id VARCHAR(100),
    p_recipient_user_id VARCHAR(256),
    p_owner_user_id VARCHAR(256)
)
RETURNS BIGINT AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)
        FROM messages m
        WHERE m.tenant_id = p_tenant_id
          AND m.deleted_at IS NULL
          AND m.session_id IN (
              SELECT ss.session_id
              FROM shared_sessions ss
              WHERE ss.tenant_id = p_tenant_id
                AND ss.owner_user_id = p_owner_user_id
                AND ss.shared_with_user_id = p_recipient_user_id
                AND ss.deleted_at IS NULL
          )
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION fn_count_shared_messages IS
'Count messages in sessions shared by a specific user with the recipient.';

-- Get messages from sessions shared by a specific user
CREATE OR REPLACE FUNCTION fn_get_shared_messages(
    p_tenant_id VARCHAR(100),
    p_recipient_user_id VARCHAR(256),
    p_owner_user_id VARCHAR(256),
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
)
RETURNS TABLE(
    id UUID,
    content TEXT,
    message_type VARCHAR(256),
    session_id VARCHAR(256),
    model VARCHAR(256),
    token_count INTEGER,
    created_at TIMESTAMP,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.content,
        m.message_type,
        m.session_id,
        m.model,
        m.token_count,
        m.created_at,
        m.metadata
    FROM messages m
    WHERE m.tenant_id = p_tenant_id
      AND m.deleted_at IS NULL
      AND m.session_id IN (
          SELECT ss.session_id
          FROM shared_sessions ss
          WHERE ss.tenant_id = p_tenant_id
            AND ss.owner_user_id = p_owner_user_id
            AND ss.shared_with_user_id = p_recipient_user_id
            AND ss.deleted_at IS NULL
      )
    ORDER BY m.created_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION fn_get_shared_messages IS
'Get messages from sessions shared by a specific user with the recipient.';

-- ============================================================================
-- SESSIONS WITH USER INFO
-- ============================================================================
-- Function to list sessions with user details (name, email) for admin views

-- List sessions with user info, CTE pagination
-- Note: messages.session_id stores the session UUID (sessions.id)
CREATE OR REPLACE FUNCTION fn_list_sessions_with_user(
    p_user_id VARCHAR(256) DEFAULT NULL,  -- Filter by user_id (NULL = all users, admin only)
    p_user_name VARCHAR(256) DEFAULT NULL,  -- Filter by user name (partial match, admin only)
    p_user_email VARCHAR(256) DEFAULT NULL,  -- Filter by user email (partial match, admin only)
    p_mode VARCHAR(50) DEFAULT NULL,  -- Filter by session mode
    p_page INTEGER DEFAULT 1,
    p_page_size INTEGER DEFAULT 50
)
RETURNS TABLE(
    id UUID,
    name VARCHAR(256),
    mode TEXT,
    description TEXT,
    user_id VARCHAR(256),
    user_name VARCHAR(256),
    user_email VARCHAR(256),
    message_count INTEGER,
    total_tokens INTEGER,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    metadata JSONB,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH session_msg_counts AS (
        -- Count messages per session (joining on session UUID)
        SELECT
            m.session_id,
            COUNT(*)::INTEGER as actual_message_count
        FROM messages m
        GROUP BY m.session_id
    ),
    filtered_sessions AS (
        SELECT
            s.id,
            s.name,
            s.mode,
            s.description,
            s.user_id,
            COALESCE(u.name, s.user_id)::VARCHAR(256) AS user_name,
            u.email::VARCHAR(256) AS user_email,
            COALESCE(mc.actual_message_count, 0) AS message_count,
            s.total_tokens,
            s.created_at,
            s.updated_at,
            s.metadata
        FROM sessions s
        LEFT JOIN users u ON u.id::text = s.user_id
        LEFT JOIN session_msg_counts mc ON mc.session_id = s.id::text
        WHERE s.deleted_at IS NULL
          AND (p_user_id IS NULL OR s.user_id = p_user_id)
          AND (p_user_name IS NULL OR u.name ILIKE '%' || p_user_name || '%')
          AND (p_user_email IS NULL OR u.email ILIKE '%' || p_user_email || '%')
          AND (p_mode IS NULL OR s.mode = p_mode)
    ),
    counted AS (
        SELECT *, COUNT(*) OVER () AS total_count
        FROM filtered_sessions
    )
    SELECT
        c.id,
        c.name,
        c.mode,
        c.description,
        c.user_id,
        c.user_name,
        c.user_email,
        c.message_count,
        c.total_tokens,
        c.created_at,
        c.updated_at,
        c.metadata,
        c.total_count
    FROM counted c
    ORDER BY c.created_at DESC
    LIMIT p_page_size
    OFFSET (p_page - 1) * p_page_size;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION fn_list_sessions_with_user IS
'List sessions with user details and computed message counts. Joins messages on session name.';

-- ============================================================================
-- RECORD INSTALLATION
-- ============================================================================

INSERT INTO rem_migrations (name, type, version)
VALUES ('install.sql', 'install', '1.0.0')
ON CONFLICT (name) DO UPDATE
SET applied_at = CURRENT_TIMESTAMP,
    applied_by = CURRENT_USER;

-- ============================================================================
-- GRANTS FOR APPLICATION USER
-- ============================================================================
-- Grant permissions to remuser (the application database user)
-- This ensures the application can run migrations and manage schema
-- Note: remuser is created by CNPG as the database owner in bootstrap.initdb.owner

DO $$
DECLARE
    app_user TEXT := 'remuser';
BEGIN
    -- Only grant if the user exists (handles different deployment scenarios)
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_user) THEN
        -- Grant ownership of migration tracking table so app can record migrations
        EXECUTE format('ALTER TABLE rem_migrations OWNER TO %I', app_user);
        EXECUTE format('ALTER TABLE kv_store OWNER TO %I', app_user);
        EXECUTE format('ALTER TABLE rate_limits OWNER TO %I', app_user);

        -- Grant usage on schema
        EXECUTE format('GRANT ALL ON SCHEMA public TO %I', app_user);

        -- Grant privileges on all tables in public schema
        EXECUTE format('GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO %I', app_user);
        EXECUTE format('GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO %I', app_user);
        EXECUTE format('GRANT ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public TO %I', app_user);

        -- Set default privileges for future objects
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO %I', app_user);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO %I', app_user);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO %I', app_user);

        RAISE NOTICE '✓ Granted permissions to application user: %', app_user;
    ELSE
        RAISE NOTICE 'Application user % does not exist, skipping grants', app_user;
    END IF;
END $$;

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
