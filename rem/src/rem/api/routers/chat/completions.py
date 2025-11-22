"""
OpenAI-compatible chat completions router for REM.

Design Pattern:
- Headers map to AgentContext (X-User-Id, X-Tenant-Id, X-Session-Id, X-Model-Name, X-Agent-Schema)
- ContextBuilder centralizes message construction with user profile + session history
- Body.model is the LLM model for Pydantic AI
- X-Model-Name header can override body.model
- X-Agent-Schema header specifies which agent schema to use (defaults to 'rem')
- Support for streaming (SSE) and non-streaming modes
- Response format control (text vs json_object)

Context Building Flow:
1. ContextBuilder.build_from_headers() extracts user_id, session_id from headers
2. Session history ALWAYS loaded with compression (if session_id provided)
   - Uses SessionMessageStore with compression to keep context efficient
   - Long messages include REM LOOKUP hints: "... [REM LOOKUP session-{id}-msg-{index}] ..."
   - Agent can retrieve full content on-demand using REM LOOKUP
3. User profile provided as REM LOOKUP hint (on-demand by default)
   - Agent receives: "User ID: {user_id}. To load user profile: Use REM LOOKUP users/{user_id}"
   - Agent decides whether to load profile based on query
4. If CHAT__AUTO_INJECT_USER_CONTEXT=true: User profile auto-loaded and injected
5. Combines: system context + compressed session history + new messages
6. Agent receives complete message list ready for execution

Headers Mapping
    X-User-Id        → AgentContext.user_id
    X-Tenant-Id      → AgentContext.tenant_id
    X-Session-Id     → AgentContext.session_id
    X-Model-Name     → AgentContext.default_model (overrides body.model)
    X-Agent-Schema   → AgentContext.agent_schema_uri (defaults to 'rem')

Default Agent:
    If X-Agent-Schema header is not provided, the system loads 'rem' schema,
    which is the REM expert assistant with comprehensive knowledge about:
    - REM architecture and concepts
    - Entity types and graph traversal
    - REM queries (LOOKUP, FUZZY, TRAVERSE)
    - Agent development with Pydantic AI
    - Cloud infrastructure (EKS, Karpenter, CloudNativePG)

Example Request:
    POST /api/v1/chat/completions
    X-Tenant-Id: acme-corp
    X-User-Id: user123
    X-Agent-Schema: rem  # Optional, this is the default

    {
      "model": "openai:gpt-4o-mini",
      "messages": [
        {"role": "user", "content": "How do I create a new REM entity?"}
      ],
      "stream": true
    }
"""

import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from ....agentic.context import AgentContext
from ....agentic.context_builder import ContextBuilder
from ....agentic.providers.pydantic_ai import create_pydantic_ai_agent
from ....services.session import SessionMessageStore, reload_session
from ....settings import settings
from .json_utils import extract_json_resilient
from .models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
)
from .streaming import stream_openai_response

router = APIRouter(prefix="/v1", tags=["chat"])

# Default agent schema file
DEFAULT_AGENT_SCHEMA = "rem"
# Path: .../rem/src/rem/api/routers/chat/completions.py -> .../rem/schemas
SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "schemas"


def load_agent_schema(schema_name: str) -> dict | None:
    """
    Load agent schema from YAML file.

    Looks for schema in schemas/agents/ directory.

    Args:
        schema_name: Schema name (e.g., 'rem', 'query', 'hello-world')

    Returns:
        Agent schema dict or None if not found
    """
    # Look for schema in agents/ subdirectory
    schema_file = SCHEMAS_DIR / "agents" / f"{schema_name}.yaml"
    if not schema_file.exists():
        logger.warning(f"Agent schema not found: {schema_file}")
        return None

    try:
        with open(schema_file, "r") as f:
            schema = yaml.safe_load(f)
        logger.debug(f"Loaded agent schema: {schema_name}")
        return schema
    except Exception as e:
        logger.error(f"Failed to load agent schema {schema_name}: {e}")
        return None


@router.post("/chat/completions", response_model=None)
async def chat_completions(body: ChatCompletionRequest, request: Request):
    """
    OpenAI-compatible chat completions with REM agent support.

    The 'model' field in the request body is the LLM model used by Pydantic AI.
    The X-Agent-Schema header specifies which agent schema to use (defaults to 'rem').

    Supported Headers:
    | Header              | Description                          | Maps To                        | Default       |
    |---------------------|--------------------------------------|--------------------------------|---------------|
    | X-User-Id           | User identifier                      | AgentContext.user_id           | None          |
    | X-Tenant-Id         | Tenant identifier (multi-tenancy)    | AgentContext.tenant_id         | "default"     |
    | X-Session-Id        | Session/conversation identifier      | AgentContext.session_id        | None          |
    | X-Agent-Schema      | Agent schema name                    | AgentContext.agent_schema_uri  | "rem"         |

    Example Models:
    - anthropic:claude-sonnet-4-5-20250929 (Claude 4.5 Sonnet)
    - anthropic:claude-3-7-sonnet-20250219 (Claude 3.7 Sonnet)
    - anthropic:claude-3-5-haiku-20241022 (Claude 3.5 Haiku)
    - openai:gpt-4.1-turbo
    - openai:gpt-4o
    - openai:gpt-4o-mini

    Response Formats:
    - text (default): Plain text response
    - json_object: Best-effort JSON extraction from agent output

    Default Agent (rem):
    - Expert assistant for REM system
    - Comprehensive knowledge of REM architecture, concepts, and implementation
    - Structured output with answer, confidence, and references

    Session Management:
    - Session history ALWAYS loaded with compression when X-Session-Id provided
    - Uses SessionMessageStore with REM LOOKUP hints for long messages
    - User profile provided as REM LOOKUP hint (on-demand by default)
    - If CHAT__AUTO_INJECT_USER_CONTEXT=true: User profile auto-loaded and injected
    - New messages saved to database with compression for session continuity
    - When Postgres is disabled, session management is skipped
    """
    # Load agent schema: use header value from context or default
    # Extract AgentContext first to get schema name
    temp_context = AgentContext.from_headers(dict(request.headers))
    schema_name = temp_context.agent_schema_uri or DEFAULT_AGENT_SCHEMA
    agent_schema = load_agent_schema(schema_name)

    if agent_schema is None:
        # Fallback to default if specified schema not found
        logger.warning(f"Schema '{schema_name}' not found, falling back to '{DEFAULT_AGENT_SCHEMA}'")
        schema_name = DEFAULT_AGENT_SCHEMA
        agent_schema = load_agent_schema(schema_name)

    if agent_schema is None:
        # No schema available at all
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail=f"Agent schema '{schema_name}' not found and default schema unavailable",
        )

    logger.info(f"Using agent schema: {schema_name}, model: {body.model}")

    # Build complete context from headers (includes user profile + session history + date)
    # This replaces manual session reloading and message construction
    new_messages = [msg.model_dump() for msg in body.messages]

    # Use ContextBuilder to construct complete message list with:
    # 1. System context hint (date + user profile)
    # 2. Session history (if session_id provided)
    # 3. New messages from request body
    context, messages = await ContextBuilder.build_from_headers(
        headers=dict(request.headers),
        new_messages=new_messages,
    )

    logger.info(f"Built context with {len(messages)} total messages (includes history + user context)")

    # Create agent with schema and model override
    agent = await create_pydantic_ai_agent(
        context=context,
        agent_schema_override=agent_schema,
        model_override=body.model,
    )

    # Combine all messages into single prompt for agent
    # ContextBuilder already assembled: system context + history + new messages
    prompt = "\n".join(msg.content for msg in messages)

    # Generate OpenAI-compatible request ID
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # Streaming mode
    if body.stream:
        return StreamingResponse(
            stream_openai_response(agent, prompt, body.model, request_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Non-streaming mode
    result = await agent.run(prompt)

    # Determine content format based on response_format request
    if body.response_format and body.response_format.type == "json_object":
        # JSON mode: Best-effort extraction of JSON from agent output
        content = extract_json_resilient(result.output)
    else:
        # Text mode: Return as string (handle structured output)
        if hasattr(result.output, "model_dump_json"):
            content = result.output.model_dump_json()
        else:
            content = str(result.output)

    # Get usage from result if available
    usage = result.usage() if hasattr(result, "usage") else None
    prompt_tokens = usage.input_tokens if usage else 0
    completion_tokens = usage.output_tokens if usage else 0

    # Save conversation messages to database (if session_id and postgres enabled)
    if settings.postgres.enabled and context.session_id:
        # Extract just the new user message (last message from body)
        user_message = {
            "role": "user",
            "content": body.messages[-1].content if body.messages else "",
            "timestamp": datetime.utcnow().isoformat(),
        }

        assistant_message = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }

        # Store messages with compression
        store = SessionMessageStore(tenant_id=context.tenant_id or "default")

        await store.store_session_messages(
            session_id=context.session_id,
            messages=[user_message, assistant_message],
            user_id=context.user_id,
            compress=True,
        )

        logger.info(f"Saved conversation to session {context.session_id}")

    return ChatCompletionResponse(
        id=request_id,
        created=int(time.time()),
        model=body.model,  # Echo back the requested model
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatMessage(role="assistant", content=content),
                finish_reason="stop",
            )
        ],
        usage=ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )
