-- Fix recursive graph traversal by introducing a unified view
-- Date: 2025-11-22
-- Description: Creates a view unifying graph_edges from all entities and updates rem_traverse

-- 1. Create Unified View for Graph Edges
CREATE OR REPLACE VIEW all_graph_edges AS
SELECT id, tenant_id, 'resources'::varchar as entity_type, graph_edges FROM resources
UNION ALL
SELECT id, tenant_id, 'moments'::varchar as entity_type, graph_edges FROM moments
UNION ALL
SELECT id, tenant_id, 'users'::varchar as entity_type, graph_edges FROM users
UNION ALL
SELECT id, tenant_id, 'persons'::varchar as entity_type, graph_edges FROM persons
UNION ALL
SELECT id, tenant_id, 'files'::varchar as entity_type, graph_edges FROM files
UNION ALL
SELECT id, tenant_id, 'messages'::varchar as entity_type, graph_edges FROM messages
UNION ALL
SELECT id, tenant_id, 'image_resources'::varchar as entity_type, graph_edges FROM image_resources;

COMMENT ON VIEW all_graph_edges IS 'Unified view of graph edges from all entity tables for traversal';

-- 2. Drop old function signature to avoid ambiguity
DROP FUNCTION IF EXISTS rem_traverse(VARCHAR, VARCHAR, INTEGER, VARCHAR, VARCHAR);

-- 3. Update REM TRAVERSE function to support array-based edge filtering
CREATE OR REPLACE FUNCTION rem_traverse(
    p_entity_key VARCHAR(255),
    p_tenant_id VARCHAR(100),
    p_max_depth INTEGER DEFAULT 1,
    p_rel_types VARCHAR[] DEFAULT NULL,
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
        WHERE kv.tenant_id = p_tenant_id
        AND kv.entity_key = p_entity_key
        AND (p_user_id IS NULL OR kv.user_id = p_user_id OR kv.user_id IS NULL)

        UNION ALL

        -- Recursive case: Follow outbound edges from discovered entities
        SELECT
            gt.depth + 1,
            target_kv.entity_key,
            target_kv.entity_type,
            target_kv.entity_id,
            (edge->>'rel_type')::VARCHAR(100) AS rel_type,
            COALESCE((edge->'weight')::REAL, 1.0) AS rel_weight,
            gt.path || target_kv.entity_key AS path
        FROM graph_traversal gt
        -- Join to Unified View to get graph_edges
        JOIN all_graph_edges source_entity 
            ON source_entity.id = gt.entity_id 
            AND source_entity.entity_type = gt.entity_type
            AND source_entity.tenant_id = p_tenant_id
        -- Extract edges from JSONB array
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(source_entity.graph_edges, '[]'::jsonb)) AS edge
        -- Lookup target entity in KV store
        JOIN kv_store target_kv ON target_kv.entity_key = (edge->>'dst')::VARCHAR(255)
            AND target_kv.tenant_id = p_tenant_id
        WHERE gt.depth < p_max_depth
        -- Filter by relationship types if specified (Array check)
        AND (p_rel_types IS NULL OR (edge->>'rel_type')::VARCHAR(100) = ANY(p_rel_types))
        -- Prevent cycles by checking path
        AND NOT (target_kv.entity_key = ANY(gt.path))
        AND (p_user_id IS NULL OR target_kv.user_id = p_user_id OR target_kv.user_id IS NULL)
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
'REM TRAVERSE query: Recursive graph traversal following entity relationships via graph_edges.

This function allows for recursive exploration of the knowledge graph, starting from a given entity.
It supports limiting the traversal depth and filtering the types of edges followed using an array.

Parameters:
  - p_entity_key: The human-readable key of the starting entity (e.g., ''Project Plan'').
  - p_tenant_id: The tenant identifier for multi-tenancy.
  - p_max_depth: The maximum number of hops to traverse from the starting entity (default: 1).
  - p_rel_types: An optional ARRAY filter for relationship types (e.g., ARRAY[''referenced_by'', ''attendee'']). If NULL, all relationship types are followed.
  - p_user_id: An optional user ID for scoping.

Returns:
  A table of discovered entities, including their depth, key, type, ID, the relationship type and weight of the edge that led to them, and the full path taken.

Example Usage:
  -- Find all entities directly connected to ''Project Plan'' (depth 1)
  SELECT * FROM rem_traverse(''Project Plan'', ''your-tenant-id'');

  -- Find all entities connected to ''Project Plan'' up to 3 hops deep, following any edge type
  SELECT * FROM rem_traverse(''Project Plan'', ''your-tenant-id'', 3);

  -- Find all entities connected to ''Project Plan'' via ''referenced_by'' OR ''attendee'' edges, up to 2 hops
  SELECT * FROM rem_traverse(''Project Plan'', ''your-tenant-id'', 2, ARRAY[''referenced_by'', ''attendee'']);

  -- Find all persons who attended ''Engineering Sync''
  SELECT * FROM rem_traverse(''Engineering Sync'', ''your-tenant-id'', 1, ARRAY[''attendee'']);
';