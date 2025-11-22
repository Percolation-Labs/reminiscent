# Session Management for REM

This module implements session persistence, compression, and reloading for conversation continuity in the REM chat completions API.

## Overview

The session management system enables multi-turn conversations by:
1. **Saving** all chat messages to the database
2. **Compressing** long assistant responses with REM LOOKUP keys
3. **Reloading** conversation history on subsequent requests
4. **Gracefully degrading** when Postgres is disabled

## Architecture

### Components

```
services/session/
├── compression.py       # Message compression and storage
├── reload.py           # Session history reloading
└── __init__.py         # Public API
```

### Database Schema

Messages are stored in the `messages` table (inherited from CoreModel):

```sql
CREATE TABLE messages (
    id UUID PRIMARY KEY,
    content TEXT NOT NULL,
    message_type VARCHAR,  -- 'user', 'assistant', 'system'
    session_id VARCHAR,    -- Groups messages by conversation
    tenant_id VARCHAR,     -- Optional: for future multi-tenant SaaS use
    user_id VARCHAR NOT NULL,  -- User ownership (primary isolation scope)
    metadata JSONB,        -- Contains entity_key, message_index, timestamp
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP
);

-- Indexes for fast retrieval
CREATE INDEX idx_messages_session ON messages(session_id, user_id);
CREATE INDEX idx_messages_entity_key ON messages((metadata->>'entity_key'));
```

## Key Features

### 1. Message Compression

Long assistant responses (>400 chars) are compressed to save context window space:

```python
from rem.services.session import MessageCompressor

compressor = MessageCompressor(truncate_length=200)

# Long message
long_msg = {"role": "assistant", "content": "A" * 1000}

# Compress with REM LOOKUP key
compressed = compressor.compress_message(long_msg, entity_key="session-123-msg-5")

# Result:
# {
#   "role": "assistant",
#   "content": "AAAA...[first 200 chars]...\n\n... [Message truncated - REM LOOKUP session-123-msg-5 to recover full content] ...\n\n...[last 200 chars]...AAAA",
#   "_compressed": True,
#   "_original_length": 1000,
#   "_entity_key": "session-123-msg-5"
# }
```

**Benefits:**
- Keeps conversation history within LLM context windows
- Full messages stored in database for audit trail
- Retrieved on-demand via REM LOOKUP queries
- Compression markers visible to LLM for awareness

### 2. Session Reloading

Load full conversation history for session continuity:

```python
from rem.services.session import reload_session
from rem.services.postgres import get_postgres_service

db = get_postgres_service()

# Reload conversation
history = await reload_session(
    db=db,
    session_id="session-abc-123",
    user_id="alice",
    decompress_messages=False  # Use compressed versions
)

# Returns:
# [
#   {"role": "user", "content": "What is REM?"},
#   {"role": "assistant", "content": "REM is..."},
#   {"role": "user", "content": "Tell me more"},
#   {"role": "assistant", "content": "...compressed with LOOKUP key..."}
# ]
```

**Options:**
- `decompress_messages=False`: Fast, uses compressed versions (default)
- `decompress_messages=True`: Slower, fetches full content via LOOKUP

### 3. REM LOOKUP Pattern

Compressed messages use entity keys for retrieval:

```python
from rem.services.session import SessionMessageStore
from rem.services.postgres import get_postgres_service

db = get_postgres_service()
store = SessionMessageStore(user_id="alice")

# Entity key format: session-{session_id}-msg-{index}
entity_key = "session-abc-123-msg-5"

# Retrieve full message via LOOKUP
full_content = await store.retrieve_message(entity_key)

# SQL executed:
# SELECT * FROM messages
# WHERE metadata->>'entity_key' = 'session-abc-123-msg-5'
#   AND user_id = 'alice'
# LIMIT 1
```

**Key Format:**
- Pattern: `session-{session_id}-msg-{message_index}`
- Example: `session-abc-123-msg-5` (5th message in session abc-123)
- Enables O(1) LOOKUP via JSONB index

## Usage in Chat Completions

### Integration Pattern

The chat completions endpoint (`rem/src/rem/api/routers/chat/completions.py`) integrates session management:

```python
@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionRequest, request: Request):
    # 1. Extract context from headers
    context = AgentContext.from_headers(dict(request.headers))
    db = get_postgres_service()

    # 2. Reload session history
    history = []
    if context.session_id and db:
        history = await reload_session(
            db=db,
            session_id=context.session_id,
            user_id=context.user_id or "default",
            decompress_messages=False
        )

    # 3. Run agent with history
    agent = await create_pydantic_ai_agent(context, agent_schema, body.model)
    result = await agent.run(prompt)

    # 4. Save new messages
    if context.session_id and db:
        store = SessionMessageStore(db=db, user_id=context.user_id or "default")
        await store.store_session_messages(
            session_id=context.session_id,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result.output}
            ],
            compress=True
        )

    return response
```

### Client Request

Include session context in HTTP headers:

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "X-Session-Id: session-abc-123" \
  -H "X-User-Id: alice" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai:gpt-4o-mini",
    "messages": [{"role": "user", "content": "What did we discuss earlier?"}],
    "stream": false
  }'
```

**Headers:**
- `X-User-Id`: User identifier (required, default: "default")
- `X-Session-Id`: Session/conversation identifier (optional)

## Testing

### Unit Tests

```bash
# Run session management tests
pytest rem/tests/integration/test_session_management.py -v

# Test message compression
pytest rem/tests/integration/test_session_management.py::test_message_compressor -v

# Test session reloading
pytest rem/tests/integration/test_session_management.py::test_reload_session -v
```

### Integration Tests

```bash
# End-to-end completions with sessions
pytest rem/tests/integration/test_completions_with_sessions.py -v

# Test session continuity
pytest rem/tests/integration/test_completions_with_sessions.py::test_completions_with_session_continuity -v

# Test tenant isolation
pytest rem/tests/integration/test_completions_with_sessions.py::test_completions_tenant_isolation -v
```

### Sample Data

Seed the database with realistic conversation data:

```bash
# Seed all sample conversations
python -m rem.tests.scripts.seed_sample_sessions --all

# Seed specific conversation
python -m rem.tests.scripts.seed_sample_sessions \
  --conversation rem_intro \
  --user-id alice

# Demonstrate LOOKUP retrieval
python -m rem.tests.scripts.seed_sample_sessions \
  --demo-lookup \
  --session-id <session-id> \
  --user-id alice
```

Sample conversations available:
- `rem_intro`: Introduction to REM concepts
- `technical_deep_dive`: InlineEdge and TRAVERSE queries
- `practical_implementation`: Session logging setup guide
- `compression_test`: Very long response for compression testing
- `multi_turn`: Multi-turn technical Q&A

## Performance Considerations

### Context Window Management

**Problem:** LLMs have limited context windows (8K-200K tokens)

**Solution:** Message compression
- Short messages: Stored as-is
- Long messages (>400 chars): Compressed with LOOKUP keys
- LLM sees truncated versions in history
- Full content available via LOOKUP if needed

**Benefits:**
- Fit 10-20 turns in 8K context window
- Full audit trail preserved in database
- Configurable compression threshold

### Database Performance

**Optimizations:**
- Composite index on `(session_id, tenant_id)` for fast session queries
- JSONB GIN index on `metadata` for LOOKUP queries
- `created_at` for chronological ordering
- Soft deletes via `deleted_at` (no hard deletes)

**Query Performance:**
- Session reload: O(n) where n = messages in session
- LOOKUP retrieval: O(1) with JSONB index
- Tenant isolation: Enforced at query level

## Graceful Degradation

When Postgres is disabled (`POSTGRES__ENABLED=false`):

```python
# All operations skip database gracefully
if not settings.postgres.enabled:
    logger.debug("Postgres disabled, skipping session management")
    return []
```

**Behavior:**
- `reload_session()` returns empty list
- `store_session_messages()` no-ops
- No errors raised
- Chat completions work without history

## Design Principles

1. **LOOKUP-First**: Entity keys enable O(1) retrieval
2. **User Isolation**: All queries scoped by user_id
3. **Graceful Degradation**: Works without database
4. **Compression-Aware**: LLM sees compression markers
5. **Audit Trail**: Full messages always stored
6. **Natural Keys**: Human-readable entity key format

## Future Enhancements

### Token Tracking (TODO)

Track token usage per session for cost analysis:

```python
# Store usage metadata
metadata = {
    "entity_key": "session-123-msg-5",
    "usage": {
        "prompt_tokens": 1500,
        "completion_tokens": 800,
        "total_tokens": 2300,
        "model": "gpt-4o",
        "estimated_cost": 0.046
    }
}
```

### Context Window Optimization

Implement sliding window with summarization:

```python
# Keep recent N messages verbatim
# Summarize older messages
# Discard ancient messages

history = [
    {"role": "system", "content": "Summary of messages 1-10: ..."},
    *recent_messages[-5:]  # Last 5 turns
]
```

### Multi-Session Retrieval

Load related sessions for context:

```python
# Find related sessions by user or topic
related_sessions = await find_related_sessions(
    user_id="alice",
    topic_tags=["rem-architecture"],
    limit=3
)
```

## Related Documentation

- [Message Entity Model](../../models/entities/message.py)
- [Repository Pattern](../postgres/repository.py)
- [AgentContext](../../agentic/context.py)
- [Chat Completions API](../../api/routers/chat/completions.py)
- [REM Query System](../../models/core/rem_query.py)

## References

Inspired by p8fs-modules session management:
- `p8fs/src/p8fs/services/llm/session_messages.py` - Compression pattern
- `p8fs/src/p8fs/services/llm/audit_mixin.py` - Session lifecycle
- `p8fs/src/p8fs/services/llm/models.py` - CallingContext pattern
