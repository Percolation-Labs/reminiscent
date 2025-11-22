-- Migration: tenant_id → user_id for REM Query Functions
-- Description: Update REM query function signatures to use user_id instead of tenant_id
-- Version: 1.0.0
-- Date: 2025-11-22
--
-- This migration updates the following functions:
-- 1. rem_lookup() - Remove tenant_id parameter, use user_id only
-- 2. rem_fuzzy() - Remove tenant_id parameter, use user_id only
-- 3. rem_search() - Remove tenant_id parameter, use user_id only
-- 4. rem_traverse() - Remove tenant_id parameter, use user_id only
--
-- IMPORTANT: This is a breaking change. Application code must be updated
-- to pass user_id instead of tenant_id when calling these functions.
--
-- Note: tenant_id column remains in database schema for future use,
-- but is no longer used for filtering in REM queries.

-- ============================================================================
-- REM LOOKUP
-- ============================================================================

-- REM LOOKUP: O(1) entity lookup by natural key
-- Returns entity metadata from KV_STORE cache
CREATE OR REPLACE FUNCTION rem_lookup(
    p_entity_key VARCHAR(255),
    p_user_id VARCHAR(100)
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    created_at TIMESTAMP,
    content_summary TEXT,
    metadata JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        kv.entity_key,
        kv.entity_type,
        kv.entity_id,
        kv.tenant_id,
        kv.user_id,
        kv.created_at,
        kv.content_summary,
        kv.metadata
    FROM kv_store kv
    WHERE kv.user_id = p_user_id
    AND kv.entity_key = p_entity_key;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_lookup IS
'REM LOOKUP query: O(1) entity lookup by natural key scoped to user_id';

-- ============================================================================
-- REM FUZZY
-- ============================================================================

-- REM FUZZY: Fuzzy text search using pg_trgm similarity
-- Returns entities matching approximate text with similarity scores
CREATE OR REPLACE FUNCTION rem_fuzzy(
    p_query TEXT,
    p_user_id VARCHAR(100),
    p_threshold REAL DEFAULT 0.3,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    tenant_id VARCHAR(100),
    user_id VARCHAR(100),
    created_at TIMESTAMP,
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
        kv.tenant_id,
        kv.user_id,
        kv.created_at,
        kv.content_summary,
        kv.metadata,
        similarity(kv.entity_key, p_query) AS similarity_score
    FROM kv_store kv
    WHERE kv.user_id = p_user_id
    AND kv.entity_key % p_query  -- Trigram similarity operator
    ORDER BY similarity_score DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_fuzzy IS
'REM FUZZY query: Fuzzy text search using pg_trgm with similarity scoring scoped to user_id';

-- ============================================================================
-- REM TRAVERSE
-- ============================================================================

-- REM TRAVERSE: Recursive graph traversal following edges
-- Explores graph_edges starting from entity_key up to max_depth
CREATE OR REPLACE FUNCTION rem_traverse(
    p_entity_key VARCHAR(255),
    p_user_id VARCHAR(100),
    p_max_depth INTEGER DEFAULT 1,
    p_rel_type VARCHAR(100) DEFAULT NULL
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
    RETURN QUERY
    WITH RECURSIVE graph_traversal AS (
        -- Base case: Find starting entity
        SELECT
            0 AS depth,
            kv.entity_key,
            kv.entity_type,
            kv.entity_id,
            NULL::VARCHAR(100) AS rel_type,
            NULL::REAL AS rel_weight,
            ARRAY[kv.entity_key]::TEXT[] AS path
        FROM kv_store kv
        WHERE kv.user_id = p_user_id
        AND kv.entity_key = p_entity_key

        UNION ALL

        -- Recursive case: Follow outbound edges from discovered entities
        SELECT
            gt.depth + 1,
            target_kv.entity_key,
            target_kv.entity_type,
            target_kv.entity_id,
            (edge->>'type')::VARCHAR(100) AS rel_type,
            COALESCE((edge->'metadata'->>'weight')::REAL, 1.0) AS rel_weight,
            gt.path || target_kv.entity_key AS path
        FROM graph_traversal gt
        -- Join to primary table to get graph_edges JSONB
        JOIN kv_store source_kv ON source_kv.entity_key = gt.entity_key
            AND source_kv.user_id = p_user_id
        JOIN resources r ON r.id = source_kv.entity_id
        -- Extract edges from JSONB array
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.graph_edges, '[]'::jsonb)) AS edge
        -- Lookup target entity in KV store
        JOIN kv_store target_kv ON target_kv.entity_key = (edge->>'target')::VARCHAR(255)
            AND target_kv.user_id = p_user_id
        WHERE gt.depth < p_max_depth
        -- Filter by relationship type if specified
        AND (p_rel_type IS NULL OR (edge->>'type')::VARCHAR(100) = p_rel_type)
        -- Prevent cycles by checking path
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
    WHERE gt.depth > 0  -- Exclude starting entity
    ORDER BY gt.entity_key, gt.depth;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_traverse IS
'REM TRAVERSE query: Recursive graph traversal following entity relationships via graph_edges scoped to user_id';

-- ============================================================================
-- REM SEARCH
-- ============================================================================

-- REM SEARCH: Vector similarity search using embeddings
-- Joins to embeddings table for semantic search
CREATE OR REPLACE FUNCTION rem_search(
    p_query_embedding vector(1536),
    p_table_name VARCHAR(100),
    p_field_name VARCHAR(100),
    p_user_id VARCHAR(100),
    p_provider VARCHAR(50) DEFAULT 'openai',
    p_min_similarity REAL DEFAULT 0.7,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE(
    entity_key VARCHAR(255),
    entity_type VARCHAR(100),
    entity_id UUID,
    distance REAL,
    content_summary TEXT
) AS $$
DECLARE
    embeddings_table VARCHAR(200);
    query_sql TEXT;
BEGIN
    -- Construct embeddings table name
    embeddings_table := 'embeddings_' || p_table_name;

    -- Dynamic query to join KV_STORE with embeddings table
    -- Note: Using inner product for OpenAI embeddings (normalized vectors)
    -- Inner product <#> returns negative value, so we negate it to get [0, 1]
    -- where 1 = perfect match, 0 = orthogonal. We then compute (1 - inner_product)
    -- to get distance where 0 = perfect match, 1 = completely different
    query_sql := format('
        SELECT
            kv.entity_key,
            kv.entity_type,
            kv.entity_id,
            (1.0 - (e.embedding <#> $1) * -1.0)::REAL AS distance,
            kv.content_summary
        FROM kv_store kv
        JOIN %I e ON e.entity_id = kv.entity_id
        WHERE kv.user_id = $2
        AND e.field_name = $3
        AND e.provider = $4
        AND (1.0 - (e.embedding <#> $1) * -1.0) <= (1.0 - $5)
        ORDER BY e.embedding <#> $1 DESC
        LIMIT $6
    ', embeddings_table);

    RETURN QUERY EXECUTE query_sql
    USING p_query_embedding, p_user_id, p_field_name, p_provider, p_min_similarity, p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION rem_search IS
'REM SEARCH query: Vector similarity search using inner product for OpenAI normalized embeddings (0=different, 1=identical) scoped to user_id';

-- ============================================================================
-- UPDATE ALL_GRAPH_EDGES VIEW
-- ============================================================================

-- Update all_graph_edges view to include user_id for proper filtering
CREATE OR REPLACE VIEW all_graph_edges AS
SELECT id, tenant_id, user_id, 'resources'::varchar as entity_type, graph_edges FROM resources
UNION ALL
SELECT id, tenant_id, user_id, 'moments'::varchar as entity_type, graph_edges FROM moments
UNION ALL
SELECT id, tenant_id, user_id, 'users'::varchar as entity_type, graph_edges FROM users
UNION ALL
SELECT id, tenant_id, user_id, 'persons'::varchar as entity_type, graph_edges FROM persons
UNION ALL
SELECT id, tenant_id, user_id, 'files'::varchar as entity_type, graph_edges FROM files
UNION ALL
SELECT id, tenant_id, user_id, 'messages'::varchar as entity_type, graph_edges FROM messages
UNION ALL
SELECT id, tenant_id, user_id, 'image_resources'::varchar as entity_type, graph_edges FROM image_resources;

COMMENT ON VIEW all_graph_edges IS 'Unified view of graph edges from all entity tables for traversal (with user_id support)';

-- ============================================================================
-- RECORD MIGRATION
-- ============================================================================

INSERT INTO rem_migrations (name, type, version)
VALUES ('006_tenant_to_user_migration.sql', 'migration', '1.0.0')
ON CONFLICT (name) DO UPDATE
SET applied_at = CURRENT_TIMESTAMP,
    applied_by = CURRENT_USER;

-- ============================================================================
-- COMPLETION
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '============================================================';
    RAISE NOTICE 'REM Query Functions Migration Complete';
    RAISE NOTICE '============================================================';
    RAISE NOTICE '';
    RAISE NOTICE 'Updated functions:';
    RAISE NOTICE '  ✓ rem_lookup(entity_key, user_id)';
    RAISE NOTICE '  ✓ rem_fuzzy(query, user_id, threshold, limit)';
    RAISE NOTICE '  ✓ rem_search(embedding, table, field, user_id, provider, min_sim, limit)';
    RAISE NOTICE '  ✓ rem_traverse(entity_key, user_id, max_depth, rel_type)';
    RAISE NOTICE '';
    RAISE NOTICE '⚠️  BREAKING CHANGE: Application code must be updated!';
    RAISE NOTICE '   - Replace tenant_id parameter with user_id in all REM query calls';
    RAISE NOTICE '   - Update Python code in rem.services.rem module';
    RAISE NOTICE '   - Update CLI commands';
    RAISE NOTICE '   - Update tests';
    RAISE NOTICE '';
    RAISE NOTICE 'Next: Apply application layer changes';
    RAISE NOTICE '============================================================';
END $$;
