"""
Feedback endpoints for chat message and session feedback.

Provides endpoints for:
- Submitting feedback on messages or sessions
- Listing feedback with filters
- Syncing feedback to Phoenix as annotations (async)

Endpoints:
    POST /api/v1/feedback              - Submit feedback
    GET  /api/v1/feedback              - List feedback with filters
    GET  /api/v1/feedback/{id}         - Get specific feedback
    GET  /api/v1/feedback/categories   - List available categories

Trace Integration:
- Feedback can reference trace_id/span_id for OTEL integration
- Phoenix sync attaches feedback as span annotations
"""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from loguru import logger
from pydantic import BaseModel, Field

from ..deps import get_current_user, get_user_filter, get_user_id_from_request, is_admin
from ...models.entities import Feedback, FeedbackCategory, Message
from ...services.postgres import Repository
from ...settings import settings
from ...utils.date_utils import utc_now

router = APIRouter(prefix="/api/v1", tags=["feedback"])


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
        default_factory=list, description="Selected feedback categories"
    )
    comment: str | None = Field(default=None, description="Free-text comment")
    # Optional trace reference (can be auto-resolved from message)
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


class FeedbackListResponse(BaseModel):
    """Response for feedback list endpoint."""

    object: Literal["list"] = "list"
    data: list[Feedback]
    total: int
    has_more: bool


class CategoryInfo(BaseModel):
    """Information about a feedback category."""

    value: str
    label: str
    description: str
    sentiment: Literal["positive", "negative", "neutral"]


class CategoriesResponse(BaseModel):
    """Response for categories endpoint."""

    categories: list[CategoryInfo]


# =============================================================================
# Category Definitions
# =============================================================================

CATEGORY_INFO: dict[str, CategoryInfo] = {
    FeedbackCategory.INCOMPLETE.value: CategoryInfo(
        value=FeedbackCategory.INCOMPLETE.value,
        label="Incomplete",
        description="Response lacks expected information",
        sentiment="negative",
    ),
    FeedbackCategory.INACCURATE.value: CategoryInfo(
        value=FeedbackCategory.INACCURATE.value,
        label="Inaccurate",
        description="Response contains factual errors",
        sentiment="negative",
    ),
    FeedbackCategory.POOR_TONE.value: CategoryInfo(
        value=FeedbackCategory.POOR_TONE.value,
        label="Poor Tone",
        description="Inappropriate or unprofessional tone",
        sentiment="negative",
    ),
    FeedbackCategory.OFF_TOPIC.value: CategoryInfo(
        value=FeedbackCategory.OFF_TOPIC.value,
        label="Off Topic",
        description="Response doesn't address the question",
        sentiment="negative",
    ),
    FeedbackCategory.TOO_VERBOSE.value: CategoryInfo(
        value=FeedbackCategory.TOO_VERBOSE.value,
        label="Too Verbose",
        description="Unnecessarily long response",
        sentiment="negative",
    ),
    FeedbackCategory.TOO_BRIEF.value: CategoryInfo(
        value=FeedbackCategory.TOO_BRIEF.value,
        label="Too Brief",
        description="Insufficiently detailed response",
        sentiment="negative",
    ),
    FeedbackCategory.CONFUSING.value: CategoryInfo(
        value=FeedbackCategory.CONFUSING.value,
        label="Confusing",
        description="Hard to understand or unclear",
        sentiment="negative",
    ),
    FeedbackCategory.UNSAFE.value: CategoryInfo(
        value=FeedbackCategory.UNSAFE.value,
        label="Unsafe",
        description="Contains potentially harmful content",
        sentiment="negative",
    ),
    FeedbackCategory.HELPFUL.value: CategoryInfo(
        value=FeedbackCategory.HELPFUL.value,
        label="Helpful",
        description="Response was useful and addressed the need",
        sentiment="positive",
    ),
    FeedbackCategory.EXCELLENT.value: CategoryInfo(
        value=FeedbackCategory.EXCELLENT.value,
        label="Excellent",
        description="Exceptionally good response",
        sentiment="positive",
    ),
    FeedbackCategory.ACCURATE.value: CategoryInfo(
        value=FeedbackCategory.ACCURATE.value,
        label="Accurate",
        description="Factually correct and precise",
        sentiment="positive",
    ),
    FeedbackCategory.WELL_WRITTEN.value: CategoryInfo(
        value=FeedbackCategory.WELL_WRITTEN.value,
        label="Well Written",
        description="Clear, well-structured response",
        sentiment="positive",
    ),
    FeedbackCategory.OTHER.value: CategoryInfo(
        value=FeedbackCategory.OTHER.value,
        label="Other",
        description="Other feedback not covered by categories",
        sentiment="neutral",
    ),
}


# =============================================================================
# Feedback Endpoints
# =============================================================================


@router.get("/feedback/categories", response_model=CategoriesResponse)
async def list_categories() -> CategoriesResponse:
    """
    List available feedback categories.

    Returns predefined categories with labels, descriptions, and sentiment.
    """
    return CategoriesResponse(categories=list(CATEGORY_INFO.values()))


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
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

    Phoenix sync happens asynchronously after feedback is stored.

    Returns:
        Created feedback object
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    # Get effective user_id from auth or anonymous tracking
    effective_user_id = get_user_id_from_request(request)

    # Resolve trace_id/span_id from message if not provided
    trace_id = request_body.trace_id
    span_id = request_body.span_id

    if request_body.message_id and (not trace_id or not span_id):
        # Try to get trace info from the message
        message_repo = Repository(Message, table_name="messages")
        message = await message_repo.get_by_id(request_body.message_id, x_tenant_id)
        if message:
            trace_id = trace_id or message.trace_id
            span_id = span_id or message.span_id

    # Create feedback entity
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

    # Store feedback (table is "feedbacks" - plural)
    repo = Repository(Feedback, table_name="feedbacks")
    result = await repo.upsert(feedback)

    logger.info(
        f"Feedback submitted: session={request_body.session_id}, "
        f"message={request_body.message_id}, rating={request_body.rating}, "
        f"categories={request_body.categories}"
    )

    # TODO: Async sync to Phoenix if trace_id/span_id available
    # This would be done via a background task or queue
    if trace_id and span_id:
        logger.debug(f"Feedback has trace info: trace={trace_id}, span={span_id}")
        # TODO: Queue for Phoenix annotation sync
        # await sync_feedback_to_phoenix(feedback)

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


@router.get("/feedback", response_model=FeedbackListResponse)
async def list_feedback(
    request: Request,
    session_id: str | None = Query(default=None, description="Filter by session ID"),
    message_id: str | None = Query(default=None, description="Filter by message ID"),
    rating: int | None = Query(default=None, description="Filter by rating"),
    category: str | None = Query(default=None, description="Filter by category"),
    phoenix_synced: bool | None = Query(
        default=None, description="Filter by Phoenix sync status"
    ),
    limit: int = Query(default=50, ge=1, le=100, description="Max results"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> FeedbackListResponse:
    """
    List feedback with optional filters.

    Access Control:
    - Regular users: Only see feedback they submitted
    - Admin users: Can see all feedback

    Filters:
    - session_id: Filter by session
    - message_id: Filter by specific message
    - rating: Filter by rating value
    - category: Filter by category (checks if category in list)
    - phoenix_synced: Filter by sync status
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Feedback, table_name="feedbacks")

    # Build user-scoped filters (uses anon_id for anonymous users)
    filters = await get_user_filter(request, x_tenant_id=x_tenant_id)

    # Apply optional filters
    if session_id:
        filters["session_id"] = session_id
    if message_id:
        filters["message_id"] = message_id
    if rating is not None:
        filters["rating"] = rating
    if phoenix_synced is not None:
        filters["phoenix_synced"] = phoenix_synced
    # TODO: category filter requires array contains query

    feedback_list = await repo.find(
        filters,
        order_by="created_at DESC",
        limit=limit + 1,
        offset=offset,
    )

    # Filter by category in Python if specified (until Repository supports array contains)
    if category:
        feedback_list = [f for f in feedback_list if category in f.categories]

    has_more = len(feedback_list) > limit
    if has_more:
        feedback_list = feedback_list[:limit]

    total = await repo.count(filters)

    return FeedbackListResponse(data=feedback_list, total=total, has_more=has_more)


@router.get("/feedback/{feedback_id}", response_model=Feedback)
async def get_feedback(
    request: Request,
    feedback_id: str,
    x_tenant_id: str = Header(alias="X-Tenant-Id", default="default"),
) -> Feedback:
    """
    Get specific feedback by ID.

    Access Control:
    - Regular users: Only access their own feedback
    - Admin users: Can access any feedback
    """
    if not settings.postgres.enabled:
        raise HTTPException(status_code=503, detail="Database not enabled")

    repo = Repository(Feedback, table_name="feedbacks")
    feedback = await repo.get_by_id(feedback_id, x_tenant_id)

    if not feedback:
        raise HTTPException(status_code=404, detail=f"Feedback '{feedback_id}' not found")

    # Check access
    current_user = get_current_user(request)
    if not is_admin(current_user):
        user_id = current_user.get("id") if current_user else None
        if feedback.user_id and feedback.user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied: not owner")

    return feedback


# =============================================================================
# Phoenix Sync (Stub - TODO: Implement background task)
# =============================================================================


async def sync_feedback_to_phoenix(feedback: Feedback) -> bool:
    """
    Sync feedback to Phoenix as a span annotation.

    TODO: Implement this as a background task.

    This should:
    1. Connect to Phoenix client
    2. Resolve trace/span from feedback
    3. Create annotation with feedback data
    4. Update feedback.phoenix_synced = True
    5. Store phoenix_annotation_id

    Args:
        feedback: Feedback entity to sync

    Returns:
        True if synced successfully
    """
    if not feedback.span_id:
        logger.warning(f"Cannot sync feedback {feedback.id}: no span_id")
        return False

    try:
        # TODO: Import and use Phoenix client
        # from ...services.phoenix import PhoenixClient
        # client = PhoenixClient()
        #
        # # Build annotation from feedback
        # label = None
        # if feedback.categories:
        #     label = feedback.categories[0]  # Primary category
        #
        # score = None
        # if feedback.rating:
        #     # Normalize to 0-1 scale
        #     if feedback.rating == -1:
        #         score = 0.0
        #     elif feedback.rating >= 1 and feedback.rating <= 5:
        #         score = feedback.rating / 5.0
        #
        # client.add_span_feedback(
        #     span_id=feedback.span_id,
        #     annotation_name="user_feedback",
        #     annotator_kind=feedback.annotator_kind,
        #     label=label,
        #     score=score,
        #     explanation=feedback.comment,
        # )
        #
        # # Update feedback record
        # feedback.phoenix_synced = True
        # repo = Repository(Feedback, table_name="feedbacks")
        # await repo.update(feedback)

        logger.info(f"TODO: Sync feedback {feedback.id} to Phoenix span {feedback.span_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to sync feedback to Phoenix: {e}")
        return False
