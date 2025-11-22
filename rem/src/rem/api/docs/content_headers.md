# Content Headers

REM API uses custom headers to provide context, identify users, and manage sessions. All headers are optional unless specified.

## Header Reference

| Header Name | Description | Example Value | Required |
|-------------|-------------|---------------|----------|
| **User Context** | | | |
| `X-User-Id` | User identifier (email, UUID, or username) | `sarah@example.com`, `user-123` | No |
| `X-Tenant-Id` | Tenant identifier for multi-tenancy | `acme-corp`, `tenant-123` | No |
| **Session Context** | | | |
| `X-Session-Id` | Session identifier for conversation continuity | `session-abc123`, `sess-456def` | No |
| `X-Agent-Schema` | Agent schema name to use | `rem`, `query-agent`, `hello-world` | No |
| **Model Selection** | | | |
| `X-Model-Name` | Override LLM model for this request | `anthropic:claude-sonnet-4-5-20250929`, `openai:gpt-4o` | No |
| **Authentication** | | | |
| `Authorization` | Bearer token for API authentication | `Bearer jwt_token_here` | Yes* |

*Required for authenticated endpoints. Not required for public endpoints.

## REM-Specific Headers

### X-User-Id
User identifier used to:
- Load user profile from dreaming worker (on-demand via REM LOOKUP)
- Associate resources, messages, and moments with user
- Enable multi-user tenancy

Accepts:
- Email addresses: `sarah@example.com`
- UUIDs: `550e8400-e29b-41d4-a716-446655440000`
- Human-readable identifiers: `sarah-chen`, `john-smith`

### X-Tenant-Id
Tenant identifier for data isolation. REM is multi-tenant by design:
- All data scoped to tenant_id
- Users can belong to tenants (e.g., "acme-corp", "engineering-team")
- If not provided, defaults to user_id for single-user deployments

### X-Session-Id
Session identifier for conversation continuity:
- Required for multi-turn conversations
- Session history ALWAYS loaded with compression
- Long messages compressed with REM LOOKUP hints
- New messages automatically saved to session

### X-Agent-Schema
Specifies which agent schema to use:
- Default: `rem` (REM expert assistant)
- Custom agents: `query-agent`, `contract-extractor`, etc.
- Schemas loaded from `schemas/agents/` directory

### X-Model-Name
Override the default LLM model for this request:
- Anthropic: `anthropic:claude-sonnet-4-5-20250929`, `anthropic:claude-3-7-sonnet-20250219`
- OpenAI: `openai:gpt-4o`, `openai:gpt-4o-mini`
- Google: `google:gemini-1.5-pro`, `google:gemini-2.0-flash-exp`

## Session Management

REM chat API is designed for multi-turn conversations where each request contains a single message:

1. Client sends message with `X-Session-Id` header
2. Server loads compressed session history from database
3. Long messages include REM LOOKUP hints: `"... [REM LOOKUP session-123-msg-1] ..."`
4. Agent can retrieve full content on-demand using REM LOOKUP
5. New messages saved to database with compression

### Session History Compression
- Short messages (<400 chars): Stored and loaded as-is
- Long messages (>400 chars): Compressed with REM LOOKUP hints
- Agent retrieves full content only when needed
- Prevents context window bloat while maintaining continuity

## User Profiles and Dreaming

The dreaming worker runs periodically to build user models from activity:

1. Analyzes user's resources, sessions, and moments
2. Generates profile with:
   - Current projects and technical focus
   - Expertise areas and learning interests
   - Collaboration patterns and work style
   - Recent activity summary
3. Stores profile in User entity (`metadata.profile` and model fields)

### User Profile Access
By default, user profile is on-demand:
- Agent receives: `"User ID: sarah@example.com. To load user profile: Use REM LOOKUP users/sarah@example.com"`
- Agent decides whether to load based on query
- More efficient for queries that don't need personalization

Optional auto-inject (set `CHAT__AUTO_INJECT_USER_CONTEXT=true`):
- User profile automatically loaded and injected into system message
- Simpler for basic chatbots that always need context

## Header Validation

- All headers are case-insensitive
- Headers starting with `X-` are custom REM headers
- Timestamps should be in ISO 8601 format (UTC)
- Model names must include provider prefix: `provider:model-id`

## Security Considerations

- Never include sensitive information in headers that might be logged
- Use `Authorization` header for authentication tokens
- Validate all header values on the server side
- Rate limiting based on user/tenant headers

## Usage Examples

See [Chat Router README](../routers/chat/README.md) for detailed examples.
