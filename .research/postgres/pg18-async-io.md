# PostgreSQL 18 - Async I/O & Performance Features for REM

## 1. Asynchronous I/O Subsystem

### What It Does
Queue multiple read requests concurrently instead of blocking on each. Up to **3x faster** sequential scans.

### REM Use Case: Vector Search & Batch Embedding Lookups
SEARCH queries scan `embeddings_*` tables with pgvector. Async I/O speeds up large vector scans.

```sql
-- postgresql.conf for EKS (io_uring on Linux 5.1+)
io_method = 'io_uring'
effective_io_concurrency = 200  -- high for EBS/network storage
maintenance_io_concurrency = 10

-- For local dev (macOS/Windows - no io_uring)
io_method = 'worker'
effective_io_concurrency = 4
```

### REM Use Case: Dreaming Workers - Vacuum Performance
Background dreaming workers trigger updates/inserts. Async vacuum keeps tables healthy without blocking.

```sql
-- Faster vacuum for high-write tables
ALTER TABLE resources SET (autovacuum_vacuum_cost_delay = 0);
ALTER TABLE embeddings_resources SET (autovacuum_vacuum_cost_delay = 0);
```

---

## 2. Cache Tier Elimination (KV_STORE Pattern)

### What It Does
With async I/O + large shared_buffers, PG18 replaces Redis/Memcached for hot-path reads.

### REM Use Case: KV_STORE for O(1) Lookups
REM's `KV_STORE` table already implements this pattern. PG18 makes it viable at scale.

```sql
-- postgresql.conf - size shared_buffers for your working set
shared_buffers = '4GB'  -- 25% of RAM for dedicated DB server
effective_cache_size = '12GB'  -- 75% of RAM

-- KV_STORE is already optimized for this
-- Triggers auto-populate on entity insert (see install.sql)
SELECT value FROM kv_store WHERE key = 'resources:sarah-chen';
```

```python
# rem/services/postgres/service.py - LOOKUP uses KV_STORE
async def execute_lookup(self, key: str, user_id: str):
    # O(1) lookup from KV_STORE - now faster with async I/O
    return await self.pool.fetchrow(
        "SELECT value FROM kv_store WHERE key = $1 AND user_id = $2",
        f"resources:{key}", user_id
    )
```

---

## 3. NUMA Awareness

### What It Does
Optimizes memory allocation on multi-socket servers to reduce cross-socket latency.

### REM Use Case: Large EKS Nodes
When running on large EC2 instances (r6i.8xlarge+), NUMA awareness improves memory-bound operations.

```sql
-- postgresql.conf (automatic in PG18, but can tune)
-- No explicit config needed - PG18 detects NUMA topology

-- Monitor NUMA allocation
SELECT * FROM pg_stat_bgwriter;
```

```yaml
# manifests/application/rem-stack/components/api/deployment.yaml
# Request NUMA-aware scheduling on large nodes
resources:
  requests:
    memory: "8Gi"
  limits:
    memory: "16Gi"
# Kubernetes will prefer NUMA-local allocation
```

---

## 4. AVX-512 for CRC32C

### What It Does
Hardware-accelerated checksums for WAL and data pages. Faster writes and replication.

### REM Use Case: High-Write Ingestion Pipeline
File processor and dreaming workers generate many writes. AVX-512 reduces CPU overhead.

```sql
-- Check if AVX-512 is being used
SHOW data_checksums;  -- should be 'on'

-- No config needed - PG18 auto-detects AVX-512
-- Benefit: faster COPY, INSERT, and streaming replication
```

```python
# rem/services/postgres/service.py - batch_upsert benefits
async def batch_upsert(self, table: str, records: list[dict], ...):
    # COPY is faster with AVX-512 checksums
    async with self.pool.acquire() as conn:
        await conn.copy_records_to_table(table, records=records)
```

---

## 5. SIMD-Optimized JSON Escaping

### What It Does
Faster JSON serialization using SIMD instructions.

### REM Use Case: JSONB Columns Everywhere
REM stores `metadata`, `graph_edges`, `spec` as JSONB. Faster escaping on read/write.

```sql
-- No config needed - automatic in PG18
-- Benefits these REM patterns:

-- Graph edges stored as JSONB array
SELECT graph_edges FROM resources WHERE label = 'sarah-chen';

-- Schema specs are large JSONB documents
SELECT spec FROM schemas WHERE name = 'contract-analyzer';

-- Metadata on every entity
SELECT metadata->'custom_field' FROM resources;
```

---

## 6. Self-Join Elimination

### What It Does
Query planner removes redundant self-joins automatically.

### REM Use Case: TRAVERSE Queries
Graph traversal can generate self-referential CTEs. PG18 optimizes these.

```sql
-- TRAVERSE generates recursive CTE - self-join elimination helps
WITH RECURSIVE graph AS (
    SELECT id, label, graph_edges, 0 as depth
    FROM resources WHERE label = 'sarah-chen'
    UNION ALL
    SELECT r.id, r.label, r.graph_edges, g.depth + 1
    FROM resources r
    JOIN graph g ON r.label = ANY(
        SELECT edge->>'dst' FROM jsonb_array_elements(g.graph_edges) edge
    )
    WHERE g.depth < 2
)
SELECT * FROM graph;
-- PG18 optimizes redundant joins in the recursive part
```

---

## Recommended PG18 Config for REM

```sql
-- postgresql.conf for production (EKS with EBS gp3)

# Async I/O (biggest win)
io_method = 'io_uring'
effective_io_concurrency = 200
maintenance_io_concurrency = 20

# Memory (cache tier elimination)
shared_buffers = '4GB'
effective_cache_size = '12GB'
work_mem = '256MB'

# WAL (AVX-512 benefits)
wal_buffers = '64MB'
checkpoint_completion_target = 0.9

# Autovacuum (async vacuum)
autovacuum_vacuum_cost_delay = 0
autovacuum_max_workers = 4
```

```yaml
# docker-compose.yml snippet
services:
  postgres:
    image: pgvector/pgvector:pg18
    command: >
      -c io_method=worker
      -c effective_io_concurrency=4
      -c shared_buffers=1GB
```

---

## Monitoring

```sql
-- Async I/O activity
SELECT * FROM pg_aios;

-- Check io_method in use
SHOW io_method;

-- Buffer cache hit ratio (should be >99% with proper shared_buffers)
SELECT
    sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) as cache_hit_ratio
FROM pg_statio_user_tables;
```

---

## Sources
- [PostgreSQL 18 Release Notes](https://www.postgresql.org/docs/current/release-18.html)
- [Phoronix: PostgreSQL 18 Released](https://www.phoronix.com/news/PostgreSQL-18-Released)
- [pganalyze: Async I/O Deep Dive](https://pganalyze.com/blog/postgres-18-async-io)
- [Neon: PostgreSQL 18 Async I/O](https://neon.com/postgresql/postgresql-18/asynchronous-io)
- [Better Stack: Complete Guide](https://betterstack.com/community/guides/databases/postgresql-asynchronous-io/)
