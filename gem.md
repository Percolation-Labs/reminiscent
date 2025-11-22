# Recursive Graph Traversal Comparison

## 1. Overview of Approaches

| Feature | Current `rem_traverse` | Proposed `traverse_graph` |
| :--- | :--- | :--- |
| **Graph Model** | **Implicit / Decentralized**<br>Edges stored in JSONB `graph_edges` column on each entity table. | **Explicit / Centralized**<br>Likely assumes a dedicated `edges` table or a centralized `nodes` table (implied by `kv_lookup` returning entity data directly). |
| **Polymorphism** | **Fully Supported**<br>Uses `all_graph_edges` VIEW to union all entity tables (`resources`, `moments`, `users`...) dynamically. | **Partial / Limited**<br>The snippet only joins `resources` table (`JOIN resources r ...`). It misses other entities (`users`, `moments`) unless `resources` is a super-table. |
| **Edge Filtering** | **JSONB Parsing**<br>Filters inside JSONB (`edge->>'rel_type'`). Slower but schema-less. | **Array Check**<br>`p_edge_types` check. Efficient if `rel_type` is a column; same speed if in JSONB. |
| **Lookup Strategy** | **Unified View + KV Store**<br>Joins `kv_store` to find IDs, then `all_graph_edges` view to find edges. | **KV Helper Function**<br>Uses `kv_lookup()` function. Cleaner syntax, but potentially hides complexity. |

---

## 2. Critical Critique of `traverse_graph` (The Proposed Snippet)

The provided snippet is "cleaner" but **fundamentally broken** for our specific architecture:

### ❌ Fatal Flaw: Single Table Assumption
The proposed query does `JOIN resources next ON next.id = kv.entity_id`.
*   **The Bug:** In our system, `kv.entity_id` might point to a `User`, `Moment`, or `File`, not just a `Resource`.
*   **The Consequence:** The traversal would **silently fail** or return incomplete data whenever the path crosses into a non-Resource entity (e.g., `Resource -> User -> Moment`).
*   **Our Fix:** Our `rem_traverse` correctly handles this by joining the polymorphic `all_graph_edges` view which unions all tables.

### ❌ Missing Edge Weight
*   **The Bug:** The snippet extracts `dst` and `rel_type` but ignores `weight`.
*   **The Consequence:** We lose the ability to filter by connection strength (e.g., "strong connections only") which is a core requirement of the REM graph model.

### ✅ Feature to Steal: Array-based Filtering
*   **The Good Idea:** `p_edge_types TEXT[]` with `edge.rel_type = ANY(p_edge_types)`.
*   **Why:** Our current implementation takes a single `p_rel_type VARCHAR`. Passing an array `['authored_by', 'owned_by']` is much more flexible than a single value.

### ✅ Feature to Steal: Cycle Detection logic
*   **The Good Idea:** `AND NOT (edge.dst = ANY(gt.path))`
*   **Status:** We actually *already* implemented this in our `rem_traverse`. It is the correct way to handle cycles in Postgres recursive CTEs.

---

## 3. Performance Implications

### `rem_traverse` (Current)
*   **Bottleneck:** The `all_graph_edges` view is a massive `UNION ALL` of 7+ tables.
*   **Impact:** Every recursive step forces Postgres to scan indexes on *all 7 tables* to find the matching ID.
*   **Verdict:** Slower per hop, but correct for polymorphic data.

### `traverse_graph` (Proposed)
*   **Bottleneck:** `CROSS JOIN LATERAL ... jsonb_array_elements`.
*   **Impact:** Expanding the JSON array into rows is CPU intensive if edge lists are huge (100s of edges per node).
*   **Verdict:** Standard overhead for JSON-based graphs. Unavoidable without a dedicated `edges` table.

---

## 4. Recommendation

**Do NOT switch** to the proposed `traverse_graph` logic as-is, because it breaks polymorphism (the "Single Table Assumption").

**DO improve** `rem_traverse` by adopting the **Array-based filtering**:
1.  Change `p_rel_type VARCHAR` -> `p_rel_types VARCHAR[]`.
2.  Update logic to `(p_rel_types IS NULL OR (edge->>'rel_type') = ANY(p_rel_types))`.

This gives us the flexibility of the proposed snippet without breaking our multi-table architecture.
