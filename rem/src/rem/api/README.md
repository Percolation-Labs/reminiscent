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

## Authentication

### Production Authentication

When `AUTH__ENABLED=true`, users authenticate via OAuth (Google or Microsoft). The OAuth flow:

1. User visits `/api/auth/google/login` or `/api/auth/microsoft/login`
2. User authenticates with provider
3. Callback stores user in session cookie
4. Subsequent requests use session cookie

### Development Token (Non-Production Only)

For local development and testing, you can use a dev token instead of OAuth. This endpoint is available at `/api/dev/token` whenever `ENVIRONMENT != "production"`, regardless of whether auth is enabled.

**Get Token:**
```bash
curl http://localhost:8000/api/dev/token
```

**Response:**
```json
{
  "token": "dev_89737a19376332bfd9a4a06db8b79fd1",
  "type": "Bearer",
  "user": {
    "id": "test-user",
    "email": "test@rem.local",
    "name": "Test User"
  },
  "usage": "curl -H \"Authorization: Bearer dev_...\" http://localhost:8000/api/v1/...",
  "warning": "This token is for development/testing only and will not work in production."
}
```

**Use Token:**
```bash
# Get the token
TOKEN=$(curl -s http://localhost:8000/api/dev/token | jq -r .token)

# Use it in requests
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Tenant-Id: default" \
     http://localhost:8000/api/v1/shared-with-me
```

**Security Notes:**
- Only available when `ENVIRONMENT != "production"`
- Token is HMAC-signed using session secret
- Authenticates as `test-user` with `pro` tier and `admin` role
- Token is deterministic per environment (same secret = same token)

### Anonymous Access

When `AUTH__ALLOW_ANONYMOUS=true` (default in development):
- Requests without authentication are allowed
- Anonymous users get rate-limited access
- MCP endpoints still require auth unless `AUTH__MCP_REQUIRES_AUTH=false`

## Usage Examples

**Note on Authentication**: By default, authentication is disabled (`AUTH__ENABLED=false`) for local development and testing. The examples below work without an `Authorization` header. If authentication is enabled, use either:
- **Dev token**: `-H "Authorization: Bearer $(curl -s http://localhost:8000/api/dev/token | jq -r .token)"`
- **Session cookie**: Login via OAuth first, then use cookies

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
session_id = str(uuid.uuid4())  # Must be a valid UUID

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

### Python: Audio Input (Voice Chat)

```python
import requests
import base64

# Read audio file and encode to base64
with open("recording.wav", "rb") as audio_file:
    audio_b64 = base64.b64encode(audio_file.read()).decode('utf-8')

url = "http://localhost:8000/api/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "X-User-Id": "sarah@example.com",
    "X-Chat-Is-Audio": "true"  # Trigger audio transcription
}
data = {
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [
        {"role": "user", "content": audio_b64}  # Base64-encoded WAV audio
    ]
}

response = requests.post(url, headers=headers, json=data)
print(response.json()["choices"][0]["message"]["content"])

# Audio is transcribed to text using OpenAI Whisper
# Then processed as normal text chat
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

## Extended SSE Event Protocol

REM uses OpenAI-compatible format for text content streaming, plus custom named SSE events for rich UI interactions.

### Event Types

| Event Type | Format | Purpose | UI Display |
|------------|--------|---------|------------|
| (text content) | `data:` (OpenAI format) | Content chunks | Main response area |
| `reasoning` | `event:` | Model thinking | Collapsible "thinking" section |
| `progress` | `event:` | Step indicators | Progress bar/stepper |
| `tool_call` | `event:` | Tool invocations | Tool status panel |
| `action_request` | `event:` | User input solicitation | Buttons, forms, modals |
| `metadata` | `event:` | System info | Hidden or badge display |
| `error` | `event:` | Error notification | Error toast/alert |
| `done` | `event:` | Stream completion | Cleanup signal |

### Event Format

**Text content (OpenAI-compatible `data:` format):**
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1732748123,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello "},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1732748123,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"world!"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1732748123,"model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

**Named events (use `event:` prefix):**
```
event: reasoning
data: {"type": "reasoning", "content": "Analyzing the request...", "step": 1}

event: progress
data: {"type": "progress", "step": 1, "total_steps": 3, "label": "Searching", "status": "in_progress"}

event: tool_call
data: {"type": "tool_call", "tool_name": "search_rem", "status": "started", "arguments": {"query": "..."}}

event: action_request
data: {"type": "action_request", "card": {"id": "feedback-1", "prompt": "Was this helpful?", "actions": [...]}}

event: metadata
data: {"type": "metadata", "confidence": 0.95, "sources": ["doc1.md"], "hidden": false}

event: done
data: {"type": "done", "reason": "stop"}
```

### Action Request Cards (Adaptive Cards-inspired)

Action requests solicit user input using a schema inspired by [Microsoft Adaptive Cards](https://adaptivecards.io/):

```json
{
  "type": "action_request",
  "card": {
    "id": "confirm-delete-123",
    "prompt": "Are you sure you want to delete this item?",
    "display_style": "modal",
    "actions": [
      {
        "type": "Action.Submit",
        "id": "confirm",
        "title": "Delete",
        "style": "destructive",
        "data": {"action": "delete", "item_id": "123"}
      },
      {
        "type": "Action.Submit",
        "id": "cancel",
        "title": "Cancel",
        "style": "secondary",
        "data": {"action": "cancel"}
      }
    ],
    "inputs": [
      {
        "type": "Input.Text",
        "id": "reason",
        "label": "Reason (optional)",
        "placeholder": "Why are you deleting this?"
      }
    ],
    "timeout_ms": 30000
  }
}
```

**Action Types:**
- `Action.Submit` - Send data to server
- `Action.OpenUrl` - Navigate to URL
- `Action.ShowCard` - Reveal nested content

**Input Types:**
- `Input.Text` - Text field (single or multiline)
- `Input.ChoiceSet` - Dropdown/radio selection
- `Input.Toggle` - Checkbox/toggle

### SSE Simulator Endpoint

For frontend development and testing, use the simulator which generates all event types without LLM costs:

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Agent-Schema: simulator" \
  -d '{"messages": [{"role": "user", "content": "demo"}], "stream": true}'
```

The simulator produces a scripted sequence demonstrating:
1. Reasoning events (4 steps)
2. Progress indicators
3. Simulated tool calls
4. Rich markdown content
5. Metadata with confidence
6. Action request for feedback

See `rem/agentic/agents/sse_simulator.py` for implementation details.

### Frontend Integration

```typescript
// Parse SSE events in React/TypeScript
const eventSource = new EventSource('/api/v1/chat/completions');

eventSource.onmessage = (e) => {
  // Default handler for data-only events (text_delta)
  const event = JSON.parse(e.data);
  if (event.type === 'text_delta') {
    appendContent(event.content);
  }
};

eventSource.addEventListener('reasoning', (e) => {
  const event = JSON.parse(e.data);
  appendReasoning(event.content);
});

eventSource.addEventListener('action_request', (e) => {
  const event = JSON.parse(e.data);
  showActionCard(event.card);
});

eventSource.addEventListener('done', () => {
  eventSource.close();
});
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

### 429 - Rate Limit Exceeded

When a user exceeds their rate limit (based on their tier), the API returns a 429 status code with a structured error body. The frontend should intercept this error to prompt the user to sign in or upgrade.

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "You have exceeded your rate limit. Please sign in or upgrade to continue.",
    "details": {
      "limit": 50,
      "tier": "anonymous",
      "retry_after": 60
    }
  }
}
```

**Handling Strategy:**
1.  **Intercept 429s:** API client should listen for `status === 429`.
2.  **Check Code:** If `error.code === 'rate_limit_exceeded'` AND `error.details.tier === 'anonymous'`, trigger "Login / Sign Up" flow.
3.  **Authenticated Users:** If `tier !== 'anonymous'`, prompt to upgrade plan.

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
- [SSE Events](routers/chat/sse_events.py) - SSE event type definitions
- [SSE Simulator](../../agentic/agents/sse_simulator.py) - Event simulator for testing
- [MCP Router](mcp_router/server.py) - MCP server implementation
- [Agent Schemas](../../schemas/agents/) - Available agent schemas
- [Session Compression](../../services/session/compression.py) - Compression implementation
- [Context Builder](../../agentic/context_builder.py) - Context construction logic
