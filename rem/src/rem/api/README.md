# REM API

FastAPI server for REM (Resources Entities Moments) system with OpenAI-compatible chat completions, MCP server, and RESTful endpoints.

## Running the API

### CLI Command

```bash
# Development mode (with auto-reload)
rem serve

# Production mode
rem serve --host 0.0.0.0 --port 8000 --workers 4
```

### CLI Options

```bash
rem serve --help

Options:
  --host TEXT       Host to bind to (default: 0.0.0.0)
  --port INTEGER    Port to listen on (default: 8000)
  --reload          Enable auto-reload for development (default: true)
  --workers INTEGER Number of worker processes (default: 1)
  --log-level TEXT  Logging level: debug, info, warning, error (default: info)
```

### Direct Python

```python
import uvicorn
from rem.api.main import app

uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
```

### Environment Variables

```bash
# API Server
API__HOST=0.0.0.0
API__PORT=8000
API__RELOAD=true
API__WORKERS=1
API__LOG_LEVEL=info

# Chat Settings
CHAT__AUTO_INJECT_USER_CONTEXT=false  # Default: false (use REM LOOKUP hints)

# LLM
LLM__DEFAULT_MODEL=anthropic:claude-sonnet-4-5-20250929
LLM__DEFAULT_TEMPERATURE=0.5
LLM__ANTHROPIC_API_KEY=sk-ant-...
LLM__OPENAI_API_KEY=sk-...

# PostgreSQL (required for session history)
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5432/rem
POSTGRES__ENABLED=true

# OpenTelemetry (optional)
OTEL__ENABLED=false
OTEL__SERVICE_NAME=rem-api
OTEL__COLLECTOR_ENDPOINT=http://localhost:4318
```

## Endpoints

### Chat Completions

**POST /v1/chat/completions** - OpenAI-compatible chat completions

Features:
- Streaming and non-streaming modes
- Session history with compression
- User profile integration via dreaming worker
- Multiple agent schemas
- Model override support

### MCP Server

**Mounted at /api/v1/mcp** - FastMCP server for Model Context Protocol

Tools:
- `ask_rem`: Query REM system using natural language
- `parse_and_ingest_file`: Ingest files into REM
- Additional MCP tools for REM operations

### Health Check

**GET /health** - Health check endpoint

## Content Headers

REM API uses custom headers to provide context, identify users, and manage sessions.

### Header Reference

| Header Name | Description | Example Value | Required |
|-------------|-------------|---------------|----------|
| `X-User-Id` | User identifier (email, UUID, or username) | `sarah@example.com`, `user-123` | No |
| `X-Tenant-Id` | Tenant identifier for multi-tenancy | `acme-corp`, `tenant-123` | No |
| `X-Session-Id` | Session identifier for conversation continuity (must be UUID) | `550e8400-e29b-41d4-a716-446655440000` | No |
| `X-Agent-Schema` | Agent schema name to use | `rem`, `query-agent` | No |
| `X-Chat-Is-Audio` | Indicates audio input in chat completions | `true`, `false` | No |
| `Authorization` | Bearer token for API authentication | `Bearer jwt_token_here` | Yes* |

*Required for authenticated endpoints. Not required for public endpoints.

## Session Management

REM chat API is designed for multi-turn conversations where each request contains a single message.

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
3. Stores profile in User entity (`metadata.profile` and model fields)

### User Profile in Chat

**On-Demand (Default):**
- Agent receives hint: `"User ID: sarah@example.com. To load user profile: Use REM LOOKUP users/sarah@example.com"`
- Agent decides whether to load based on query
- More efficient for queries that don't need personalization

**Auto-Inject (Optional):**
- Set environment variable: `CHAT__AUTO_INJECT_USER_CONTEXT=true`
- User profile automatically loaded and injected into system message
- Simpler for basic chatbots that always need context

## Usage Examples

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
  -H "X-Session-Id: 550e8400-e29b-41d4-a716-446655440000" \
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
  -H "X-Session-Id: 550e8400-e29b-41d4-a716-446655440000" \
  -d '{
    "model": "openai:gpt-4o",
    "messages": [
      {"role": "user", "content": "How are they created?"}
    ]
  }'
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

## Architecture

### Middleware Ordering

Middleware runs in reverse order of addition:
1. CORS (added last, runs first) - adds headers to all responses
2. Auth middleware - validates authentication
3. Logging middleware - logs requests/responses
4. Sessions middleware (added first, runs last)

### Stateless MCP Mounting

- FastMCP with `stateless_http=True` for Kubernetes compatibility
- Prevents stale session errors across pod restarts
- Mount at `/api/v1/mcp` for consistency
- Path rewrite middleware for trailing slash handling
- `redirect_slashes=False` prevents auth header stripping

### Context Building Flow

1. ContextBuilder extracts user_id, session_id from headers
2. Session history ALWAYS loaded with compression (if session_id provided)
3. User profile provided as REM LOOKUP hint (on-demand by default)
4. If CHAT__AUTO_INJECT_USER_CONTEXT=true: User profile auto-loaded
5. Combines: system context + compressed session history + new messages
6. Agent receives complete message list ready for execution

## Error Responses

### 500 - Agent Schema Not Found

```json
{
  "detail": "Agent schema 'invalid-schema' not found and default schema unavailable"
}
```

**Solution**: Use valid schema name or ensure default schema exists in `schemas/agents/rem.yaml`

## Best Practices

1. **Use Session IDs**: Always provide `X-Session-Id` for multi-turn conversations
2. **Generate Stable Session IDs**: Use UUIDs or meaningful identifiers
3. **Tenant Scoping**: Provide `X-Tenant-Id` for multi-tenant deployments
4. **Model Selection**: Choose appropriate model for task complexity
5. **Streaming**: Use streaming for long-running responses
6. **User Context**: Enable auto-inject only if always needed, otherwise use on-demand

## Related Documentation

- [Chat Router](routers/chat/completions.py) - Chat completions implementation
- [MCP Router](mcp_router/server.py) - MCP server implementation
- [Agent Schemas](../../schemas/agents/) - Available agent schemas
- [Session Compression](../../services/session/compression.py) - Compression implementation
- [Context Builder](../../agentic/context_builder.py) - Context construction logic
