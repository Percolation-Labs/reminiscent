# Chat Completions API

OpenAI-compatible chat completions endpoint with REM-specific session management and user context.

## Endpoints

### POST /v1/chat/completions

OpenAI-compatible chat completions with streaming support.

**Features:**
- Streaming and non-streaming modes
- Session history with compression
- User profile integration via dreaming worker
- Multiple agent schemas
- Model override support

## Headers

See [Content Headers Documentation](../../docs/content_headers.md) for complete header reference.

**Key Headers:**
- `X-User-Id`: User identifier (email, UUID, or username)
- `X-Tenant-Id`: Tenant identifier for multi-tenancy (optional, defaults to user_id)
- `X-Session-Id`: Session identifier for conversation continuity
- `X-Agent-Schema`: Agent schema to use (default: `rem`)
- `X-Model-Name`: Override LLM model (optional)

## Session Management

REM is designed for multi-turn conversations where each request contains a single message.

### How Sessions Work

1. **First Message**: Client sends message without `X-Session-Id`
   - Server processes message
   - Returns response
   - Client generates session ID for subsequent messages

2. **Subsequent Messages**: Client sends message with `X-Session-Id`
   - Server loads compressed session history from database
   - Combines history with new message
   - Agent receives full conversation context
   - New messages saved to database with compression

3. **Compression**: Long assistant responses are compressed
   - Short messages (<400 chars): Stored and loaded as-is
   - Long messages (>400 chars): Compressed with REM LOOKUP hints
   - Example: `"Start of response... [Message truncated - REM LOOKUP session-123-msg-1 to recover full content] ...end of response"`
   - Agent can retrieve full content on-demand using REM LOOKUP

### Benefits of Compression
- Prevents context window bloat
- Maintains conversation continuity
- Agent decides what to retrieve
- More efficient for long conversations

## User Profiles and Dreaming

The dreaming worker runs periodically to build user models:

1. Analyzes user's resources, sessions, and moments
2. Generates profile with current projects, expertise, interests
3. Stores profile in User entity

### User Profile in Chat

**On-Demand (Default):**
- Agent receives hint: `"User ID: sarah@example.com. To load user profile: Use REM LOOKUP users/sarah@example.com"`
- Agent decides whether to load based on query
- More efficient for queries that don't need personalization

**Auto-Inject (Optional):**
- Set environment variable: `CHAT__AUTO_INJECT_USER_CONTEXT=true`
- User profile automatically loaded and injected into system message
- Simpler for basic chatbots that always need context

## Agent Schemas

Specify different agent behaviors using `X-Agent-Schema` header.

**Available Schemas:**
- `rem` (default): REM expert assistant
- `query-agent`: REM query specialist
- `contract-extractor`: Extract structured data from contracts
- Custom schemas: Place YAML files in `schemas/agents/`

## Request Examples

### cURL: Simple Chat

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
      {"role": "user", "content": "What is REM?"}
    ]
  }'
```

### cURL: Streaming Chat

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
      {"role": "user", "content": "Explain REM architecture"}
    ],
    "stream": true
  }'
```

### cURL: Multi-Turn Conversation

```bash
# First message
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -H "X-Session-Id: session-abc123" \
  -d '{
    "model": "openai:gpt-4o",
    "messages": [
      {"role": "user", "content": "What are moments in REM?"}
    ]
  }'

# Second message (session history loaded automatically)
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -H "X-Session-Id: session-abc123" \
  -d '{
    "model": "openai:gpt-4o",
    "messages": [
      {"role": "user", "content": "How are they created?"}
    ]
  }'
```

### cURL: Custom Agent Schema

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -H "X-Agent-Schema: query-agent" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
      {"role": "user", "content": "LOOKUP users/sarah@example.com"}
    ]
  }'
```

### cURL: Model Override

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -H "X-Model-Name: openai:gpt-4o-mini" \
  -d '{
    "model": "will-be-overridden",
    "messages": [
      {"role": "user", "content": "Quick question about REM"}
    ]
  }'
```

### cURL: Tenant Scoping

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-User-Id: sarah@example.com" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Session-Id: session-def456" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
      {"role": "user", "content": "Show me our team resources"}
    ]
  }'
```

## Python Examples

### Python: Simple Chat

```python
import requests

url = "http://localhost:8000/api/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "X-User-Id": "sarah@example.com"
}
data = {
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
        {"role": "user", "content": "What is REM?"}
    ]
}

response = requests.post(url, headers=headers, json=data)
print(response.json()["choices"][0]["message"]["content"])
```

### Python: Streaming Chat

```python
import requests
import json

url = "http://localhost:8000/api/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "X-User-Id": "sarah@example.com"
}
data = {
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
        {"role": "user", "content": "Explain REM architecture"}
    ],
    "stream": True
}

response = requests.post(url, headers=headers, json=data, stream=True)

for line in response.iter_lines():
    if line:
        line_str = line.decode('utf-8')
        if line_str.startswith('data: '):
            data_str = line_str[6:]  # Remove 'data: ' prefix
            if data_str != '[DONE]':
                chunk = json.loads(data_str)
                delta = chunk["choices"][0]["delta"]
                if "content" in delta:
                    print(delta["content"], end="", flush=True)
```

### Python: Multi-Turn Conversation

```python
import requests
import uuid

url = "http://localhost:8000/api/v1/chat/completions"
session_id = f"session-{uuid.uuid4()}"

def send_message(content):
    headers = {
        "Content-Type": "application/json",
        "X-User-Id": "sarah@example.com",
        "X-Session-Id": session_id
    }
    data = {
        "model": "openai:gpt-4o",
        "messages": [
            {"role": "user", "content": content}
        ]
    }

    response = requests.post(url, headers=headers, json=data)
    return response.json()["choices"][0]["message"]["content"]

# First turn
response1 = send_message("What are moments in REM?")
print(f"Assistant: {response1}\n")

# Second turn (session history loaded automatically)
response2 = send_message("How are they created?")
print(f"Assistant: {response2}\n")

# Third turn
response3 = send_message("Can you give an example?")
print(f"Assistant: {response3}\n")
```

### Python: With User Profile Auto-Inject

```python
import requests
import os

# Enable auto-inject via environment variable
os.environ["CHAT__AUTO_INJECT_USER_CONTEXT"] = "true"

url = "http://localhost:8000/api/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "X-User-Id": "sarah@example.com"
}
data = {
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
        {"role": "user", "content": "What should I focus on next?"}
    ]
}

# User profile automatically loaded and injected
# Agent receives context about sarah@example.com's current projects, interests, etc.
response = requests.post(url, headers=headers, json=data)
print(response.json()["choices"][0]["message"]["content"])
```

## Response Format

### Non-Streaming Response

```json
{
  "id": "chatcmpl-abc123def456",
  "created": 1732292400,
  "model": "anthropic:claude-sonnet-4-5-20250929",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "REM (Resources Entities Moments) is a bio-inspired memory architecture..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 200,
    "total_tokens": 350
  }
}
```

### Streaming Response (SSE Format)

```
data: {"id":"chatcmpl-abc123","choices":[{"delta":{"role":"assistant","content":""},"index":0}]}

data: {"id":"chatcmpl-abc123","choices":[{"delta":{"content":"REM"},"index":0}]}

data: {"id":"chatcmpl-abc123","choices":[{"delta":{"content":" (Resources"},"index":0}]}

data: {"id":"chatcmpl-abc123","choices":[{"delta":{"content":" Entities"},"index":0}]}

data: {"id":"chatcmpl-abc123","choices":[{"delta":{},"finish_reason":"stop","index":0}]}

data: [DONE]
```

## Configuration

### Environment Variables

```bash
# Chat Settings
CHAT__AUTO_INJECT_USER_CONTEXT=false  # Default: false (use REM LOOKUP hints)

# LLM Settings
LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
LLM__DEFAULT_TEMPERATURE=0.5

# PostgreSQL (required for session history)
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5432/rem
POSTGRES__ENABLED=true

# API Settings
API__HOST=0.0.0.0
API__PORT=8000
```

## Error Responses

### 500 - Agent Schema Not Found

```json
{
  "detail": "Agent schema 'invalid-schema' not found and default schema unavailable"
}
```

**Solution**: Use valid schema name or ensure default schema exists in `schemas/agents/rem.yaml`

### Session History Disabled

If PostgreSQL is disabled, session history will not be loaded:
- Session management skipped
- Each request treated as independent
- User profile hints still provided

## Best Practices

1. **Use Session IDs**: Always provide `X-Session-Id` for multi-turn conversations
2. **Generate Stable Session IDs**: Use UUIDs or meaningful identifiers
3. **Tenant Scoping**: Provide `X-Tenant-Id` for multi-tenant deployments
4. **Model Selection**: Choose appropriate model for task complexity
5. **Streaming**: Use streaming for long-running responses
6. **User Context**: Enable auto-inject only if always needed, otherwise use on-demand

## Compression and REM LOOKUP

When session history contains long messages, compression is applied:

**Original Message (800 chars):**
```
The REM system provides a comprehensive framework for managing resources,
entities, and moments in a scalable, multi-tenant environment. It combines
vector search, graph traversal, and temporal indexing to enable flexible
retrieval patterns. [... 600 more characters ...]
```

**Compressed Message:**
```
The REM system provides a comprehensive framework for managing resources,
entities, and moments in a scalable, multi-tenant environment. It combines
vector search, graph traversal, and temporal indexing to enable flexible

... [Message truncated - REM LOOKUP session-abc123-msg-1 to recover full content] ...

[... final 200 characters of original message ...]
```

**Agent Behavior:**
- Sees compressed version by default
- Can use `REM LOOKUP session-abc123-msg-1` to retrieve full content
- Only retrieves when needed for context

## Related Documentation

- [Content Headers](../../docs/content_headers.md) - Complete header reference
- [Agent Schemas](../../../schemas/agents/) - Available agent schemas
- [Session Compression](../../../services/session/compression.py) - Compression implementation
- [Context Builder](../../../agentic/context_builder.py) - Context construction logic
