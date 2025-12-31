"""
Message feedback endpoint.

Provides endpoint for submitting feedback on messages.

Endpoints:
    POST /api/v1/messages/feedback - Submit feedback on a message

Trace Integration:
- Feedback auto-resolves trace_id/span_id from the message in the database
- Phoenix sync attaches feedback as span annotations when trace info is available

HTTP Status Codes:
- 201: Feedback saved AND synced to Phoenix as annotation (phoenix_synced=true)
- 200: Feedback accepted and saved to DB, but NOT synced to Phoenix
       (missing trace_id/span_id, Phoenix disabled, or sync failed)

IMPORTANT - Testing Requirements:
    ╔════════════════════════════════════════════════════════════════════════════════════════════════════╗
    ║  1. Use 'rem' agent (NOT 'simulator') - only real agents capture traces                            ║
    ║  2. Session IDs MUST be UUIDs - use python3 -c "import uuid; print(uuid.uuid4())"                  ║
    ║  3. Port-forward OTEL collector: kubectl port-forward -n observability                             ║
    ║       svc/otel-collector-collector 4318:4318                                                       ║
    ║  4. Port-forward Phoenix: kubectl port-forward -n siggy svc/phoenix 6006:6006                      ║
    ║  5. Set environment variables when starting the API:                                               ║
    ║       OTEL__ENABLED=true PHOENIX__ENABLED=true PHOENIX_API_KEY=<jwt> uvicorn ...                   ║
    ║  6. Get PHOENIX_API_KEY:                                                                           ║
    ║       kubectl get secret -n siggy rem-phoenix-api-key -o jsonpath='{.data.PHOENIX_API_KEY}'        ║
    ║         | base64 -d                                                                                ║
    ╚════════════════════════════════════════════════════════════════════════════════════════════════════╝

Usage:
    # 1. Send a chat message with X-Session-Id header (MUST be UUID!)
    SESSION_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
    curl -X POST http://localhost:8000/api/v1/chat/completions \\
        -H "Content-Type: application/json" \\
        -H "X-Session-Id: $SESSION_ID" \\
        -H "X-Agent-Schema: rem" \\
        -d '{"messages": [{"role": "user", "content": "hello"}], "stream": true}'

    # 2. Extract message_id from the 'metadata' SSE event:
    #    event: metadata
    #    data: {"message_id": "728882f8-...", "trace_id": "e53c701c...", ...}

    # 3. Submit feedback referencing that message (trace_id auto-resolved from DB)
    curl -X POST http://localhost:8000/api/v1/messages/feedback \\
        -H "Content-Type: application/json" \\
        -H "X-Tenant-Id: default" \\
        -d '{
            "session_id": "'$SESSION_ID'",
            "message_id": "<message-id-from-metadata>",
            "rating": 1,
            "categories": ["helpful"],
            "comment": "Great response!"
        }'

    # 4. Check response:
    #    - 201 + phoenix_synced=true = annotation synced to Phoenix (check Phoenix UI at :6006)
    #    - 200 + phoenix_synced=false = feedback saved but not synced (missing trace info)
"""

from fastapi import APIRouter, Header, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel, Field

from .common import ErrorResponse

from ..deps import get_user_id_from_request
from ...models.entities import Feedback
from ...services.postgres import Repository
from ...settings import settings

router = APIRouter(prefix="/api/v1", tags=["messages"])


# =============================================================================
# Request/Response Models
# =============================================================================


class FeedbackCreateRequest(BaseModel):
    """Request to submit feedback."""

    session_id: str = Field(description="Session ID this feedback relates to")
    message_id: str | None = Field(
        default=None, description="Specific message ID (null for session-level)"
    )
    rating: int | None = Field(
        default=None,
        ge=-1,
        le=5,
        description="Rating: -1 (thumbs down), 1 (thumbs up), or 1-5 scale",
    )
    categories: list[str] = Field(
        default_factory=list, description="Feedback categories"
    )
    comment: str | None = Field(default=None, description="Free-text comment")
    trace_id: str | None = Field(
        default=None, description="OTEL trace ID (auto-resolved if message has it)"
    )
    span_id: str | None = Field(
        default=None, description="OTEL span ID (auto-resolved if message has it)"
    )


class FeedbackResponse(BaseModel):
    """Response after submitting feedback."""

    id: str
    session_id: str
    message_id: str | None
    rating: int | None
    categories: list[str]
    comment: str | None
    trace_id: str | None
    span_id: str | None
    phoenix_synced: bool
    created_at: str


# =============================================================================
# Feedback Endpoint
# =============================================================================


@router.post(
    "/messages/feedback",
    response_model=FeedbackResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Database not enabled"},
    },
)
async def submit_feedback(
    request: Request,
    response: Response,
    request_body: FeedbackCreateRequest,
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> FeedbackResponse:
    """
    Submit feedback on a message or session.

    If message_id is provided, feedback is attached to that specific message.
    If only session_id is provided, feedback applies to the entire session.

    Trace IDs (trace_id, span_id) can be:
    - Provided explicitly in the request
    - Auto-resolved from the message if message_id is provided

    HTTP Status Codes:
    - 201: Feedback saved AND synced to Phoenix (phoenix_synced=true)
    - 200: Feedback accepted but NOT synced (missing trace info, disabled, or failed)

    Returns:
        Created feedback object with phoenix_synced indicating sync status
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    effective_user_id = get_user_id_from_request(request)

    # Resolve trace_id/span_id from message if not provided
    trace_id = request_body.trace_id
    span_id = request_body.span_id

    if request_body.message_id and (not trace_id or not span_id):
        # Look up message by ID to get trace context
        # Note: Messages are stored with tenant_id=user_id (not x_tenant_id header)
        # so we query by ID only - UUIDs are globally unique
        from ...services.postgres import PostgresService
        import uuid

        logger.info(f"Looking up trace context for message_id={request_body.message_id}")

        # Convert message_id string to UUID for database query
        try:
            message_uuid = uuid.UUID(request_body.message_id)
        except ValueError as e:
            logger.warning(f"Invalid message_id format '{request_body.message_id}': {e}")
            message_uuid = None

        if message_uuid:
            db = PostgresService()
            # Ensure connection (same pattern as Repository)
            if not db.pool:
                await db.connect()

            if db.pool:
                query = """
                    SELECT trace_id, span_id FROM messages
                    WHERE id = $1 AND deleted_at IS NULL
                    LIMIT 1
                """
                async with db.pool.acquire() as conn:
                    row = await conn.fetchrow(query, message_uuid)
                    logger.info(f"Database query result for message {request_body.message_id}: row={row}")
                    if row:
                        trace_id = trace_id or row["trace_id"]
                        span_id = span_id or row["span_id"]
                        logger.info(f"Found trace context for message {request_body.message_id}: trace_id={trace_id}, span_id={span_id}")
                    else:
                        logger.warning(f"No message found in database with id={request_body.message_id}")
            else:
                logger.warning(f"Database pool not available for message lookup after connect attempt")

    feedback = Feedback(
        session_id=request_body.session_id,
        message_id=request_body.message_id,
        rating=request_body.rating,
        categories=request_body.categories,
        comment=request_body.comment,
        trace_id=trace_id,
        span_id=span_id,
        phoenix_synced=False,
        annotator_kind="HUMAN",
        user_id=effective_user_id,
        tenant_id=x_tenant_id,
    )

    repo = Repository(Feedback, table_name="feedbacks")
    result = await repo.upsert(feedback)

    logger.info(
        f"Feedback submitted: session={request_body.session_id}, "
        f"message={request_body.message_id}, rating={request_body.rating}"
    )

    # Sync to Phoenix if trace_id/span_id available and Phoenix is enabled
    phoenix_synced = False
    phoenix_annotation_id = None

    if trace_id and span_id and settings.phoenix.enabled:
        try:
            from ...services.phoenix import PhoenixClient

            phoenix_client = PhoenixClient()
            phoenix_annotation_id = phoenix_client.sync_user_feedback(
                span_id=span_id,
                rating=request_body.rating,
                categories=request_body.categories,
                comment=request_body.comment,
                feedback_id=str(result.id),
                trace_id=trace_id,
            )

            if phoenix_annotation_id:
                phoenix_synced = True
                # Update the feedback record with sync status
                result.phoenix_synced = True
                result.phoenix_annotation_id = phoenix_annotation_id
                await repo.upsert(result)
                logger.info(f"Feedback synced to Phoenix: annotation_id={phoenix_annotation_id}")
            else:
                logger.warning(f"Phoenix sync returned no annotation ID for feedback {result.id}")

        except Exception as e:
            logger.error(f"Failed to sync feedback to Phoenix: {e}")
            # Don't fail the request if Phoenix sync fails
    elif trace_id and span_id:
        logger.debug(f"Feedback has trace info but Phoenix disabled: trace={trace_id}, span={span_id}")

    # Set HTTP status code based on Phoenix sync result
    # 201 = synced to Phoenix, 200 = accepted but not synced
    response.status_code = 201 if phoenix_synced else 200

    return FeedbackResponse(
        id=str(result.id),
        session_id=result.session_id,
        message_id=result.message_id,
        rating=result.rating,
        categories=result.categories,
        comment=result.comment,
        trace_id=result.trace_id,
        span_id=result.span_id,
        phoenix_synced=result.phoenix_synced,
        created_at=result.created_at.isoformat() if result.created_at else "",
    )
