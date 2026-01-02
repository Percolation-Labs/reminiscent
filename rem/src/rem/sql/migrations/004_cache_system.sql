-- REM Cache System
-- Description: Cache management helpers for UNLOGGED tables (kv_store)
-- Version: 1.0.0
-- Date: 2025-11-29
--
-- This migration adds:
--   1. cache_system_state table for debouncing and API secret storage
--   2. maybe_trigger_kv_rebuild() function for async rebuild triggering
--   3. Helper functions for cache management
--
-- NOTE: Core functions (rem_lookup, rem_fuzzy, rem_traverse) are defined in 001_install.sql
-- This file only provides cache-specific infrastructure.

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
    -- Check for user-specific OR public (NULL user_id) entries
    -- This ensures self-healing triggers correctly for public ontologies
    RETURN NOT EXISTS (
        SELECT 1 FROM kv_store
        WHERE user_id = p_user_id OR user_id IS NULL
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
    v_api_url TEXT := 'http://rem-api.rem.svc.cluster.local:8000/api/admin/internal/rebuild-kv';
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
    RAISE NOTICE '  rem_kv_store_empty() - Check if cache is empty';
    RAISE NOTICE '  rem_get_cache_api_secret() - Get API secret';
    RAISE NOTICE '  rem_record_cache_rebuild() - Record rebuild completion';
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
    RAISE NOTICE '============================================================';
END $$;
