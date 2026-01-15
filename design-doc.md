# REM Design Document

**Resources, Entities, Moments** — A bio-inspired memory system for agentic AI.

---

## Table of Contents

1. [Theory & Philosophy](#1-theory--philosophy)
2. [System Architecture](#2-system-architecture)
3. [Agent Framework](#3-agent-framework)
4. [MCP Tool Layer](#4-mcp-tool-layer)
5. [Streaming Architecture](#5-streaming-architecture)
6. [Session Memory](#6-session-memory)
7. [REM Query Dialect](#7-rem-query-dialect)
8. [Ontology System](#8-ontology-system)
9. [Multi-Agent Orchestration](#9-multi-agent-orchestration)
10. [Evaluation Framework](#10-evaluation-framework)
11. [API Headers & Context](#11-api-headers--context)

---

## 1. Theory & Philosophy

### 1.1 Bio-Inspired Memory Model

REM draws inspiration from biological memory systems:

| Biological Concept | REM Implementation |
|-------------------|-------------------|
| **Episodic Memory** | Session history — user/assistant exchanges stored chronologically |
| **Semantic Memory** | Ontology system — structured knowledge indexed for retrieval |
| **Working Memory** | Agent scratchpad — transient state during query execution |
| **Consolidation** | Dreaming workers — background processes that enrich entities with embeddings and graph edges |

### 1.2 Core Design Principles

1. **Natural Language Keys**: Entity references use human-readable labels (`sarah-chen`), not UUIDs
2. **Agent Responsibility**: Agents must "take notes" via `register_metadata` — tool responses are not stored (often verbose RAG results)
3. **Schema-as-Code**: Agents defined via YAML (JSON Schema), not Python classes
4. **MCP Unification**: Both tools and resources exposed as callable functions
5. **Shared Memory**: Agents in the same session share memory; specialization via schema, not isolation

### 1.3 Information Flow

```
┌──────────────────────────────────────────────────────────────────┐
│                        User Query                                 │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Execution                              │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐           │
│  │   Schema    │   │   Memory    │   │    Tools    │           │
│  │   (YAML)    │   │  (Session)  │   │    (MCP)    │           │
│  └─────────────┘   └─────────────┘   └─────────────┘           │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    REM Query Layer                               │
│  LOOKUP ──► FUZZY ──► SEARCH ──► TRAVERSE ──► SQL              │
│    O(1)      O(n)     O(log n)     O(k)       O(n)             │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL + pgvector                         │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │ KV_STORE  │  │  Tables   │  │Embeddings │  │  Edges    │   │
│  │  (cache)  │  │ (source)  │  │ (vectors) │  │  (graph)  │   │
│  └───────────┘  └───────────┘  └───────────┘  └───────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. System Architecture

### 2.1 Component Overview

```
remstack/
├── rem/                          # Python package (PyPI: remdb)
│   ├── src/rem/
│   │   ├── api/                  # FastAPI + MCP server
│   │   │   ├── mcp_router/       # MCP tools, resources, prompts
│   │   │   └── routers/chat/     # Streaming, completions
│   │   ├── agentic/              # Agent framework
│   │   │   ├── providers/        # Pydantic AI wrapper
│   │   │   ├── mcp/              # Tool wrapping
│   │   │   └── agents/           # Built-in agents
│   │   ├── services/             # Business logic
│   │   │   ├── rem/              # Query execution
│   │   │   ├── session/          # Memory management
│   │   │   ├── postgres/         # Database layer
│   │   │   └── phoenix/          # Evaluation
│   │   └── models/               # Pydantic models
│   └── schemas/                  # YAML agent definitions
└── manifests/                    # Kubernetes deployment
```

### 2.2 Request Flow

```
HTTP Request
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI Application                                         │
│  POST /api/v1/chat/completions                              │
│                                                              │
│  Headers:                                                    │
│  ├── X-User-Id        → user_id (data scoping)              │
│  ├── X-Session-Id     → session_id (memory continuity)      │
│  ├── X-Agent-Schema   → agent_schema_uri (agent selection)  │
│  └── X-Client-Id      → client_id (web/mobile/cli)          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Context Builder                                             │
│  ├── Load session history from Postgres                     │
│  ├── Convert to Pydantic-AI message format                  │
│  └── Optionally inject user profile                         │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent Execution                                             │
│  ├── Load schema from YAML or database                      │
│  ├── Create Pydantic-AI agent with MCP tools                │
│  ├── Execute with streaming                                 │
│  └── Store messages + tool calls to session                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  SSE Response Stream                                         │
│  ├── OpenAI-compatible content chunks                       │
│  ├── Named events (reasoning, progress, tool_call)          │
│  └── Metadata events from register_metadata                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Agent Framework

### 3.1 YAML Protocol

Agents are defined as JSON Schema documents in YAML format:

```yaml
type: object
description: |
  You are a REM Query Agent that answers questions
  using the REM database...

properties:
  answer:
    type: string
    description: Clear, concise answer
  confidence:
    type: number
    minimum: 0
    maximum: 1
  sources:
    type: array
    items:
      type: string

required:
  - answer
  - confidence
  - sources

json_schema_extra:
  kind: agent
  name: query-agent
  version: "1.0.0"
  tools:
    - name: search_rem
      mcp_server: rem
  resources:
    - uri_pattern: rem://.*
```

### 3.2 Schema Components

| Field | Purpose |
|-------|---------|
| `description` | System prompt (agent instructions) |
| `properties` | Structured output schema |
| `required` | Required output fields |
| `json_schema_extra.kind` | `agent` or `evaluator` |
| `json_schema_extra.name` | Kebab-case identifier |
| `json_schema_extra.tools` | MCP tool references |
| `json_schema_extra.resources` | MCP resource patterns |

### 3.3 Agent Creation Flow

```
1. Load Schema
   └── schema = load_agent_schema("query-agent")

2. Extract Components
   ├── system_prompt = schema.description
   ├── metadata = schema.json_schema_extra
   └── output_schema = schema.properties

3. Create Pydantic Model
   └── OutputModel = json_schema_to_pydantic(output_schema)

4. Load MCP Tools
   ├── mcp_server = import_module("rem.mcp_server")
   ├── tools = await mcp_server.get_tools()
   └── wrapped_tools = [wrap_tool(t) for t in tools]

5. Create Agent
   └── agent = Agent(
           model="anthropic:claude-sonnet-4-5-20250929",
           system_prompt=system_prompt,
           output_type=OutputModel,
           tools=wrapped_tools
       )
```

**Key Files:**
- Schema protocol: `rem/src/rem/agentic/schema.py`
- Agent factory: `rem/src/rem/agentic/providers/pydantic_ai.py`
- Context management: `rem/src/rem/agentic/context.py`

---

## 4. MCP Tool Layer

### 4.1 Tool Abstraction

REM unifies tools and resources as callable functions via MCP (Model Context Protocol):

```
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Server                                  │
│                                                                  │
│  Tools (actions)              Resources (data)                  │
│  ├── search_rem()             ├── rem://agents                  │
│  ├── register_metadata()      ├── rem://schema/entities         │
│  ├── ask_agent()              └── user://profile/{user_id}      │
│  ├── ingest_into_rem()                                          │
│  └── save_agent()                    ▼                          │
│           │                   Wrapped as tools                   │
│           │                   via read_resource()                │
│           └──────────────────────────┐                          │
│                                      ▼                          │
│                        Pydantic-AI Tool Functions               │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Core Tools

| Tool | Purpose | When to Use |
|------|---------|-------------|
| `search_rem` | Execute REM queries | Retrieve entities from memory |
| `register_metadata` | Emit structured metadata | Confidence, sources, flags |
| `ask_agent` | Invoke child agent | Multi-agent delegation |
| `ingest_into_rem` | Process files | S3/local file ingestion |
| `read_resource` | Access MCP resources | Load schemas, user profiles |
| `save_agent` | Persist agent schema | User-created agents |

### 4.3 The register_metadata Pattern

Since tool responses are NOT stored in session memory (they're often verbose RAG results), agents must explicitly "take notes":

```python
# Agent calls register_metadata to persist important findings
register_metadata(
    confidence=0.95,
    references=["sarah-chen", "q3-report"],
    sources=["REM database"],
    risk_level="green",
    extra={"topics": ["quarterly-review"]}
)
```

This emits a metadata SSE event AND provides structured data for session tracing.

**Key Files:**
- MCP server: `rem/src/rem/api/mcp_router/server.py`
- Tool implementations: `rem/src/rem/api/mcp_router/tools.py`
- Resource definitions: `rem/src/rem/api/mcp_router/resources.py`

---

## 5. Streaming Architecture

### 5.1 OpenAI-Compatible Events

REM streams responses using a hybrid format:

```
Text Content (OpenAI format):
  data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"Hello"}}]}

Named Events (REM extensions):
  event: reasoning
  data: {"type":"reasoning","content":"Analyzing...","step":1}

  event: tool_call
  data: {"type":"tool_call","tool_name":"search_rem","status":"started"}

  event: metadata
  data: {"type":"metadata","confidence":0.95,"sources":[...]}

  event: done
  data: {"type":"done","reason":"stop"}
```

### 5.2 Event Types

| Event Type | Format | Purpose |
|------------|--------|---------|
| text_delta | `data:` (OpenAI) | Streaming content |
| reasoning | `event:` (named) | Model thinking |
| progress | `event:` (named) | Step indicators |
| tool_call | `event:` (named) | Tool invocation |
| metadata | `event:` (named) | Structured metadata |
| done | `event:` (named) | Stream complete |

### 5.3 Multi-Agent Multiplexing

When a parent agent calls `ask_agent`, child events are multiplexed into the parent stream:

```
Parent Agent
     │
     ├─ agent.iter()
     │    │
     │    ├─ Model Request Node
     │    │    └─ Text deltas, tool calls
     │    │
     │    └─ Call Tools Node (ask_agent)
     │         │
     │         ▼
     │    ┌─────────────────────────────────────┐
     │    │ stream_with_child_events()          │
     │    │                                     │
     │    │  asyncio.wait(FIRST_COMPLETED)     │
     │    │  ├─ tool_stream.__anext__()        │
     │    │  └─ child_event_sink.get()         │
     │    │                                     │
     │    │  Yields: ("tool", event)           │
     │    │      or: ("child", event)          │
     │    └─────────────────────────────────────┘
     │
     ▼
SSE Response (interleaved parent + child events)
```

**Key Files:**
- Main streaming: `rem/src/rem/api/routers/chat/streaming.py`
- Child multiplexing: `rem/src/rem/api/routers/chat/child_streaming.py`
- Event utilities: `rem/src/rem/api/routers/chat/streaming_utils.py`

---

## 6. Session Memory

### 6.1 Memory Philosophy

**What IS stored:**
- User messages (complete)
- Assistant messages (complete)
- Tool calls (name, arguments, call_id)

**What is NOT stored:**
- Tool responses (often verbose RAG results)

This design puts the burden on agents to "take notes" via `register_metadata`. The rationale:
1. Tool responses are often 10-100x larger than useful information
2. Agents should extract and summarize relevant findings
3. Memory compression becomes agent-driven, not arbitrary truncation

### 6.2 Session Message Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Chat Request                                                    │
│  X-Session-Id: sess-123                                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  SessionMessageStore.load_session_messages()                     │
│  ├── SELECT * FROM messages WHERE session_id = $1               │
│  ├── Compress long assistant messages (>400 chars)              │
│  │   └── Truncate + add "[REM LOOKUP entity-key]" hint          │
│  └── Preserve all tool metadata                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  session_to_pydantic_messages()                                  │
│  ├── Convert storage format → Pydantic-AI format                │
│  ├── Synthesize ToolCallPart from metadata                      │
│  └── Prepend system prompt                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Agent Execution                                                 │
│  agent.run(prompt, message_history=pydantic_messages)           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  SessionMessageStore.store_session_messages()                    │
│  ├── Store all messages UNCOMPRESSED (audit trail)              │
│  └── Metadata: tool_call_id, tool_name, tool_arguments          │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 Message Model

| Field | Type | Purpose |
|-------|------|---------|
| `content` | TEXT | Message text |
| `message_type` | VARCHAR | 'user', 'assistant', 'system', 'tool' |
| `session_id` | VARCHAR | Groups messages by conversation |
| `user_id` | VARCHAR | Owner/scoping |
| `metadata` | JSONB | tool_call_id, tool_name, tool_arguments |

**Key Files:**
- Message model: `rem/src/rem/models/entities/message.py`
- Session store: `rem/src/rem/services/session/compression.py`
- Format conversion: `rem/src/rem/services/session/pydantic_messages.py`

---

## 7. REM Query Dialect

### 7.1 Query Types & Performance Contracts

| Query | Complexity | Syntax | Use Case |
|-------|------------|--------|----------|
| **LOOKUP** | O(1) | `LOOKUP "entity-key"` | Know exact entity name |
| **FUZZY** | O(n) indexed | `FUZZY "text" THRESHOLD 0.5` | Typos, partial matches |
| **SEARCH** | O(log n) | `SEARCH "semantic query" FROM table` | Conceptual similarity |
| **TRAVERSE** | O(k) | `TRAVERSE TYPE "rel" FROM "entity" DEPTH 2` | Graph relationships |
| **SQL** | O(n) | `SELECT * FROM table WHERE ...` | Direct SQL access |

### 7.2 Query Execution Flow

```
Query String: SEARCH "API documentation" FROM ontologies LIMIT 10
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│  RemQueryParser.parse()                                          │
│  ├── Tokenize with shlex (handle quoted strings)                │
│  ├── Identify query type: SEARCH                                │
│  └── Extract parameters: query_text, table_name, limit          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  RemService.execute_query_string()                               │
│  ├── Validate parameters → RemQuery model                       │
│  └── Dispatch to _execute_search()                              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  _execute_search()                                               │
│  ├── Generate embedding: generate_embedding_async(query_text)   │
│  └── Call PostgreSQL function: rem_search()                     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  PostgreSQL rem_search()                                         │
│  ├── Vector similarity: 1 - (embedding <=> query_embedding)     │
│  ├── Filter by min_similarity (default 0.3)                     │
│  └── Return top K with similarity_score                         │
└─────────────────────────────────────────────────────────────────┘
```

### 7.3 Graph Edges

Entities link via `graph_edges` JSONB array:

```json
{
  "dst": "sarah-chen",
  "rel_type": "authored_by",
  "weight": 0.8,
  "properties": {
    "dst_entity_type": "users",
    "created_at": "2025-01-10T..."
  }
}
```

Key design: **Human-readable labels, not UUIDs.** This enables conversational queries:

```
TRAVERSE FROM "quarterly-report" TYPE "authored_by" DEPTH 1
```

### 7.4 KV_STORE Cache

All entities cached in an UNLOGGED table for O(1) lookup:

| Column | Purpose |
|--------|---------|
| `entity_key` | Normalized name (kebab-case) |
| `entity_type` | Source table |
| `entity_id` | UUID reference |
| `content_summary` | For fuzzy search |
| `graph_edges` | Cached edges |

Rebuilt automatically via triggers on entity table changes.

**Key Files:**
- Query models: `rem/src/rem/models/core/rem_query.py`
- Parser: `rem/src/rem/services/rem/parser.py`
- Service: `rem/src/rem/services/rem/service.py`
- PostgreSQL functions: `rem/src/rem/sql/migrations/001_install.sql`

---

## 8. Ontology System

### 8.1 WIKI-Like Knowledge Structure

The ontology system provides structured, searchable knowledge:

```
┌─────────────────────────────────────────────────────────────────┐
│  Resources (base content)                                        │
│  ├── Documents, conversations, artifacts                        │
│  └── Raw ingested content                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Dreaming (extraction)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Ontologies (structured knowledge)                               │
│  ├── Agent-extracted: CVs, contracts, clinical notes            │
│  ├── Direct-loaded: API docs, wikis, knowledge bases            │
│  └── Embedded for semantic search                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ Graph edges
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Knowledge Graph                                                 │
│  ├── Entities linked by relationship types                      │
│  ├── Human-readable edge labels                                 │
│  └── Weighted relationships (1.0=primary, 0.5=secondary)        │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 Ontology Entity

| Field | Purpose |
|-------|---------|
| `name` | Entity key (kebab-case) |
| `uri` | Source reference (git://, s3://) |
| `content` | Text for embedding |
| `extracted_data` | Structured fields (JSONB) |
| `graph_edges` | Relationships |
| `tags` | Classification labels |

### 8.3 Combined Search Pattern

Agents can combine search modes:

```
1. LOOKUP "sarah-chen"           → Exact entity (O(1))
2. FUZZY "sara" THRESHOLD 0.7    → Handle typos
3. SEARCH "machine learning"     → Semantic similarity
   FROM ontologies
4. TRAVERSE FROM "sarah-chen"    → Find related entities
   TYPE "authored_by"
```

**Key Files:**
- Ontology model: `rem/src/rem/models/entities/ontology.py`
- Config model: `rem/src/rem/models/entities/ontology_config.py`
- Embeddings: `rem/src/rem/services/embeddings/`

---

## 9. Multi-Agent Orchestration

### 9.1 Context Inheritance

When a parent agent calls `ask_agent`, the child inherits context:

```
Parent Agent (context: user_id=U1, session_id=S1, tenant_id=T1)
     │
     │ ask_agent("sentiment-analyzer", input_text="...")
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Context Inheritance                                             │
│                                                                  │
│  parent_context = get_current_context()                         │
│  child_context = parent_context.child_context(                  │
│      agent_schema_uri="sentiment-analyzer"                      │
│  )                                                               │
│                                                                  │
│  # Inherits: user_id, tenant_id, session_id, is_eval           │
│  # Overrides: agent_schema_uri                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
Child Agent (context: user_id=U1, session_id=S1, schema=sentiment)
```

### 9.2 Memory Sharing

All agents in the same session share memory:

```python
# Parent calls ask_agent
ask_agent("specialist", input_text="Analyze X")

# Inside ask_agent:
# 1. Load session history (same session_id)
raw_history = await store.load_session_messages(session_id, user_id)

# 2. Convert to pydantic-ai format
messages = session_to_pydantic_messages(raw_history, system_prompt)

# 3. Child sees FULL conversation history
result = await child_agent.run(prompt, message_history=messages)
```

### 9.3 Routing Patterns

**Orchestrator Design:**

```
User Query
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Orchestrator Agent                                              │
│                                                                  │
│  1. Load user profile (via read_resource)                       │
│  2. Analyze query intent                                        │
│  3. Route to specialist:                                        │
│     ├── ask_agent("sentiment") if emotional content             │
│     ├── ask_agent("search") if information retrieval            │
│     └── ask_agent("action") if task execution                   │
│  4. Synthesize response                                         │
└─────────────────────────────────────────────────────────────────┘
```

**User Profile Loading:**

```python
# Agent can load user context via MCP resource
profile = read_resource("user://profile/user-123")

# Returns:
# - Email and name
# - AI-generated summary
# - Interests and preferences
# - Activity level
```

### 9.4 Event Proxying

Child agent events streamed through parent's event sink:

| Child Event | Parent Handling |
|-------------|-----------------|
| `child_tool_start` | Emit tool_call event |
| `child_content` | Stream as content + set flag |
| `child_tool_result` | Emit progress event |

The `child_content_streamed` flag prevents duplication when parent echoes child output.

**Key Files:**
- ask_agent tool: `rem/src/rem/api/mcp_router/tools.py:1208-1527`
- Context management: `rem/src/rem/agentic/context.py`
- Child streaming: `rem/src/rem/api/routers/chat/child_streaming.py`

---

## 10. Evaluation Framework

### 10.1 Evaluators as YAML Agents

Evaluators follow the same schema pattern with `kind: evaluator`:

```yaml
type: object
description: |
  You are THE JUDGE evaluating REM LOOKUP responses.

  Scoring Rubric:
  - Correctness (0-1): Accuracy of returned data
  - Completeness (0-1): All properties present?
  - Performance (0-1): O(1) contract satisfied?

properties:
  correctness_score:
    type: number
    minimum: 0
    maximum: 1
  completeness_score:
    type: number
  pass:
    type: boolean

required:
  - correctness_score
  - pass

json_schema_extra:
  kind: evaluator
  name: rem-lookup-correctness
```

### 10.2 Two-Phase Evaluation

```
Phase 1: SME Golden Set Creation
┌─────────────────────────────────────────────────────────────────┐
│  SMEs create (input, reference) pairs                           │
│  └── No agent execution                                         │
└─────────────────────────────────────────────────────────────────┘

Phase 2a: Run Agents (produce outputs)
┌─────────────────────────────────────────────────────────────────┐
│  For each (input, reference) in golden set:                     │
│  └── output = await agent.run(input)                            │
└─────────────────────────────────────────────────────────────────┘

Phase 2b: Run Evaluators (produce scores)
┌─────────────────────────────────────────────────────────────────┐
│  For each (input, output, reference):                           │
│  └── scores = await evaluator(input, output, reference)         │
└─────────────────────────────────────────────────────────────────┘
```

### 10.3 Phoenix Integration

REM integrates with Arize Phoenix for evaluation orchestration:

| Component | Purpose |
|-----------|---------|
| `PhoenixClient` | Dataset management, experiment execution |
| `create_evaluator_from_schema` | Convert YAML → Phoenix evaluator |
| `run_evaluation_experiment` | End-to-end workflow |

**Key Files:**
- Evaluator schemas: `rem/src/rem/schemas/evaluators/`
- Phoenix provider: `rem/src/rem/agentic/providers/phoenix.py`
- Phoenix client: `rem/src/rem/services/phoenix/client.py`

---

## 11. API Headers & Context

### 11.1 Request Headers

| Header | Field | Purpose |
|--------|-------|---------|
| `X-User-Id` | `user_id` | Data scoping (UUID5 of email) |
| `X-Session-Id` | `session_id` | Conversation continuity |
| `X-Tenant-Id` | `tenant_id` | Workspace isolation |
| `X-Agent-Schema` | `agent_schema_uri` | Agent selection |
| `X-Model-Name` | `default_model` | LLM override |
| `X-Is-Eval` | `is_eval` | Evaluation session flag |
| `X-Client-Id` | `client_id` | Client identifier |

### 11.2 Data Scoping

All queries automatically scoped by `user_id`:

```sql
-- Every PostgreSQL function includes:
WHERE (user_id = effective_user_id OR user_id IS NULL)

-- User's private data + public/shared data
```

### 11.3 Context Propagation

```python
class AgentContext(BaseModel):
    user_id: str | None          # Data scoping
    tenant_id: str               # Workspace isolation
    session_id: str | None       # Memory continuity
    default_model: str           # LLM selection
    agent_schema_uri: str | None # Agent identity
    is_eval: bool = False        # Evaluation mode
    client_id: str | None        # Client tracking

# Available globally via ContextVar
context = get_current_context()

# Create child context for nested agents
child = context.child_context(agent_schema_uri="child-agent")
```

**Key Files:**
- Context model: `rem/src/rem/agentic/context.py`
- Context builder: `rem/src/rem/agentic/context_builder.py`
- API main: `rem/src/rem/api/main.py`

---

## Summary

REM provides a bio-inspired memory system for agentic AI with:

1. **YAML-defined agents** wrapping Pydantic AI with structured outputs
2. **MCP tool layer** unifying tools and resources as functions
3. **OpenAI-compatible streaming** with named events and multi-agent multiplexing
4. **Session memory** storing user/assistant messages and tool calls (not responses)
5. **REM query dialect** with guaranteed performance contracts
6. **Ontology system** combining semantic and entity lookup
7. **Multi-agent orchestration** via `ask_agent` with shared memory
8. **Evaluation framework** using YAML-defined LLM-as-a-Judge evaluators

The key insight: agents must "take notes" because memory is valuable. Tool responses are not stored — agents extract what matters via `register_metadata`.
