# Database Design Principles

Effective database design is crucial for building scalable applications.

## Relational Database Design

### Normalization
Organize data to reduce redundancy and improve data integrity:
- **1NF**: Atomic values, no repeating groups
- **2NF**: No partial dependencies on composite keys
- **3NF**: No transitive dependencies
- **BCNF**: Stricter version of 3NF

### Denormalization
Strategically introduce redundancy for performance:
- Materialized views for complex aggregations
- Caching frequently accessed data
- Pre-computed join tables

## Indexing Strategies

### B-Tree Indexes
Default index type for range queries and sorting. Efficient for:
- Equality comparisons (=)
- Range queries (>, <, BETWEEN)
- ORDER BY operations

### Hash Indexes
Optimized for exact match lookups. Fast for equality comparisons but cannot handle range queries.

### Full-Text Search Indexes
Specialized indexes for text search (GIN, GiST in PostgreSQL). Support:
- Fuzzy matching
- Phrase search
- Ranking by relevance

### Vector Indexes (pgvector)
Enable similarity search using embeddings:
- IVFFlat: Inverted file index for approximate search
- HNSW: Hierarchical navigable small world graphs

## Query Optimization
- Use EXPLAIN ANALYZE to understand query execution
- Avoid SELECT * in production code
- Use appropriate JOIN types (INNER, LEFT, RIGHT)
- Partition large tables by date or other keys
- Consider read replicas for scaling reads

## Transaction Isolation
- READ UNCOMMITTED: No isolation (avoid)
- READ COMMITTED: Default in PostgreSQL
- REPEATABLE READ: Snapshot isolation
- SERIALIZABLE: Strictest isolation level
