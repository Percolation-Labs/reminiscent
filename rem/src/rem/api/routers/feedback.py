"""
Message feedback endpoint.

Provides endpoint for submitting feedback on messages.

Endpoints:
    POST /api/v1/messages/feedback - Submit feedback on a message

Trace Integration:
- Feedback can reference trace_id/span_id for OTEL integration
- Phoenix sync attaches feedback as span annotations (async)
"""

from fastapi import APIRouter, Header, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from ..deps import get_user_id_from_request
from ...models.entities import Feedback, Message
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


@router.post("/messages/feedback", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    request: Request,
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

    Returns:
        Created feedback object
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    effective_user_id = get_user_id_from_request(request)

    # Resolve trace_id/span_id from message if not provided
    trace_id = request_body.trace_id
    span_id = request_body.span_id

    if request_body.message_id and (not trace_id or not span_id):
        message_repo = Repository(Message, table_name="messages")
        message = await message_repo.get_by_id(request_body.message_id, x_tenant_id)
        if message:
            trace_id = trace_id or message.trace_id
            span_id = span_id or message.span_id

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

    # TODO: Async sync to Phoenix if trace_id/span_id available
    if trace_id and span_id:
        logger.debug(f"Feedback has trace info: trace={trace_id}, span={span_id}")

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
