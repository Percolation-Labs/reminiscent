# Moments: Session Compression and Long-Term Memory

## Overview

The Moment Builder system provides **automatic session compression** for indefinite conversations. As sessions grow, the system:
1. **Triggers asynchronously** when context/message thresholds are crossed
2. **Creates discrete moments** summarizing what happened in the window
3. **Updates user summary** with evolving interests and preferences
4. **Filters session history** to only recent messages on load
5. **Points the LLM** to user profile and moment keys for deeper context

This enables conversations to continue indefinitely while maintaining relevant context without context window exhaustion.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           STREAMING API FLOW                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  [User Message] ──► [Stream Response] ──► [Send to User] ──► [Check Thresholds] │
│                                                                     │            │
│                         ┌───────────────────────────────────────────┘            │
│                         │                                                        │
│                         ▼                                                        │
│            ┌────────────────────────────────────┐                               │
│            │  session.message_count > threshold │                               │
│            │  OR                                │                               │
│            │  session.total_tokens > threshold  │                               │
│            └────────────────────────────────────┘                               │
│                         │                                                        │
│                         ▼ (async, fire-and-forget)                              │
│            ┌────────────────────────────────────┐                               │
│            │  POST /api/v1/moments/build        │                               │
│            │  {session_id, user_id}             │                               │
│            └────────────────────────────────────┘                               │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                         MOMENT BUILDER PROCESS                                   │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  [Load Unprocessed Messages]                                                    │
│         │                                                                        │
│         ▼                                                                        │
│  [LLM: Moment Builder Agent]  ◄─── Dynamic prompt from Resource entity          │
│         │                                                                        │
│         ├──► [Create Moment(s)]                                                 │
│         │    - name: "discussion-on-2025-01-26-api-design"                      │
│         │    - category: "session-compression"                                   │
│         │    - summary: "User discussed API design patterns..."                 │
│         │    - topic_tags: ["api-design", "rest", "authentication"]             │
│         │    - emotion_tags: ["focused", "curious"]                             │
│         │    - starts_timestamp / ends_timestamp                                │
│         │    - source_session_id: (link to session)                             │
│         │                                                                        │
│         └──► [Update User.summary]                                              │
│              - Merge new interests with existing                                 │
│              - Update preferred_topics                                           │
│              - Fold in recent activity                                          │
│         │                                                                        │
│         └──► [Insert Partition Event] (if insert_partition_event=True)          │
│              - message_type: "tool", tool_name: "session_partition"             │
│              - Contains: user_key, moment_keys, summary                         │
│              - Marks boundary - no need to look back beyond this                │
│         │                                                                        │
│         └──► [Update session.last_moment_message_idx]                           │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────┐
│                        CONTEXT LOADING (Reader)                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  load_session_messages(session_id, max_messages=50)                             │
│         │                                                                        │
│         ├──► [DB: CTE for last N messages in conversation order]                │
│         │                                                                        │
│         └──► [Check for partition event in loaded messages]                     │
│              │                                                                   │
│              ├─► If partition event found:                                      │
│              │   - Context keys already in session data                         │
│              │   - No extra context_builder hints needed                        │
│              │   - LLM uses rem://moments/* and rem://users/* resources         │
│              │                                                                   │
│              └─► If no partition event:                                         │
│                  - Add recent moment keys to context hint                       │
│                  - Add user profile key                                         │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Data Model

### Settings (new)

```python
# rem/src/rem/settings.py

class MomentBuilderSettings(BaseSettings):
    """Settings for automatic moment building."""

    enabled: bool = False  # Master switch

    # Thresholds (whichever is hit first triggers moment building)
    message_threshold: int = 250     # Trigger after ~250 exchanges
    token_threshold: int = 100000    # Trigger after 100K tokens (~50-78% context)

    # Context loading limits
    load_max_messages: int = 50      # Max messages to load via CTE

    # Session partition event (inserted at compression boundary)
    # When True: partition event contains user_key + moment_keys, no extra hints needed
    # When False: context_builder adds user/moment hints separately
    insert_partition_event: bool = True

    # Recent moments to show in context hint (only used if insert_partition_event=False)
    recent_moment_count: int = 5

    # Optional: Custom moment builder prompt resource
    # If set, loads prompt from Resource entity instead of default
    prompt_resource_uri: str | None = None
```

### Moment Entity (existing, minor additions)

```python
# rem/src/rem/models/entities/moment.py

class Moment(CoreModel):
    # ... existing fields ...

    # New: Link moment to source session
    source_session_id: str | None = Field(
        default=None,
        description="Session ID this moment was extracted from"
    )

    # New: Category for filtering
    category: str | None = Field(
        default=None,
        description="Moment category (e.g., 'session-compression', 'meeting', 'coding-session')"
    )

    # New: Chain to previous moments for backwards traversal
    previous_moment_keys: list[str] = Field(
        default_factory=list,
        description="Keys of 1-3 preceding moments, enabling LLM to chain backwards through history"
    )
```

### Session Entity (add tracking field)

```python
# rem/src/rem/models/entities/session.py

class Session(CoreModel):
    # ... existing fields ...

    # Track which messages have been processed into moments
    last_moment_message_idx: int | None = Field(
        default=None,
        description="Index of last message included in a moment"
    )
```

### Message Entity (optional: add processed flag)

```python
# Alternative to session.last_moment_message_idx
# If we need per-message granularity

class Message(CoreModel):
    # ... existing fields ...

    moment_id: str | None = Field(
        default=None,
        description="ID of moment this message was compressed into"
    )
```

### Session Partition Event

When `insert_partition_event=True` (default), the moment builder inserts a special tool-like message at the compression boundary. This event contains all context keys needed to understand history before that point.

**Why this matters:**
- When loading session messages, if a partition event is found, no need to look further back
- The event itself contains user profile key and moment keys
- Context builder doesn't need to add extra hints - they're already in the session data
- Simplifies the loading logic to just a SQL filter with CTE

**Partition Event Format (stored as message_type="tool"):**

```json
{
  "role": "tool",
  "tool_name": "session_partition",
  "content": {
    "partition_type": "moment_compression",
    "created_at": "2025-01-26T10:30:00Z",
    "user_key": "user-abc123",
    "moment_keys": [
      "moment-2025-01-26-api-design",
      "moment-2025-01-25-docker-debugging"
    ],
    "last_n_moment_keys": [
      "moment-2025-01-26-api-design",
      "moment-2025-01-25-docker-debugging",
      "moment-2025-01-24-auth-implementation",
      "moment-2025-01-23-project-setup",
      "moment-2025-01-22-initial-setup"
    ],
    "recent_moments_summary": "Recent journey: User set up their project environment (Jan 22), implemented authentication (Jan 23-24), debugged Docker networking issues (Jan 25), and is now designing the REST API with focus on authentication endpoints (Jan 26).",
    "messages_compressed": 50,
    "summary": "Compressed 50 messages into 2 moments covering API design and Docker debugging."
  }
}
```

**How it appears in context:**

```
[TOOL RESULT: session_partition]
{
  "partition_type": "moment_compression",
  "user_key": "user-abc123",
  "moment_keys": ["moment-2025-01-26-api-design", "moment-2025-01-25-docker-debugging"],
  "last_n_moment_keys": ["moment-2025-01-26-api-design", "moment-2025-01-25-docker-debugging", "moment-2025-01-24-auth-implementation", "moment-2025-01-23-project-setup", "moment-2025-01-22-initial-setup"],
  "recent_moments_summary": "Recent journey: User set up their project (Jan 22), implemented auth (Jan 23-24), debugged Docker (Jan 25), now designing REST API (Jan 26).",
  "summary": "Compressed 50 messages. Use rem://moments/key/{key} for full context."
}
[/TOOL RESULT]

[Conversation continues from here with recent messages...]
```

**Key fields for LLM awareness:**
- `moment_keys`: Keys from THIS compaction (just created)
- `last_n_moment_keys`: Last N moment keys overall (for full backwards navigation)
- `recent_moments_summary`: Brief narrative of the user's recent journey across all moments

**Loading behavior:**

1. Load last N messages via CTE (e.g., last 100)
2. If partition event found in loaded messages:
   - Context keys are already present (user_key, moment_keys)
   - LLM can read `rem://moments/key/{key}` or `rem://users/{key}` resources on-demand
   - No extra context_builder hints needed
3. If no partition event found:
   - Fall back to adding recent moment keys to context hint
   - Add user profile key for on-demand lookup

**Session Recovery Pattern:**

Session recovery is just message loading with the CTE query. The lag mechanism ensures the partition event appears as a "distant memory" rather than right before recent messages:

```
Load last 100 messages:
├── [Partition Event]   ◄── Summary + moment_keys + REM LOOKUP hints
├── [Recent messages]   ◄── Lag buffer (recent conversation)
└── [User's new input]
```

The partition event is compact - it contains:
- `moment_keys`: References to detailed moments (in moments table)
- `recent_moments_summary`: Brief narrative of what was discussed
- `recovery_hint`: Instructions to use REM LOOKUP if needed

The LLM only loads moments on-demand via REM LOOKUP when the partition summary isn't enough.

## Compaction Strategy

### What Gets Compacted

The moment builder compacts these message types into moments:
- **user** messages
- **assistant** messages
- **tool** messages (tool calls and results)

**NOT compacted** (preserved in session):
- **session_partition** events (the compaction boundary markers themselves)

### Lag Mechanism (Critical Design)

The moment builder uses a **lag mechanism** to ensure partition events appear "in the past" rather than right before recent messages. This is critical for a natural conversation flow.

**Why lag matters:**
- Without lag, the partition event would appear immediately before the most recent messages
- This would confuse the LLM with a memory checkpoint right in the middle of active conversation
- With lag, the partition event appears as a "distant memory" checkpoint

**How it works:**

```
Session with 250 messages (or 100K tokens), lag=30%:

Messages 1-175:   ──► Summarized into Moment (stored in moments table, NOT in session)
                     Partition event inserted at message 175's timestamp
Messages 176-250: ──► Recent conversation (~75 messages / ~30K tokens)

What LLM sees on reload:
├── [Partition Event]   ◄── Single message: summary + moment_keys + REM LOOKUP hints
├── [Messages 176-250]  ◄── Recent conversation (~75 messages)
```

The partition event is a compact checkpoint containing:
- `moment_keys`: Keys to lookup full moment details
- `recent_moments_summary`: Brief narrative of compressed history
- `recovery_hint`: Instructions to use REM LOOKUP if needed

Moments live in their own table - they don't clog the session.

**Configuration:**
```bash
# Minimum messages to keep after partition (absolute)
MOMENT_BUILDER__LAG_MESSAGES=10

# Percentage of messages to keep after partition (0.1-0.5)
MOMENT_BUILDER__LAG_PERCENTAGE=0.3
```

The actual lag is `max(lag_messages, total_messages * lag_percentage)`.

### Compaction Window

Compaction is **incremental** - only process messages since the last compaction:

```
Session Timeline (with lag=30%):

First compaction (50 messages accumulated):
├── Messages 1-35   ──► Compressed into Moment A (stored in moments table)
├── Partition Event ◄── Inserted at message 35's timestamp
├── Messages 36-50  ──► Kept as recent context (lag buffer)

Second compaction (100 messages accumulated):
├── Partition Event A  ◄── Previous checkpoint
├── Messages 36-70     ──► Compressed into Moment B
├── Partition Event B  ◄── Inserted at message 70's timestamp
├── Messages 71-100    ──► Recent context (lag buffer)
```

Key: Moments are in the `moments` table. Only partition events (compact summaries) are in the session.

**Query for unprocessed messages:**
```sql
SELECT * FROM messages
WHERE session_id = $1
  AND user_id = $2
  AND created_at > (
    SELECT COALESCE(MAX(created_at), '1970-01-01')
    FROM messages
    WHERE session_id = $1
      AND message_type = 'tool'
      AND content::jsonb->>'tool_name' = 'session_partition'
  )
  AND NOT (message_type = 'tool' AND content::jsonb->>'tool_name' = 'session_partition')
ORDER BY created_at ASC;
```

### Backwards Chaining via `previous_moment_keys`

Each moment stores keys of the 1-3 preceding moments, enabling the LLM to chain backwards through history:

```
Moment C
├── previous_moment_keys: ["moment-B", "moment-A"]
├── summary: "Discussed deployment strategy..."
└── (LLM can read moment-B or moment-A for deeper context)

Moment B
├── previous_moment_keys: ["moment-A"]
├── summary: "Set up Docker environment..."
└── ...

Moment A
├── previous_moment_keys: []  # First moment, no predecessors
├── summary: "Initial project discussion..."
└── ...
```

This allows the LLM to navigate arbitrarily far back in history by following the chain, without needing to load all moments upfront.

## API Endpoints

### Build Moments (async trigger)

```
POST /api/v1/moments/build
```

**Request:**
```json
{
  "session_id": "uuid",
  "user_id": "uuid",
  "force": false  // Optional: bypass threshold check
}
```

**Response:**
```json
{
  "status": "accepted",
  "job_id": "uuid"  // For tracking if needed
}
```

This endpoint:
1. Accepts immediately (202 Accepted)
2. Queues background task to run moment builder
3. Returns job_id for optional status tracking

### List Moments (for LLM tool)

```
GET /api/v1/moments?user_id={user_id}&category={category}&limit={limit}&offset={offset}
```

**Response:**
```json
{
  "moments": [
    {
      "key": "moment-2025-01-25-docker-debugging",
      "summary": "Debugging Docker networking issues...",
      "topic_tags": ["docker", "networking"],
      "starts_timestamp": "2025-01-25T10:00:00Z",
      "ends_timestamp": "2025-01-25T11:30:00Z"
    }
  ],
  "total": 42,
  "has_more": true
}
```

### Get Moment Detail

```
GET /api/v1/moments/{moment_key}
```

Returns full moment with all fields.

## MCP Resources

Moments are exposed as MCP resources (read-only data), not tools.

**Important:** All moment resources are **user-scoped**. The user_id is derived from the MCP connection context (JWT/session), not from the URI. This ensures users can only access their own moments.

### Resource URIs

```
rem://moments                              # Page 1 of moment keys (most recent 25, user-scoped)
rem://moments/1                            # Same as above (page 1)
rem://moments/2                            # Page 2 (next 25, going backwards in time)
rem://moments/3                            # Page 3, etc.
rem://moments/key/{moment-key}             # Get specific moment detail (must belong to user)
```

**Pagination:** Page size is 25. Pages go backwards in time (page 1 = most recent).

### read_resource: rem://moments/{page} (paginated keys + dates, user-scoped)

```python
@server.read_resource()
async def read_moments_page(uri: str, context: AgentContext) -> str:
    """
    List moment keys for a specific page (25 per page, most recent first).

    URI: rem://moments or rem://moments/{page_number}
    - rem://moments or rem://moments/1 = page 1 (most recent 25)
    - rem://moments/2 = page 2 (next 25, going backwards in time)

    User scoping: Only returns moments where user_id matches context.user_id.

    Returns JSON with paginated moment keys:
    {
      "page": 1,
      "page_size": 25,
      "total_pages": 3,
      "total_moments": 67,
      "moments": [
        {"key": "moment-2025-01-26-api-design",
         "date": "2025-01-26",
         "time_range": "10:00-11:30",
         "topics": ["api-design", "authentication"]},
        {"key": "moment-2025-01-25-docker",
         "date": "2025-01-25",
         "time_range": "14:00-15:00",
         "topics": ["docker", "debugging"]}
      ]
    }

    LLM uses these keys to decide which moments to read in full
    via rem://moments/key/{moment-key}.
    """
```

### read_resource: rem://moments/key/{moment-key} (full detail, user-scoped)

```python
@server.read_resource()
async def read_moment_detail(uri: str, context: AgentContext) -> str:
    """
    Read a specific moment resource by key.

    URI format: rem://moments/key/{moment-key}

    User scoping: Query filters by BOTH moment key AND user_id.
    Returns 404 if moment doesn't exist or belongs to different user.

    Returns full JSON with:
    - summary (detailed description)
    - topic_tags, emotion_tags
    - starts_timestamp, ends_timestamp
    - present_persons
    - source_session_id
    """
```

**Security note:** Moment keys are looked up with user_id filter to prevent cross-user access. Integration test required to verify user A cannot read user B's moments even with valid key.

## Moment Builder Agent

The moment builder is an LLM agent that **models the user's journey** by observing:
- **User messages**: What questions they ask, what they're trying to accomplish
- **Assistant responses**: What guidance/answers were provided
- **Tool calls**: What actions were taken, what data was retrieved

The prompt can be customized via `settings.moment_builder.prompt_resource_uri` to change how the journey is modeled. By default, it creates discrete moments capturing conversation segments and updates the user's evolving profile.

### Default Prompt (can be overridden via Resource)

```markdown
# Moment Builder - User Journey Observer

You are observing a user's journey through a conversation. Your job is to:

1. **Model the User's Journey**
   - What was the user trying to accomplish?
   - What challenges or questions did they face?
   - How did the conversation evolve?
   - What was resolved vs left open?

2. **Create Discrete Moments**
   - Each moment = a distinct segment of the journey
   - Include: what happened, what was learned, what changed
   - Tag with topics (technical concepts) and emotions (user state)
   - Write a narrative summary (2-3 sentences)

3. **Update User Profile**
   - What new interests emerged?
   - What expertise level was demonstrated?
   - What preferences or patterns were observed?
   - Merge with existing profile, don't replace

## Input

You receive the conversation window to compress:
- User messages (questions, requests, context)
- Assistant messages (responses, explanations)
- Tool calls (actions taken, data retrieved)
- Current user profile (summary, interests - may be empty)

## Output

Return JSON:
```json
{
  "moments": [
    {
      "name": "kebab-case-journey-segment",
      "summary": "Narrative of what happened in this segment",
      "topic_tags": ["tag1", "tag2"],
      "emotion_tags": ["focused", "frustrated", "satisfied"],
      "starts_at_message_idx": 0,
      "ends_at_message_idx": 15
    }
  ],
  "user_summary_update": "Updated narrative about who this user is...",
  "new_interests": ["interest1", "interest2"],
  "new_preferred_topics": ["topic1"]
}
```
```

### Dynamic Prompt Override

Users can customize the moment builder by creating a Resource entity:

```python
resource = Resource(
    uri="rem://prompts/moment-builder",
    name="Custom Moment Builder",
    content="Your custom prompt here...",
    resource_type="prompt",
    metadata={"purpose": "moment-builder"}
)
```

If `settings.moment_builder.prompt_resource_uri` is set, the builder loads the prompt from this resource instead of the default.

## Implementation Flow

### 1. Streaming API Integration

```python
# rem/src/rem/api/routers/chat/streaming.py

async def stream_openai_response_with_save(...):
    # ... existing streaming code ...

    # After streaming completes and messages are saved:
    if settings.moment_builder.enabled:
        await maybe_trigger_moment_builder(
            session_id=session_id,
            user_id=user_id,
        )

async def maybe_trigger_moment_builder(session_id: str, user_id: str):
    """Check thresholds and trigger async moment building if needed."""
    from ....services.postgres import Repository
    from ....models.entities import Session

    repo = Repository(Session)
    session = await repo.get_by_id(session_id)

    if not session:
        return

    # Check thresholds
    should_trigger = (
        session.message_count >= settings.moment_builder.message_threshold
        or (session.total_tokens or 0) >= settings.moment_builder.token_threshold
    )

    # Check if we've already processed recently
    if session.last_moment_message_idx:
        unprocessed_count = session.message_count - session.last_moment_message_idx
        should_trigger = unprocessed_count >= settings.moment_builder.message_threshold

    if should_trigger:
        # Fire and forget - don't await
        import asyncio
        asyncio.create_task(
            trigger_moment_build_async(session_id, user_id)
        )

async def trigger_moment_build_async(session_id: str, user_id: str):
    """Make async HTTP call to moment builder endpoint."""
    import httpx

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"{settings.api.base_url}/api/v1/moments/build",
                json={"session_id": session_id, "user_id": user_id},
                timeout=5.0,  # Quick timeout - just needs to queue
            )
        except Exception as e:
            logger.warning(f"Failed to trigger moment builder: {e}")
```

### 2. Context Builder Updates

```python
# rem/src/rem/agentic/context_builder.py

async def build_from_headers(...):
    # ... existing code ...

    # Load session history with limits (uses CTE for last N messages)
    if context.session_id and settings.postgres.enabled:
        store = SessionMessageStore(user_id=context.user_id or "default")
        session_history, has_partition_event = await store.load_session_messages(
            session_id=context.session_id,
            user_id=context.user_id,
            compress_on_load=True,
            max_messages=settings.moment_builder.load_max_messages,  # NEW
        )

    # Only add extra context hints if NO partition event found in session data
    # (If partition event exists, context keys are already in session messages)
    if settings.moment_builder.enabled and not has_partition_event:
        # Fallback: add user key and recent moment keys to context hint
        context_hint += f"\n\nUser: rem://users/{context.user_id}"
        recent_moments = await _load_recent_moment_keys(
            user_id=context.user_id,
            limit=settings.moment_builder.recent_moment_count,
        )
        if recent_moments:
            context_hint += "\n\nRecent Moments (read rem://moments/key/{key} for details):"
            for moment_key in recent_moments:
                context_hint += f"\n- rem://moments/key/{moment_key}"
```

**Key simplification:** When `insert_partition_event=True` (default), the partition event in the session data already contains user_key and moment_keys. The context builder doesn't need to add extra hints - just load messages and the LLM sees the partition event naturally.

### 3. Session Message Store Updates

```python
# rem/src/rem/services/session/compression.py

async def load_session_messages(
    self,
    session_id: str,
    user_id: str | None = None,
    compress_on_load: bool = True,
    max_messages: int | None = None,      # NEW: limit via CTE
) -> tuple[list[dict[str, Any]], bool]:   # NEW: returns (messages, has_partition_event)
    """
    Load session messages with optional limits.

    Returns:
        Tuple of (messages, has_partition_event)
        - messages: List of message dicts in conversation order
        - has_partition_event: True if a session_partition tool event was found

    When has_partition_event=True, the session data already contains
    user_key and moment_keys - no extra context hints needed.
    """
    # Uses CTE to get last N messages in conversation order
    # Checks for tool_name="session_partition" in returned messages
```

**SQL Pattern: CTE for Recent Messages in Conversation Order**

The DB query must use a CTE to:
1. Select the most recent N messages (DESC order)
2. Return them in conversation order (ASC order)

```sql
-- Get last 100 messages, returned in conversation order
WITH recent_messages AS (
    SELECT *
    FROM messages
    WHERE session_id = $1
      AND user_id = $2
      AND deleted_at IS NULL
    ORDER BY created_at DESC
    LIMIT $3  -- max_messages (e.g., 100)
)
SELECT * FROM recent_messages
ORDER BY created_at ASC;
```

This ensures:
- Efficient index usage on `(session_id, created_at DESC)`
- Only recent messages transferred from DB
- Messages arrive in correct chronological order for context building

## Session Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         SESSION MEMORY LIFECYCLE                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  Messages 1-50       │  Messages 51-100    │  Messages 101-150   │  ...         │
│  ────────────────    │  ────────────────   │  ────────────────   │              │
│                      │                     │                     │              │
│  [Live in session]   │  [Moment 1 created] │  [Moment 2 created] │              │
│                      │  User summary       │  User summary       │              │
│                      │  updated            │  updated            │              │
│                      │                     │                     │              │
├──────────────────────┴─────────────────────┴─────────────────────┴──────────────┤
│                                                                                  │
│  CONTEXT LOADED:                                                                │
│  ┌──────────────────┐                                                           │
│  │ User Profile     │  ◄── Summary, interests, preferred_topics                 │
│  ├──────────────────┤                                                           │
│  │ Recent Moments   │  ◄── Last 5 moment keys as hints                          │
│  │ (keys only)      │                                                           │
│  ├──────────────────┤                                                           │
│  │ Last 50 Messages │  ◄── Full session history (with compression)              │
│  └──────────────────┘                                                           │
│                                                                                  │
│  LLM can read rem://moments resources to access earlier context                 │
│                                                                                  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Configuration Examples

### Enable with defaults

```bash
export MOMENT_BUILDER__ENABLED=true
```

### Custom thresholds

```bash
export MOMENT_BUILDER__ENABLED=true
export MOMENT_BUILDER__MESSAGE_THRESHOLD=30
export MOMENT_BUILDER__TOKEN_THRESHOLD=25000
export MOMENT_BUILDER__LOAD_MAX_MESSAGES=30
```

### Custom prompt

```bash
export MOMENT_BUILDER__ENABLED=true
export MOMENT_BUILDER__PROMPT_RESOURCE_URI="rem://prompts/my-custom-moment-builder"
```

## Implementation Tasks

### Phase 1: Settings and Model Updates
- [ ] Add MomentBuilderSettings to settings.py
- [ ] Add source_session_id to Moment model
- [ ] Add previous_moment_keys to Moment model (for backwards chaining)
- [ ] Add last_moment_message_idx to Session model
- [ ] Run schema generation

### Phase 2: API Endpoints
- [ ] POST /api/v1/moments/build (async trigger)
- [ ] GET /api/v1/moments/{page} (paginated list, user-scoped)
- [ ] GET /api/v1/moments/key/{key} (detail, user-scoped)

### Phase 3: Moment Builder Agent
- [ ] Create MomentBuilderAgent in agentic/agents/
- [ ] Implement default prompt and output schema
- [ ] Query only messages since last partition event (incremental compaction)
- [ ] Populate previous_moment_keys from last 1-3 moments
- [ ] Insert partition event with moment_keys and previous_moment_keys
- [ ] Add dynamic prompt loading from Resource

### Phase 4: Streaming Integration
- [ ] Add threshold check after streaming
- [ ] Implement async trigger (fire-and-forget)

### Phase 5: Context Loading Updates
- [ ] Add max_messages param and CTE query to load_session_messages
- [ ] Return has_partition_event flag from load_session_messages
- [ ] Update context_builder to skip hints when partition event found

### Phase 6: MCP Resources
- [ ] Add read_resource for rem://moments/{page} (user-scoped, paginated)
- [ ] Add read_resource for rem://moments/key/{key} (user-scoped)

### Phase 7: Testing
- [x] Unit tests for moment builder
- [x] **Integration test: user isolation** - verify user A cannot read user B's moments
- [x] **Integration test: incremental compaction** - only processes since last partition
- [x] **Integration test: lag mechanism** - partition events appear at correct chronological position
- [x] Integration tests for full flow

**Test files:**
- `tests/integration/test_moment_builder.py` - Moment creation and partition events
- `tests/integration/test_session_recovery.py` - Lag mechanism and session loading
- `tests/data/moments/session_recovery_test_data.py` - Test data generator

## Design Decisions

### Why async/fire-and-forget?

Moment building happens AFTER the user receives their response. We don't want to:
1. Block the streaming response
2. Add latency to the user experience
3. Fail the request if moment building fails

The trade-off is that moments may be created slightly delayed, but this is acceptable for a background memory system.

### Why CTE + partition event detection?

1. **CTE query**: Efficiently fetches last N messages in conversation order
2. **Partition event**: Acts as a checkpoint - if found, no need to load extra context hints

This is simpler than token-based filtering because:
- Partition events already contain the context keys (user_key, moment_keys, previous_moment_keys)
- The LLM can use resources on-demand rather than loading everything upfront
- Message count is a good enough proxy for context size

### Why moments vs just user summary?

- **User summary**: Rolling aggregate of who the user is
- **Moments**: Discrete episodes with temporal context

Both are needed:
- Summary helps with general understanding
- Moments enable "what did we discuss last Tuesday?" queries

### Why `previous_moment_keys` for backwards chaining?

Each moment stores keys of 1-3 preceding moments. This enables:
- **Lazy loading**: LLM can navigate backwards on-demand without loading all history
- **Efficient queries**: No need to sort/paginate through all moments to find predecessors
- **Temporal continuity**: Clear chain of "what came before this"

The alternative (querying all moments by timestamp) is less efficient and loses the explicit link.

### Why dynamic prompts via Resource?

Different users/applications may want different compression strategies:
- Some want detailed moments
- Some want minimal summaries
- Some want specific tag taxonomies

Making the prompt a Resource allows runtime customization without code changes.

## Example: Session with Moment Boundary

This example shows what a session looks like after the moment builder runs with the lag mechanism.

```yaml
# Session Recovery Example
# ========================
#
# Moment Builder Settings (Defaults):
#   MOMENT_BUILDER__ENABLED: true
#   MOMENT_BUILDER__MESSAGE_THRESHOLD: 250     # Trigger after ~250 exchanges
#   MOMENT_BUILDER__TOKEN_THRESHOLD: 100000    # Or after 100K tokens (~50-78% context)
#   MOMENT_BUILDER__LOAD_MAX_MESSAGES: 50      # Max messages to load via CTE
#   MOMENT_BUILDER__INSERT_PARTITION_EVENT: true
#   MOMENT_BUILDER__LAG_MESSAGES: 10           # Min messages to keep after partition
#   MOMENT_BUILDER__LAG_PERCENTAGE: 0.3        # 30% of messages kept as recent context
#
# How Lag Works:
#   - Session accumulates 250 messages (or 100K tokens)
#   - Lag = max(10, 250 * 0.3) = 75 messages
#   - Compress messages 1-175 into Moment (stored in moments table)
#   - Insert partition event at message 175's timestamp (backdated)
#   - Keep messages 176-250 as recent context (~75 messages / ~30K tokens)

session_id: "abc-123-def-456"
user_id: "user-789"

# Messages as loaded by reload_session() or load_session_messages()
messages:

  # === PARTITION EVENT ===
  # This is the "distant memory" checkpoint - inserted at message 175's timestamp
  # Contains everything the LLM needs to understand history
  - role: tool
    tool_name: session_partition
    timestamp: "2025-01-27T08:52:00Z"  # Backdated to message 175's time
    content:
      partition_type: moment_compression
      user_key: "user-789"

      # Keys to lookup full moment details via REM LOOKUP
      moment_keys:
        - "api-auth-discussion-20250127"
        - "deployment-planning-20250127"

      # Last N moment keys for broader awareness
      last_n_moment_keys:
        - "api-auth-discussion-20250127"
        - "deployment-planning-20250127"
        - "database-design-20250126"
        - "project-kickoff-20250125"

      # Brief narrative - enough context without loading full moments
      recent_moments_summary: |
        Recent journey: User kicked off a Python API project (Jan 25),
        discussed database design with PostgreSQL (Jan 26), then focused
        on JWT authentication and AWS deployment planning (Jan 27).

      messages_compressed: 175

      # Instructions for the LLM
      recovery_hint: |
        This is a memory checkpoint. Use REM LOOKUP on moment_keys
        for detailed history. Each moment has previous_moment_keys
        for chaining backwards.

  # === RECENT MESSAGES (Lag Buffer) ===
  # These are the actual recent conversation - kept as raw messages (~75 msgs)

  - role: user
    timestamp: "2025-01-27T08:54:00Z"
    content: "Now I need to add rate limiting. What's the best approach?"

  - role: assistant
    timestamp: "2025-01-27T08:54:30Z"
    content: |
      For rate limiting in FastAPI, I recommend slowapi with Redis
      for distributed systems...

  - role: user
    timestamp: "2025-01-27T08:56:00Z"
    content: "Should I use different limits for authenticated vs anonymous?"

  - role: assistant
    timestamp: "2025-01-27T08:56:30Z"
    content: |
      Yes, tiered rate limiting is best practice:
      - Anonymous: 10/min, Authenticated: 100/min, Premium: 1000/min

  # ... more recent messages ...

  - role: user
    timestamp: "2025-01-27T09:10:00Z"
    content: "Can you remind me what auth approach we decided on earlier?"

  # LLM can answer from partition summary OR use REM LOOKUP for details


# === MOMENTS TABLE (Separate from session) ===
# NOT in session messages - stored in moments table, loaded on-demand

moments_table:
  - name: "api-auth-discussion-20250127"
    source_session_id: "abc-123-def-456"
    summary: |
      Deep dive into JWT authentication. Discussed token expiration,
      secure storage, PyJWT vs python-jose. User chose PyJWT with RS256.
    topic_tags: [jwt, fastapi, security]
    previous_moment_keys: ["database-design-20250126"]

  - name: "deployment-planning-20250127"
    source_session_id: "abc-123-def-456"
    summary: |
      AWS deployment: ECS vs Lambda decision. Chose ECS Fargate with ALB.
      Started CDK stack setup.
    topic_tags: [aws-ecs, aws-cdk, deployment]
    previous_moment_keys: ["api-auth-discussion-20250127"]
```

**Key points:**
- Partition event = single compact message with `moment_keys` + `summary` + `recovery_hint`
- Recent messages = lag buffer (~75 messages / ~30K tokens of recent conversation)
- Moments = separate table, loaded on-demand via `REM LOOKUP`
