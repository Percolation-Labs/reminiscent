"""
OpenAI-compatible chat completions router for REM.

Design Pattern:
- Headers map to AgentContext (X-User-Id, X-Tenant-Id, X-Session-Id, X-Model-Name, X-Agent-Schema)
- Body.model is the LLM model for Pydantic AI
- X-Model-Name header can override body.model
- X-Agent-Schema header specifies which agent schema to use (defaults to 'rem-agent')
- Support for streaming (SSE) and non-streaming modes
- Response format control (text vs json_object)

Headers Mapping
    X-User-Id        → AgentContext.user_id
    X-Tenant-Id      → AgentContext.tenant_id
    X-Session-Id     → AgentContext.session_id
    X-Model-Name     → AgentContext.default_model (overrides body.model)
    X-Agent-Schema   → AgentContext.agent_schema_uri (defaults to 'rem-agent')

Default Agent:
    If X-Agent-Schema header is not provided, the system loads 'rem-agent' schema,
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
    X-Agent-Schema: rem-agent  # Optional, this is the default

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
from pathlib import Path

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from ....agentic.context import AgentContext
from ....agentic.providers.pydantic_ai import create_pydantic_ai_agent
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
DEFAULT_AGENT_SCHEMA = "rem-agent"
# Path: .../rem/src/rem/api/routers/chat/completions.py -> .../rem/schemas
SCHEMAS_DIR = Path(__file__).parent.parent.parent.parent.parent.parent / "schemas"


def load_agent_schema(schema_name: str) -> dict | None:
    """
    Load agent schema from YAML file.

    Args:
        schema_name: Schema name (e.g., 'rem-agent', 'query-agent')

    Returns:
        Agent schema dict or None if not found
    """
    schema_file = SCHEMAS_DIR / f"{schema_name}.yaml"
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
    The X-Agent-Schema header specifies which agent schema to use (defaults to 'rem-agent').

    Supported Headers:
    | Header              | Description                          | Maps To                        | Default       |
    |---------------------|--------------------------------------|--------------------------------|---------------|
    | X-User-Id           | User identifier                      | AgentContext.user_id           | None          |
    | X-Tenant-Id         | Tenant identifier (multi-tenancy)    | AgentContext.tenant_id         | "default"     |
    | X-Session-Id        | Session/conversation identifier      | AgentContext.session_id        | None          |
    | X-Agent-Schema      | Agent schema name                    | AgentContext.agent_schema_uri  | "rem-agent"   |

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

    Default Agent (rem-agent):
    - Expert assistant for REM system
    - Comprehensive knowledge of REM architecture, concepts, and implementation
    - Structured output with answer, confidence, and references
    """
    # Create context from headers (maps headers to AgentContext fields)
    context = AgentContext.from_headers(dict(request.headers))

    # Load agent schema: use header value if provided, otherwise use default
    schema_name = context.agent_schema_uri or DEFAULT_AGENT_SCHEMA
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

    # Create agent with schema and model override
    agent = await create_pydantic_ai_agent(
        context=context,
        agent_schema_override=agent_schema,
        model_override=body.model,
    )

    # Combine system and user messages into single prompt
    prompt = "\n".join(
        msg.content or "" for msg in body.messages if msg.role in ("system", "user")
    )

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
