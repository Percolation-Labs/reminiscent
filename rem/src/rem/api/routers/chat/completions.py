"""
OpenAI-compatible chat completions router for REM.

Quick Start (Local Development)
===============================

NOTE: Local dev uses LOCAL databases (Postgres via Docker Compose on port 5050).
      Do NOT port-forward databases. Only port-forward observability services.

IMPORTANT: Session IDs MUST be UUIDs. Non-UUID session IDs will cause message
           storage issues and feedback will not work correctly.

1. Port Forwarding (REQUIRED for trace capture and Phoenix sync):

    # Terminal 1: OTEL Collector (HTTP) - sends traces to Phoenix
    kubectl port-forward -n observability svc/otel-collector-collector 4318:4318

    # Terminal 2: Phoenix UI - view traces at http://localhost:6006
    kubectl port-forward -n siggy svc/phoenix 6006:6006

2. Get Phoenix API Key (REQUIRED for feedback->Phoenix sync):

    export PHOENIX_API_KEY=$(kubectl get secret -n siggy rem-phoenix-api-key \\
      -o jsonpath='{.data.PHOENIX_API_KEY}' | base64 -d)

3. Start API with OTEL and Phoenix enabled:

    cd /path/to/remstack/rem
    source .venv/bin/activate
    OTEL__ENABLED=true \\
    PHOENIX__ENABLED=true \\
    PHOENIX_API_KEY="$PHOENIX_API_KEY" \\
    uvicorn rem.api.main:app --host 0.0.0.0 --port 8000 --app-dir src

4. Test Chat Request (session_id MUST be a UUID):

    SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
    curl -s -N -X POST http://localhost:8000/api/v1/chat/completions \\
      -H 'Content-Type: application/json' \\
      -H "X-Session-Id: $SESSION_ID" \\
      -H 'X-Agent-Schema: rem' \\
      -d '{"messages": [{"role": "user", "content": "Hello"}], "stream": true}'

    # Note: Use 'rem' agent schema (default) for real LLM responses.
    # The 'simulator' agent is for testing SSE events without LLM calls.

5. Submit Feedback on Response:

    The metadata SSE event contains message_id and trace_id for feedback:
        event: metadata
        data: {"message_id": "728882f8-...", "trace_id": "e53c701c...", ...}

    Use session_id (UUID you generated) and message_id to submit feedback:

    curl -X POST http://localhost:8000/api/v1/messages/feedback \\
      -H 'Content-Type: application/json' \\
      -H 'X-Tenant-Id: default' \\
      -d '{
        "session_id": "<your-uuid-session-id>",
        "message_id": "<message-id-from-metadata>",
        "rating": 1,
        "categories": ["helpful"],
        "comment": "Good response"
      }'

    Expected response (201 = synced to Phoenix):
        {"phoenix_synced": true, "trace_id": "e53c701c...", "span_id": "6432d497..."}

OTEL Architecture
=================

    REM API --[OTLP/HTTP]--> OTEL Collector --[relay]--> Phoenix
             (port 4318)    (k8s: observability)         (k8s: siggy)

Environment Variables:
    OTEL__ENABLED=true              Enable OTEL tracing (required for trace capture)
    PHOENIX__ENABLED=true           Enable Phoenix integration (required for feedback sync)
    PHOENIX_API_KEY=<jwt>           Phoenix API key (required for feedback->Phoenix sync)
    OTEL__COLLECTOR_ENDPOINT        Default: http://localhost:4318
    OTEL__PROTOCOL                  Default: http (use port 4318, not gRPC 4317)

Design Pattern
==============

- Headers map to AgentContext (X-User-Id, X-Tenant-Id, X-Session-Id, X-Agent-Schema, X-Is-Eval)
- ContextBuilder centralizes message construction with user profile + session history
- Body.model is the LLM model for Pydantic AI
- X-Agent-Schema header specifies which agent schema to use (defaults to 'rem')
- Support for streaming (SSE) and non-streaming modes
- Response format control (text vs json_object)
- OpenAI-compatible body fields: metadata, store, reasoning_effort, etc.

Context Building Flow:
1. ContextBuilder.build_from_headers() extracts user_id, session_id from headers
2. Session history ALWAYS loaded with compression (if session_id provided)
   - Uses SessionMessageStore with compression to keep context efficient
   - Long messages include REM LOOKUP hints: "... [REM LOOKUP session-{id}-msg-{index}] ..."
   - Agent can retrieve full content on-demand using REM LOOKUP
3. User profile provided as REM LOOKUP hint (on-demand by default)
   - Agent receives: "User: {email}. To load user profile: Use REM LOOKUP \"{email}\""
   - Agent decides whether to load profile based on query
4. If CHAT__AUTO_INJECT_USER_CONTEXT=true: User profile auto-loaded and injected
5. Combines: system context + compressed session history + new messages
6. Agent receives complete message list ready for execution

Headers Mapping
    X-User-Id        → AgentContext.user_id
    X-Tenant-Id      → AgentContext.tenant_id
    X-Session-Id     → AgentContext.session_id (use UUID for new sessions)
    X-Model-Name     → AgentContext.default_model (overrides body.model)
    X-Agent-Schema   → AgentContext.agent_schema_uri (defaults to 'rem')
    X-Is-Eval        → AgentContext.is_eval (sets session mode to EVALUATION)

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
    X-Session-Id: a1b2c3d4-e5f6-7890-abcd-ef1234567890  # UUID
    X-Agent-Schema: rem  # Optional, this is the default

    {
      "model": "openai:gpt-4o-mini",
      "messages": [
        {"role": "user", "content": "How do I create a new REM entity?"}
      ],
      "stream": true
    }
"""

import base64
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

from ....agentic.context import AgentContext
from ....agentic.context_builder import ContextBuilder
from ....agentic.providers.pydantic_ai import create_agent
from ....models.entities.session import Session, SessionMode
from ....services.audio.transcriber import AudioTranscriber
from ....services.postgres.repository import Repository
from ....services.session import SessionMessageStore, reload_session
from ....settings import settings
from ....utils.schema_loader import load_agent_schema, load_agent_schema_async
from .json_utils import extract_json_resilient
from .models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
)
from .streaming import stream_openai_response, stream_openai_response_with_save, stream_simulator_response

router = APIRouter(prefix="/api/v1", tags=["chat"])

# Default agent schema file
DEFAULT_AGENT_SCHEMA = "rem"


def get_current_trace_context() -> tuple[str | None, str | None]:
    """Get trace_id and span_id from current OTEL context.

    Returns:
        Tuple of (trace_id, span_id) as hex strings, or (None, None) if not available.
    """
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.get_span_context().is_valid:
            ctx = span.get_span_context()
            trace_id = format(ctx.trace_id, '032x')
            span_id = format(ctx.span_id, '016x')
            return trace_id, span_id
    except Exception:
        pass
    return None, None


def get_tracer():
    """Get the OpenTelemetry tracer for chat completions."""
    try:
        from opentelemetry import trace
        return trace.get_tracer("rem.chat.completions")
    except Exception:
        return None


async def ensure_session_with_metadata(
    session_id: str,
    user_id: str | None,
    tenant_id: str,
    is_eval: bool,
    request_metadata: dict[str, str] | None,
    agent_schema: str | None = None,
) -> None:
    """
    Ensure session exists and update with metadata/mode.

    If X-Is-Eval header is true, sets session mode to EVALUATION.
    Merges request metadata with existing session metadata.

    Args:
        session_id: Session identifier (maps to Session.name)
        user_id: User identifier
        tenant_id: Tenant identifier
        is_eval: Whether this is an evaluation session
        request_metadata: Metadata from request body to merge
        agent_schema: Optional agent schema being used
    """
    if not settings.postgres.enabled:
        return

    try:
        repo = Repository(Session, table_name="sessions")

        # Try to load existing session by name (session_id is the name field)
        existing_list = await repo.find(
            filters={"name": session_id, "tenant_id": tenant_id},
            limit=1,
        )
        existing = existing_list[0] if existing_list else None

        if existing:
            # Merge metadata if provided
            merged_metadata = existing.metadata or {}
            if request_metadata:
                merged_metadata.update(request_metadata)

            # Update session if eval flag or new metadata
            needs_update = False
            if is_eval and existing.mode != SessionMode.EVALUATION:
                existing.mode = SessionMode.EVALUATION
                needs_update = True
            if request_metadata:
                existing.metadata = merged_metadata
                needs_update = True

            if needs_update:
                await repo.upsert(existing)
                logger.debug(f"Updated session {session_id} (eval={is_eval}, metadata keys={list(merged_metadata.keys())})")
        else:
            # Create new session
            session = Session(
                name=session_id,
                mode=SessionMode.EVALUATION if is_eval else SessionMode.NORMAL,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_schema_uri=agent_schema,
                metadata=request_metadata or {},
            )
            await repo.upsert(session)
            logger.info(f"Created session {session_id} (eval={is_eval})")

    except Exception as e:
        # Non-critical - log but don't fail the request
        logger.error(f"Failed to ensure session metadata: {e}", exc_info=True)


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
    | X-Is-Eval           | Mark as evaluation session           | AgentContext.is_eval           | false         |

    Additional OpenAI-compatible Body Fields:
    - metadata: Key-value pairs merged with session metadata (max 16 keys)
    - store: Whether to store for distillation/evaluation
    - max_completion_tokens: Max tokens to generate (replaces max_tokens)
    - seed: Seed for deterministic sampling
    - top_p: Nucleus sampling probability
    - logprobs: Return log probabilities
    - reasoning_effort: low/medium/high for o-series models
    - service_tier: auto/flex/priority/default

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

    Evaluation Sessions:
    - Set X-Is-Eval: true header to mark session as evaluation
    - Session mode will be set to EVALUATION
    - Request metadata is merged with session metadata
    - Useful for A/B testing, model comparison, and feedback collection
    """
    # Load agent schema: use header value from context or default
    # Extract AgentContext from request (gets user_id from JWT token)
    temp_context = AgentContext.from_request(request)
    schema_name = temp_context.agent_schema_uri or DEFAULT_AGENT_SCHEMA

    # Resolve model: use body.model if provided, otherwise settings default
    if body.model is None:
        body.model = settings.llm.default_model
        logger.debug(f"No model specified, using default: {body.model}")

    # Special handling for simulator schema - no LLM, just generates demo SSE events
    # Check BEFORE loading schema since simulator doesn't need a schema file
    # Still builds full context and saves messages like a real agent
    if schema_name == "simulator":
        logger.info("Using SSE simulator (no LLM)")

        # Build context just like real agents (loads session history, user context)
        new_messages = [msg.model_dump() for msg in body.messages]
        context, messages = await ContextBuilder.build_from_headers(
            headers=dict(request.headers),
            new_messages=new_messages,
            user_id=temp_context.user_id,  # From JWT token (source of truth)
        )

        # Ensure session exists with metadata and eval mode if applicable
        if context.session_id:
            await ensure_session_with_metadata(
                session_id=context.session_id,
                user_id=context.user_id,
                tenant_id=context.tenant_id,
                is_eval=context.is_eval,
                request_metadata=body.metadata,
                agent_schema="simulator",
            )

        # Get the last user message as prompt
        prompt = body.messages[-1].content if body.messages else "demo"
        request_id = f"sim-{uuid.uuid4().hex[:24]}"

        # Generate message IDs upfront for correlation
        user_message_id = str(uuid.uuid4())
        assistant_message_id = str(uuid.uuid4())

        # Simulated assistant response content (for persistence)
        simulated_content = (
            f"[SSE Simulator Response]\n\n"
            f"This is a simulated response demonstrating all SSE event types:\n"
            f"- reasoning events (model thinking)\n"
            f"- text_delta events (streamed content)\n"
            f"- progress events (multi-step operations)\n"
            f"- tool_call events (function invocations)\n"
            f"- action_request events (UI solicitation)\n"
            f"- metadata events (confidence, sources, message IDs)\n\n"
            f"Original prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}"
        )

        # Save messages to database (if session_id and postgres enabled)
        if settings.postgres.enabled and context.session_id:
            user_message = {
                "id": user_message_id,
                "role": "user",
                "content": prompt,
                "timestamp": datetime.utcnow().isoformat(),
            }
            assistant_message = {
                "id": assistant_message_id,
                "role": "assistant",
                "content": simulated_content,
                "timestamp": datetime.utcnow().isoformat(),
            }

            try:
                store = SessionMessageStore(user_id=context.user_id or settings.test.effective_user_id)
                await store.store_session_messages(
                    session_id=context.session_id,
                    messages=[user_message, assistant_message],
                    user_id=context.user_id,
                    compress=True,
                )
                logger.info(f"Saved simulator conversation to session {context.session_id}")
            except Exception as e:
                # Log error but don't fail the request - session storage is non-critical
                logger.error(f"Failed to save session messages: {e}", exc_info=True)

        if body.stream:
            return StreamingResponse(
                stream_simulator_response(
                    prompt=prompt,
                    model="simulator-v1.0.0",
                    # Pass message correlation IDs
                    message_id=assistant_message_id,
                    in_reply_to=user_message_id,
                    session_id=context.session_id,
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            # Non-streaming simulator returns simple JSON
            return ChatCompletionResponse(
                id=request_id,
                created=int(time.time()),
                model="simulator-v1.0.0",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatMessage(
                            role="assistant",
                            content=simulated_content,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=ChatCompletionUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            )

    # Load schema using centralized utility
    # Enable database fallback to load dynamic agents stored in schemas table
    # Use async version since we're in an async context (FastAPI endpoint)
    user_id = temp_context.user_id or settings.test.effective_user_id
    try:
        agent_schema = await load_agent_schema_async(
            schema_name,
            user_id=user_id,
        )
    except FileNotFoundError:
        # Fallback to default if specified schema not found
        logger.warning(f"Schema '{schema_name}' not found, falling back to '{DEFAULT_AGENT_SCHEMA}'")
        schema_name = DEFAULT_AGENT_SCHEMA
        try:
            agent_schema = load_agent_schema(schema_name)
        except FileNotFoundError:
            # No schema available at all
            from fastapi import HTTPException

            raise HTTPException(
                status_code=500,
                detail=f"Agent schema '{schema_name}' not found and default schema unavailable",
            )

    logger.debug(f"Using agent schema: {schema_name}, model: {body.model}")

    # Check for audio input
    is_audio = request.headers.get("x-chat-is-audio", "").lower() == "true"

    # Process messages (transcribe audio if needed)
    new_messages = [msg.model_dump() for msg in body.messages]

    if is_audio and new_messages and new_messages[0]["role"] == "user":
        # First user message should be base64-encoded audio
        try:
            audio_b64 = new_messages[0]["content"]
            audio_bytes = base64.b64decode(audio_b64)

            # Write to temp file for transcription
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
                tmp_file.write(audio_bytes)
                tmp_path = tmp_file.name

            # Transcribe audio
            transcriber = AudioTranscriber()
            result = transcriber.transcribe_file(tmp_path)

            # Replace audio content with transcribed text
            new_messages[0]["content"] = result.text
            logger.info(f"Transcribed audio: {len(result.text)} characters")

            # Clean up temp file
            Path(tmp_path).unlink()

        except Exception as e:
            logger.error(f"Failed to transcribe audio: {e}")
            # Fall through with original content (will likely fail at agent)

    # Use ContextBuilder to construct complete message list with:
    # 1. System context hint (date + user profile)
    # 2. Session history (if session_id provided)
    # 3. New messages from request body (transcribed if audio)
    context, messages = await ContextBuilder.build_from_headers(
        headers=dict(request.headers),
        new_messages=new_messages,
        user_id=temp_context.user_id,  # From JWT token (source of truth)
    )

    logger.info(f"Built context with {len(messages)} total messages (includes history + user context)")

    # Ensure session exists with metadata and eval mode if applicable
    if context.session_id:
        await ensure_session_with_metadata(
            session_id=context.session_id,
            user_id=context.user_id,
            tenant_id=context.tenant_id,
            is_eval=context.is_eval,
            request_metadata=body.metadata,
            agent_schema=schema_name,
        )

    # Create agent with schema and model override
    agent = await create_agent(
        context=context,
        agent_schema_override=agent_schema,
        model_override=body.model,  # type: ignore[arg-type]
    )

    # Combine all messages into single prompt for agent
    # ContextBuilder already assembled: system context + history + new messages
    prompt = "\n".join(msg.content for msg in messages)

    # Generate OpenAI-compatible request ID
    request_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # Streaming mode
    if body.stream:
        # Save user message before streaming starts
        if settings.postgres.enabled and context.session_id:
            user_message = {
                "role": "user",
                "content": body.messages[-1].content if body.messages else "",
                "timestamp": datetime.utcnow().isoformat(),
            }
            try:
                store = SessionMessageStore(user_id=context.user_id or settings.test.effective_user_id)
                await store.store_session_messages(
                    session_id=context.session_id,
                    messages=[user_message],
                    user_id=context.user_id,
                    compress=False,  # User messages are typically short
                )
                logger.debug(f"Saved user message to session {context.session_id}")
            except Exception as e:
                logger.error(f"Failed to save user message: {e}", exc_info=True)

        return StreamingResponse(
            stream_openai_response_with_save(
                agent=agent,
                prompt=prompt,
                model=body.model,
                request_id=request_id,
                agent_schema=schema_name,
                session_id=context.session_id,
                user_id=context.user_id,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Non-streaming mode
    # Create a parent span to capture trace context for message storage
    trace_id, span_id = None, None
    tracer = get_tracer()

    if tracer:
        with tracer.start_as_current_span(
            "chat_completion",
            attributes={
                "session.id": context.session_id or "",
                "user.id": context.user_id or "",
                "model": body.model,
                "agent.schema": context.agent_schema_uri or DEFAULT_AGENT_SCHEMA,
            }
        ) as span:
            # Capture trace context from the span we just created
            trace_id, span_id = get_current_trace_context()
            result = await agent.run(prompt)
    else:
        # No tracer available, run without tracing
        result = await agent.run(prompt)

    # Determine content format based on response_format request
    if body.response_format and body.response_format.type == "json_object":
        # JSON mode: Best-effort extraction of JSON from agent output
        content = extract_json_resilient(result.output)  # type: ignore[attr-defined]
    else:
        # Text mode: Return as string (handle structured output)
        from rem.agentic.serialization import serialize_agent_result_json
        content = serialize_agent_result_json(result.output)  # type: ignore[attr-defined]

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
            "trace_id": trace_id,
            "span_id": span_id,
        }

        assistant_message = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            "trace_id": trace_id,
            "span_id": span_id,
        }

        try:
            # Store messages with compression
            store = SessionMessageStore(user_id=context.user_id or settings.test.effective_user_id)

            await store.store_session_messages(
                session_id=context.session_id,
                messages=[user_message, assistant_message],
                user_id=context.user_id,
                compress=True,
            )

            logger.info(f"Saved conversation to session {context.session_id}")
        except Exception as e:
            # Log error but don't fail the request - session storage is non-critical
            logger.error(f"Failed to save session messages: {e}", exc_info=True)

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
