-- REM Cache System
-- Description: Self-healing cache for UNLOGGED tables (kv_store)
-- Version: 1.0.0
-- Date: 2025-11-29
--
-- This migration adds:
--   1. cache_system_state table for debouncing and API secret storage
--   2. maybe_trigger_kv_rebuild() function for async rebuild triggering
--   3. Updated rem_lookup/fuzzy/traverse with self-healing on empty cache
--
-- Self-Healing Flow:
--   Query returns 0 results → Check if kv_store empty → Trigger async rebuild
--   Priority: pg_net (if available) → dblink (always available)

-- ============================================================================
-- REQUIRED EXTENSION
-- ============================================================================
-- pgcrypto is needed for gen_random_bytes() to generate API secrets
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- CACHE SYSTEM STATE TABLE
-- ============================================================================
-- Stores:
--   - Last rebuild trigger timestamp (for debouncing)
--   - API secret for internal endpoint authentication
--   - Rebuild statistics

CREATE TABLE IF NOT EXISTS cache_system_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- Single row table
    api_secret TEXT NOT NULL,                          -- Secret for internal API auth
    last_triggered_at TIMESTAMPTZ,                     -- Debounce: last trigger time
    last_rebuild_at TIMESTAMPTZ,                       -- Last successful rebuild
    triggered_by TEXT,                                 -- What triggered last rebuild
    trigger_count INTEGER DEFAULT 0,                   -- Total trigger count
    rebuild_count INTEGER DEFAULT 0,                   -- Total successful rebuilds
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Generate initial secret if table is empty
INSERT INTO cache_system_state (id, api_secret)
SELECT 1, encode(gen_random_bytes(32), 'hex')
WHERE NOT EXISTS (SELECT 1 FROM cache_system_state WHERE id = 1);

COMMENT ON TABLE cache_system_state IS
'Single-row table storing cache system state: API secret for internal auth and debounce tracking';

-- ============================================================================
-- HELPER: Check if extension exists
-- ============================================================================

CREATE OR REPLACE FUNCTION rem_extension_exists(p_extension TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (SELECT 1 FROM pg_extension WHERE extname = p_extension);
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- HELPER: Check if kv_store is empty for user
-- ============================================================================

CREATE OR REPLACE FUNCTION rem_kv_store_empty(p_user_id TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    -- Quick existence check - very fast with index
    RETURN NOT EXISTS (
        SELECT 1 FROM kv_store
        WHERE user_id = p_user_id
        LIMIT 1
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- MAIN: Maybe trigger KV rebuild (async, non-blocking)
-- ============================================================================
-- Called when a query returns 0 results and kv_store appears empty.
-- Uses pg_net (if available) to call API, falls back to dblink.
-- Includes debouncing to prevent request storms.

CREATE OR REPLACE FUNCTION maybe_trigger_kv_rebuild(
    p_user_id TEXT,
    p_triggered_by TEXT DEFAULT 'query'
)
RETURNS VOID AS $$
DECLARE
    v_has_pgnet BOOLEAN;
    v_has_dblink BOOLEAN;
    v_last_trigger TIMESTAMPTZ;
    v_api_secret TEXT;
    v_debounce_seconds CONSTANT INTEGER := 30;
    v_api_url TEXT := 'http://rem-api.siggy.svc.cluster.local:8000/api/admin/internal/rebuild-kv';
    v_request_id BIGINT;
BEGIN
    -- Quick check: is kv_store actually empty for this user?
    IF NOT rem_kv_store_empty(p_user_id) THEN
        RETURN;  -- Cache has data, nothing to do
    END IF;

    -- Try to acquire advisory lock (non-blocking, transaction-scoped)
    -- This prevents multiple concurrent triggers
    IF NOT pg_try_advisory_xact_lock(2147483646) THEN
        RETURN;  -- Another session is handling it
    END IF;

    -- Check debounce: was rebuild triggered recently?
    SELECT last_triggered_at, api_secret
    INTO v_last_trigger, v_api_secret
    FROM cache_system_state
    WHERE id = 1;

    IF v_last_trigger IS NOT NULL
       AND v_last_trigger > (CURRENT_TIMESTAMP - (v_debounce_seconds || ' seconds')::INTERVAL) THEN
        RETURN;  -- Triggered recently, skip
    END IF;

    -- Update state (so concurrent callers see it)
    UPDATE cache_system_state
    SET last_triggered_at = CURRENT_TIMESTAMP,
        triggered_by = p_triggered_by,
        trigger_count = trigger_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = 1;

    -- Check available extensions
    v_has_pgnet := rem_extension_exists('pg_net');
    v_has_dblink := rem_extension_exists('dblink');

    -- Priority 1: pg_net (async HTTP to API - supports S3 restore)
    IF v_has_pgnet THEN
        BEGIN
            SELECT net.http_post(
                url := v_api_url,
                headers := jsonb_build_object(
                    'Content-Type', 'application/json',
                    'X-Internal-Secret', v_api_secret
                ),
                body := jsonb_build_object(
                    'user_id', p_user_id,
                    'triggered_by', 'pg_net_' || p_triggered_by,
                    'timestamp', CURRENT_TIMESTAMP
                )
            ) INTO v_request_id;

            RAISE DEBUG 'kv_rebuild triggered via pg_net (request_id: %)', v_request_id;
            RETURN;
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'pg_net trigger failed: %, falling back to dblink', SQLERRM;
        END;
    END IF;

    -- Priority 2: dblink (async SQL - direct rebuild)
    IF v_has_dblink THEN
        BEGIN
            -- Connect to self (same database)
            PERFORM dblink_connect(
                'kv_rebuild_conn',
                format('dbname=%s', current_database())
            );

            -- Send async query (returns immediately)
            PERFORM dblink_send_query(
                'kv_rebuild_conn',
                'SELECT rebuild_kv_store()'
            );

            -- Don't disconnect - query continues in background
            -- Connection auto-closes when session ends

            RAISE DEBUG 'kv_rebuild triggered via dblink';
            RETURN;
        EXCEPTION WHEN OTHERS THEN
            -- Clean up failed connection
            BEGIN
                PERFORM dblink_disconnect('kv_rebuild_conn');
            EXCEPTION WHEN OTHERS THEN
                NULL;
            END;
            RAISE WARNING 'dblink trigger failed: %', SQLERRM;
        END;
    END IF;

    -- No async method available - log warning but don't block query
    RAISE WARNING 'No async rebuild method available (pg_net or dblink). Cache rebuild skipped.';

EXCEPTION WHEN OTHERS THEN
    -- Never fail the calling query
    RAISE WARNING 'maybe_trigger_kv_rebuild failed: %', SQLERRM;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION maybe_trigger_kv_rebuild IS
'Async trigger for kv_store rebuild. Uses pg_net (API) or dblink (SQL). Includes debouncing.';

-- ============================================================================
-- UPDATED: rem_lookup with self-healing
-- ============================================================================

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
    v_result_count INTEGER := 0;
BEGIN
    effective_user_id := COALESCE(p_user_id, p_tenant_id);

    -- First lookup in KV store to get entity_type (table name)
    SELECT kv.entity_type INTO entity_table
    FROM kv_store kv
    WHERE (kv.user_id = effective_user_id OR kv.user_id IS NULL)
    AND kv.entity_key = p_entity_key
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

-- ============================================================================
-- UPDATED: rem_fuzzy with self-healing
-- ============================================================================

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

    -- Find matching keys in KV store
    FOR kv_matches IN
        SELECT
            kv.entity_key,
            kv.entity_type,
            similarity(kv.entity_key, p_query) AS sim_score
        FROM kv_store kv
        WHERE (kv.user_id = effective_user_id OR kv.user_id IS NULL)
        AND kv.entity_key % p_query
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

    -- Fetch full records
    RETURN QUERY
    SELECT
        f.entity_type::VARCHAR(100),
        similarity(f.entity_key, p_query) AS similarity_score,
        f.entity_record AS data
    FROM rem_fetch(entities_by_table, effective_user_id) f
    ORDER BY similarity_score DESC;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- UPDATED: rem_traverse with self-healing
-- ============================================================================

CREATE OR REPLACE FUNCTION rem_traverse(
    p_entity_key VARCHAR(255),
    p_tenant_id VARCHAR(100),
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
    AND kv.entity_key = p_entity_key
    LIMIT 1;

    -- SELF-HEALING: If start not found and cache is empty, trigger rebuild
    IF NOT COALESCE(v_found_start, FALSE) THEN
        IF rem_kv_store_empty(effective_user_id) THEN
            PERFORM maybe_trigger_kv_rebuild(effective_user_id, 'rem_traverse');
        END IF;
        RETURN;
    END IF;

    -- Original traverse logic
    FOR graph_keys IN
        WITH RECURSIVE graph_traversal AS (
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
            AND kv.entity_key = p_entity_key

            UNION ALL

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
            JOIN kv_store target_kv ON target_kv.entity_key = (edge->>'dst')::VARCHAR(255)
                AND (target_kv.user_id = effective_user_id OR target_kv.user_id IS NULL)
            WHERE gt.depth < p_max_depth
            AND (p_rel_type IS NULL OR (edge->>'rel_type')::VARCHAR(100) = p_rel_type)
            AND NOT (target_kv.entity_key = ANY(gt.path))
        )
        SELECT DISTINCT ON (gt.entity_key)
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

    IF NOT p_keys_only THEN
        RETURN QUERY
        SELECT
            g.depth,
            g.entity_key,
            g.entity_type,
            g.entity_id,
            g.rel_type,
            g.rel_weight,
            g.path,
            f.entity_record
        FROM (
            SELECT * FROM rem_traverse(p_entity_key, p_tenant_id, effective_user_id, p_max_depth, p_rel_type, TRUE)
        ) g
        LEFT JOIN rem_fetch(entities_by_table, effective_user_id) f
            ON g.entity_key = f.entity_key;
    END IF;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- HELPER: Get API secret for validation
-- ============================================================================

CREATE OR REPLACE FUNCTION rem_get_cache_api_secret()
RETURNS TEXT AS $$
DECLARE
    v_secret TEXT;
BEGIN
    SELECT api_secret INTO v_secret FROM cache_system_state WHERE id = 1;
    RETURN v_secret;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Only allow rem user to execute
REVOKE ALL ON FUNCTION rem_get_cache_api_secret() FROM PUBLIC;

-- ============================================================================
-- HELPER: Record successful rebuild
-- ============================================================================

CREATE OR REPLACE FUNCTION rem_record_cache_rebuild(p_triggered_by TEXT DEFAULT 'api')
RETURNS VOID AS $$
BEGIN
    UPDATE cache_system_state
    SET last_rebuild_at = CURRENT_TIMESTAMP,
        rebuild_count = rebuild_count + 1,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = 1;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- RECORD INSTALLATION
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'rem_migrations') THEN
        INSERT INTO rem_migrations (name, type, version)
        VALUES ('004_cache_system.sql', 'install', '1.0.0')
        ON CONFLICT (name) DO UPDATE
        SET applied_at = CURRENT_TIMESTAMP,
            applied_by = CURRENT_USER;
    END IF;
END $$;

-- ============================================================================
-- COMPLETION
-- ============================================================================

DO $$
DECLARE
    v_has_pgnet BOOLEAN;
    v_has_dblink BOOLEAN;
BEGIN
    v_has_pgnet := rem_extension_exists('pg_net');
    v_has_dblink := rem_extension_exists('dblink');

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Cache System Installation Complete';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables:';
    RAISE NOTICE '  cache_system_state - Debounce tracking and API secret';
    RAISE NOTICE '';
    RAISE NOTICE 'Functions:';
    RAISE NOTICE '  maybe_trigger_kv_rebuild() - Async rebuild trigger';
    RAISE NOTICE '  rem_lookup() - Updated with self-healing';
    RAISE NOTICE '  rem_fuzzy() - Updated with self-healing';
    RAISE NOTICE '  rem_traverse() - Updated with self-healing';
    RAISE NOTICE '';
    RAISE NOTICE 'Async Methods Available:';
    IF v_has_pgnet THEN
        RAISE NOTICE '  [x] pg_net - HTTP POST to API (preferred)';
    ELSE
        RAISE NOTICE '  [ ] pg_net - Not installed';
    END IF;
    IF v_has_dblink THEN
        RAISE NOTICE '  [x] dblink - Async SQL (fallback)';
    ELSE
        RAISE NOTICE '  [ ] dblink - Not installed';
    END IF;
    RAISE NOTICE '';
    RAISE NOTICE 'Self-Healing: Queries will auto-trigger rebuild on empty cache';
    RAISE NOTICE '============================================================';
END $$;
