# REM Agents

Built-in agents for REM system operations.

## Overview

This folder contains specialized agents that provide high-level interfaces for REM operations. These agents use LLMs to interpret natural language and convert it to structured REM queries.

## REM Query Agent

**File**: `rem_query_agent.py`

Converts natural language questions into structured REM queries with PostgreSQL dialect awareness.

### Features

- **Query Type Selection**: Automatically chooses optimal query type (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
- **PostgreSQL Dialect Aware**: Knows when to use KV_STORE vs primary tables
- **Token Optimized**: Minimal output fields for fast generation and low cost
- **Confidence Scoring**: Returns confidence (0-1) with reasoning for low scores
- **Multi-Step Planning**: Can break complex queries into multiple REM calls

### Usage

#### Simple Query

```python
from rem.agentic.agents import ask_rem

# Convert natural language to REM query
result = await ask_rem("Show me Sarah Chen")

print(result.query_type)  # QueryType.LOOKUP
print(result.parameters)  # {"entity_key": "sarah-chen"}
print(result.confidence)  # 1.0
```

#### With Custom Model

```python
# Use fast, cheap model for query generation
result = await ask_rem(
    "Find documents about databases",
    llm_model="gpt-4o-mini"
)

print(result.query_type)  # QueryType.SEARCH
print(result.parameters)
# {
#     "query_text": "database",
#     "table_name": "resources",
#     "field_name": "content",
#     "limit": 10
# }
```

#### Integration with RemService

```python
from rem.services.rem import RemService

# RemService automatically uses REM Query Agent
result = await rem_service.ask_rem(
    natural_query="What does Sarah manage?",
    tenant_id="acme-corp"
)

# Returns:
# {
#     "query_output": {
#         "query_type": "TRAVERSE",
#         "parameters": {"start_key": "sarah-chen", "max_depth": 1, "rel_type": "manages"},
#         "confidence": 0.85,
#         "reasoning": "TRAVERSE query to find entities Sarah manages via graph edges"
#     },
#     "results": [...],  # Executed query results (if confidence >= 0.7)
#     "natural_query": "What does Sarah manage?"
# }
```

### Query Types

| Type | Description | When to Use | Example |
|------|-------------|-------------|---------|
| `LOOKUP` | O(1) entity lookup by natural key | User references specific entity by name | "Show me Sarah Chen" |
| `FUZZY` | Trigram text similarity (pg_trgm) | Partial/misspelled names, approximate matches | "Find people named Sara" |
| `SEARCH` | Semantic vector similarity | Conceptual questions, semantic similarity | "Documents about databases" |
| `SQL` | Direct table queries with WHERE | Temporal, filtered, or aggregate queries | "Meetings in Q4 2024" |
| `TRAVERSE` | Recursive graph traversal | Relationships, connections, "what's related" | "What does Sarah manage?" |

### Configuration

Set the model for REM Query Agent in your environment:

```bash
# .env
LLM__QUERY_AGENT_MODEL=gpt-4o-mini  # Fast, cheap model recommended
```

If not set, uses `settings.llm.default_model`.

### Output Schema

```python
class REMQueryOutput(BaseModel):
    query_type: QueryType  # Selected query type
    parameters: dict       # Query parameters
    confidence: float      # 0.0-1.0 confidence score
    reasoning: str | None  # Only if confidence < 0.7 or multi-step
    multi_step: list[dict] | None  # For complex queries
```

### Design Philosophy

1. **Token Efficiency**: Output is concise by design
   - Reasoning only included when needed (low confidence or multi-step)
   - Minimal fields to reduce generation time and cost

2. **PostgreSQL Awareness**: Agent knows the database schema
   - LOOKUP/FUZZY use UNLOGGED KV_STORE (fast cache)
   - SEARCH joins KV_STORE + embeddings_<table>
   - SQL queries primary tables directly
   - TRAVERSE follows graph_edges JSONB field

3. **Progressive Complexity**: Prefer simple queries over complex
   - LOOKUP is fastest (O(1))
   - FUZZY uses indexed trigrams
   - SEARCH requires embedding generation
   - SQL scans tables (filtered)
   - TRAVERSE is recursive (most complex)

4. **Confidence-Based Execution**: RemService auto-executes if confidence >= 0.7
   - High confidence: Execute immediately
   - Low confidence: Return query + reasoning for review

### Testing

See `tests/unit/agentic/agents/test_rem_query_agent.py` for unit tests.

Tests cover:
- Schema structure validation
- Output model creation
- Confidence validation
- Multi-step query support

Integration tests with actual LLM execution require API keys and are in `tests/integration/`.

## Future Agents

Additional agents can be added following the same pattern:

- **Entity Summarization Agent**: Summarize entity relationships
- **Query Explanation Agent**: Explain REM query results in natural language
- **Schema Discovery Agent**: Discover available tables and fields
- **Data Quality Agent**: Identify data quality issues in entities
