# PostgreSQL 17 & 18 Features for REM

## PostgreSQL 17 (Sept 2024)

| Feature | REM Use Case |
|---------|--------------|
| **JSON_TABLE()** | Convert JSONB metadata/graph_edges to relational format |
| **Incremental Backups** | `pg_basebackup --incremental` for faster DR |
| **COPY ON_ERROR** | Resilient bulk imports for file processor |
| **MERGE + RETURNING** | Upsert with audit trail in one query |
| **Vacuum 20x less memory** | Better for high-write dreaming workers |
| **Streaming I/O for seq scans** | Faster full-table scans on embeddings |
| **pg_maintain role** | Non-owner maintenance in multi-tenant |

```sql
-- JSON_TABLE: flatten graph edges
SELECT * FROM resources r,
  JSON_TABLE(r.graph_edges, '$[*]' COLUMNS (
    dst TEXT PATH '$.dst',
    rel_type TEXT PATH '$.rel_type'
  )) AS edges;

-- COPY with error handling
COPY resources FROM '/data/import.csv' WITH (ON_ERROR 'ignore');
```

**Links:**
- [Official Release](https://www.postgresql.org/about/news/postgresql-17-released-2936/)
- [Release Notes](https://www.postgresql.org/docs/17/release-17.html)
- [EDB Feature Overview](https://www.enterprisedb.com/blog/exploring-postgresql-17-new-features-enhancements)

---

## PostgreSQL 18 (Sept 2025)

| Feature | REM Use Case |
|---------|--------------|
| **Async I/O (io_uring)** | 3x faster vector scans, vacuum |
| **UUIDv7 native** | Sortable IDs for resources/moments |
| **Skip scan on B-tree** | Faster partial-index queries |
| **Virtual generated columns** | Computed fields without storage |
| **RETURNING OLD/NEW** | Audit logs in single DML |
| **NOT NULL as NOT VALID** | Zero-downtime schema migrations |
| **OAuth 2.0 auth** | Direct IdP integration |
| **WITHOUT OVERLAPS** | Temporal validity for entities |
| **Parallel GIN index builds** | Faster full-text index creation |
| **Data checksums default** | On-disk integrity guaranteed |

```sql
-- UUIDv7: time-sortable IDs
ALTER TABLE resources ALTER COLUMN id SET DEFAULT uuidv7();

-- RETURNING with old/new values
UPDATE resources SET metadata = '{}'
RETURNING OLD.metadata as before, NEW.metadata as after;

-- Zero-downtime constraint
ALTER TABLE resources ADD CONSTRAINT nn CHECK (label IS NOT NULL) NOT VALID;
-- Later: VALIDATE CONSTRAINT nn;

-- Temporal: no overlapping validity periods
CREATE TABLE entity_versions (
  id UUID, valid_from TIMESTAMPTZ, valid_to TIMESTAMPTZ,
  PRIMARY KEY (id, valid_from, valid_to) WITHOUT OVERLAPS
);
```

**Links:**
- [Official Release](https://www.postgresql.org/about/news/postgresql-18-released-3142/)
- [Release Notes](https://www.postgresql.org/docs/current/release-18.html)
- [Neon: PG18 Features](https://neon.com/postgresql/postgresql-18-new-features)
- [Bytebase: DBA Perspective](https://www.bytebase.com/blog/what-is-new-in-postgres-18/)
- [Xata: Deep Dive](https://xata.io/blog/going-down-the-rabbit-hole-of-postgres-18-features)

---

## See Also

- [pg18-async-io.md](./pg18-async-io.md) - Detailed async I/O config for REM
