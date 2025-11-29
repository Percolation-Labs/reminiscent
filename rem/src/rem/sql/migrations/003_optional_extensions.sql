-- REM Optional Extensions
-- Description: Optional PostgreSQL extensions that enhance functionality but are not required
-- Version: 1.0.0
-- Date: 2025-11-29
--
-- These extensions are installed with try/catch - failures are logged but don't break the install.
-- This allows the same migration to work on:
--   - Custom images with extensions baked in (percolationlabs/rem-pg:18)
--   - Standard PostgreSQL images (extensions will be skipped)
--
-- Extensions:
--   - pg_net: Async HTTP/HTTPS requests from triggers and functions (Supabase)

-- ============================================================================
-- pg_net: Async HTTP Extension
-- ============================================================================
-- Enables PostgreSQL to make non-blocking HTTP requests from triggers and functions.
-- Requires: Custom image with pg_net compiled, shared_preload_libraries='pg_net'
--
-- Use cases:
--   - Webhook notifications on data changes
--   - Async event publishing to external APIs
--   - Background HTTP requests from triggers

DO $$
BEGIN
    -- Attempt to create pg_net extension
    CREATE EXTENSION IF NOT EXISTS pg_net;
    RAISE NOTICE '  pg_net extension installed successfully';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE '  pg_net extension not available (this is OK if using standard PostgreSQL image)';
        RAISE NOTICE '  Error: %', SQLERRM;
END $$;

-- ============================================================================
-- pg_net Helper Functions (only created if extension exists)
-- ============================================================================
-- Wrapper functions for common HTTP operations with sensible defaults

DO $$
BEGIN
    -- Only create helpers if pg_net is available
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_net') THEN

        -- Helper: POST JSON to a URL with standard headers
        EXECUTE $func$
        CREATE OR REPLACE FUNCTION rem_http_post(
            p_url TEXT,
            p_body JSONB,
            p_headers JSONB DEFAULT '{}'::jsonb
        )
        RETURNS BIGINT AS $inner$
        DECLARE
            merged_headers JSONB;
            request_id BIGINT;
        BEGIN
            -- Merge default headers with provided headers
            merged_headers := '{"Content-Type": "application/json"}'::jsonb || p_headers;

            SELECT net.http_post(
                url := p_url,
                headers := merged_headers,
                body := p_body
            ) INTO request_id;

            RETURN request_id;
        END;
        $inner$ LANGUAGE plpgsql;
        $func$;

        RAISE NOTICE '  rem_http_post helper function created';

        -- Helper: GET from a URL
        EXECUTE $func$
        CREATE OR REPLACE FUNCTION rem_http_get(
            p_url TEXT,
            p_headers JSONB DEFAULT '{}'::jsonb
        )
        RETURNS BIGINT AS $inner$
        DECLARE
            request_id BIGINT;
        BEGIN
            SELECT net.http_get(
                url := p_url,
                headers := p_headers
            ) INTO request_id;

            RETURN request_id;
        END;
        $inner$ LANGUAGE plpgsql;
        $func$;

        RAISE NOTICE '  rem_http_get helper function created';

        -- ====================================================================
        -- REM Query Function
        -- ====================================================================
        -- Executes REM queries via the REM API using pg_net
        --
        -- Default API host: rem-api (works in K8s same namespace)
        -- For local Docker testing: Add "host.docker.internal rem-api" to /etc/hosts
        -- Or override with p_api_host parameter
        --
        -- Example:
        --   SELECT rem_query('LOOKUP sarah-chen', 'user123');
        --   SELECT rem_query('SEARCH resources ''API design'' LIMIT 5', 'user123');

        EXECUTE $func$
        CREATE OR REPLACE FUNCTION rem_query(
            p_query TEXT,
            p_user_id TEXT,
            p_api_host TEXT DEFAULT 'rem-api',
            p_api_port INTEGER DEFAULT 8000,
            p_mode TEXT DEFAULT 'rem-dialect'
        )
        RETURNS BIGINT AS $inner$
        DECLARE
            api_url TEXT;
            request_body JSONB;
            request_headers JSONB;
            request_id BIGINT;
        BEGIN
            -- Build API URL
            -- Default: http://rem-api:8000/api/v1/query (K8s same namespace)
            api_url := format('http://%s:%s/api/v1/query', p_api_host, p_api_port);

            -- Build request body
            request_body := jsonb_build_object(
                'query', p_query,
                'mode', p_mode
            );

            -- Build headers with user ID
            request_headers := jsonb_build_object(
                'Content-Type', 'application/json',
                'X-User-Id', p_user_id
            );

            -- Make async HTTP POST request
            SELECT net.http_post(
                url := api_url,
                headers := request_headers,
                body := request_body
            ) INTO request_id;

            RETURN request_id;
        END;
        $inner$ LANGUAGE plpgsql;
        $func$;

        RAISE NOTICE '  rem_query() function created';

        -- Helper to get query results (waits for async response)
        -- NOTE: pg_net is async by design. This function polls for the response.
        -- For best results, use rem_query() and check results later, or use longer timeouts.
        EXECUTE $func$
        CREATE OR REPLACE FUNCTION rem_query_result(
            p_request_id BIGINT,
            p_timeout_ms INTEGER DEFAULT 10000
        )
        RETURNS JSONB AS $inner$
        DECLARE
            v_status_code INTEGER;
            v_content TEXT;
            v_found BOOLEAN;
            start_time TIMESTAMP;
            elapsed_ms INTEGER;
        BEGIN
            start_time := clock_timestamp();

            -- Poll for response with timeout
            -- Each iteration starts a new query to see committed data from background worker
            LOOP
                -- Check if response exists (background worker commits independently)
                SELECT true, status_code, content::text
                INTO v_found, v_status_code, v_content
                FROM net._http_response
                WHERE id = p_request_id;

                -- Found response
                IF v_found THEN
                    IF v_status_code = 200 THEN
                        RETURN v_content::jsonb;
                    ELSE
                        RETURN jsonb_build_object(
                            'error', true,
                            'status_code', v_status_code,
                            'content', v_content
                        );
                    END IF;
                END IF;

                -- Check timeout
                elapsed_ms := EXTRACT(EPOCH FROM (clock_timestamp() - start_time)) * 1000;
                IF elapsed_ms >= p_timeout_ms THEN
                    RETURN jsonb_build_object(
                        'error', true,
                        'message', 'Request timeout - pg_net is async, response may arrive later',
                        'request_id', p_request_id,
                        'hint', 'Check net._http_response table or increase timeout'
                    );
                END IF;

                -- Wait 500ms before next poll (pg_net worker runs every 100ms)
                PERFORM pg_sleep(0.5);
            END LOOP;
        END;
        $inner$ LANGUAGE plpgsql;
        $func$;

        RAISE NOTICE '  rem_query_result() function created';

        -- Convenience function: execute query and wait for result
        -- WARNING: Due to PostgreSQL transaction isolation, this may timeout even when
        -- the request succeeds. The background worker commits separately and the polling
        -- loop may not see the response. Use rem_query() + check net._http_response for
        -- more reliable async operation.
        EXECUTE $func$
        CREATE OR REPLACE FUNCTION rem_query_sync(
            p_query TEXT,
            p_user_id TEXT,
            p_api_host TEXT DEFAULT 'rem-api',
            p_api_port INTEGER DEFAULT 8000,
            p_mode TEXT DEFAULT 'rem-dialect',
            p_timeout_ms INTEGER DEFAULT 10000
        )
        RETURNS JSONB AS $inner$
        DECLARE
            request_id BIGINT;
            v_status_code INTEGER;
            v_content TEXT;
            v_found BOOLEAN := false;
            start_time TIMESTAMP;
            elapsed_ms INTEGER;
        BEGIN
            -- Execute query - this queues the HTTP request
            request_id := rem_query(p_query, p_user_id, p_api_host, p_api_port, p_mode);

            -- Wait for response with explicit snapshot refresh attempts
            start_time := clock_timestamp();
            LOOP
                -- Query in separate subtransaction-like context
                SELECT true, status_code, content::text
                INTO v_found, v_status_code, v_content
                FROM net._http_response
                WHERE id = request_id;

                IF v_found THEN
                    IF v_status_code = 200 THEN
                        RETURN v_content::jsonb;
                    ELSE
                        RETURN jsonb_build_object('error', true, 'status_code', v_status_code, 'content', v_content);
                    END IF;
                END IF;

                elapsed_ms := EXTRACT(EPOCH FROM (clock_timestamp() - start_time)) * 1000;
                IF elapsed_ms >= p_timeout_ms THEN
                    -- Return info about the async request so caller can check later
                    RETURN jsonb_build_object(
                        'pending', true,
                        'request_id', request_id,
                        'message', 'Request queued but response not yet visible due to transaction isolation',
                        'hint', 'Query net._http_response WHERE id = ' || request_id || ' after this transaction commits'
                    );
                END IF;

                PERFORM pg_sleep(0.3);
            END LOOP;
        END;
        $inner$ LANGUAGE plpgsql;
        $func$;

        RAISE NOTICE '  rem_query_sync() function created (async pattern recommended)';

    ELSE
        RAISE NOTICE '  Skipping pg_net helper functions (extension not installed)';
    END IF;
END $$;

-- ============================================================================
-- RECORD INSTALLATION
-- ============================================================================

DO $$
BEGIN
    -- Only record if migrations table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'rem_migrations') THEN
        INSERT INTO rem_migrations (name, type, version)
        VALUES ('003_optional_extensions.sql', 'install', '1.0.0')
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
    pg_net_installed BOOLEAN;
BEGIN
    SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_net') INTO pg_net_installed;

    RAISE NOTICE '============================================================';
    RAISE NOTICE 'Optional Extensions Installation Complete';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    IF pg_net_installed THEN
        RAISE NOTICE 'Installed:';
        RAISE NOTICE '  pg_net (async HTTP/HTTPS requests)';
        RAISE NOTICE '  rem_http_post() - POST JSON to URL';
        RAISE NOTICE '  rem_http_get() - GET from URL';
        RAISE NOTICE '  rem_query() - Execute REM query (async)';
        RAISE NOTICE '  rem_query_result() - Get async query result';
        RAISE NOTICE '  rem_query_sync() - Execute and wait for result';
    ELSE
        RAISE NOTICE 'Skipped (not available in this PostgreSQL image):';
        RAISE NOTICE '  pg_net';
        RAISE NOTICE '';
        RAISE NOTICE 'To enable pg_net, use the custom image: percolationlabs/rem-pg:18';
    END IF;
    RAISE NOTICE '============================================================';
END $$;
