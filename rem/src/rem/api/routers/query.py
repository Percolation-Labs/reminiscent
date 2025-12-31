"""
REM Query API - Execute REM dialect or natural language queries.

Endpoints:
    POST /api/v1/query - Execute a REM query

Modes:
    - rem-dialect (default): Execute REM query syntax directly
      Example: "LOOKUP sarah-chen", "SEARCH resources 'API design'", "TRAVERSE FROM doc-123 DEPTH 2"

    - natural-language: Convert natural language to REM query via LLM agent
      Example: "Find all documents by Sarah", "What meetings happened last week?"

    - staged-plan: Execute a multi-stage query plan (query field is ignored)
      Example: Execute a sequence of queries with context passing between stages
      Status: TODO - signature only, implementation pending in RemService

Model Selection:
    Default model: openai:gpt-4.1 (widely available, good balance of speed/quality)

    Recommended for speed: cerebras:qwen-3-32b
    - Cerebras provides extremely fast inference (~1000 tokens/sec)
    - Set CEREBRAS_API_KEY environment variable
    - Pass model="cerebras:qwen-3-32b" in request

Example:
    # REM dialect (default)
    curl -X POST http://localhost:8000/api/v1/query \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: user123" \\
        -d '{"query": "LOOKUP sarah-chen"}'

    # Natural language
    curl -X POST http://localhost:8000/api/v1/query \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: user123" \\
        -d '{"query": "Find all documents about API design", "mode": "natural-language"}'

    # With Cerebras for speed
    curl -X POST http://localhost:8000/api/v1/query \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: user123" \\
        -d '{"query": "Who is Sarah?", "mode": "natural-language", "model": "cerebras:qwen-3-32b"}'

    # Staged plan (TODO) - static query stages
    curl -X POST http://localhost:8000/api/v1/query \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: user123" \\
        -d '{"mode": "staged-plan", "plan": [
            {"stage": 1, "query": "LOOKUP Sarah Chen", "name": "user"},
            {"stage": 2, "query": "TRAVERSE FROM \"Sarah Chen\" DEPTH 2"}
        ]}'

    # Staged plan with LLM-driven dynamic stages
    curl -X POST http://localhost:8000/api/v1/query \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: user123" \\
        -d '{"mode": "staged-plan", "plan": [
            {"stage": 1, "query": "LOOKUP Sarah Chen", "name": "user"},
            {"stage": 2, "intent": "find her team members", "depends_on": ["user"]}
        ]}'

    # Plan continuation - pass previous_results to resume a multi-turn plan
    # Turn 1: Execute stage 1, get back stage_results
    # Turn 2: Continue with stage 2, passing previous results
    curl -X POST http://localhost:8000/api/v1/query \\
        -H "Content-Type: application/json" \\
        -H "X-User-Id: user123" \\
        -d '{
            "mode": "staged-plan",
            "plan": [
                {"stage": 1, "query": "LOOKUP Sarah Chen", "name": "user"},
                {"stage": 2, "intent": "find her team members", "depends_on": ["user"]}
            ],
            "previous_results": [
                {"stage": 1, "name": "user", "query_executed": "LOOKUP Sarah Chen", "results": [...], "count": 1}
            ],
            "resume_from_stage": 2
        }'
"""

from enum import Enum
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from .common import ErrorResponse

from ...services.postgres import get_postgres_service
from ...services.rem.service import RemService
from ...services.rem.parser import RemQueryParser
from ...models.core import RemQuery
from ...settings import settings

router = APIRouter(prefix="/api/v1", tags=["query"])


class QueryMode(str, Enum):
    """Query execution mode."""
    REM_DIALECT = "rem-dialect"
    NATURAL_LANGUAGE = "natural-language"
    STAGED_PLAN = "staged-plan"


class StagedPlanResult(BaseModel):
    """Result from a completed stage - used for plan continuation."""

    stage: int = Field(..., description="Stage number that produced this result")
    name: str | None = Field(default=None, description="Stage name for referencing")
    query_executed: str = Field(..., description="The REM query that was executed")
    results: list[dict[str, Any]] = Field(default_factory=list, description="Query results")
    count: int = Field(default=0, description="Number of results")


class QueryPlanStage(BaseModel):
    """A single stage in a multi-stage query plan.

    Each stage can be either:
    1. A static REM dialect query (query field set)
    2. A dynamic query built by LLM from intent + previous results (intent field set)

    The LLM interprets the intent along with previous stage results to construct
    the appropriate REM query at runtime.
    """

    stage: int = Field(..., description="Stage number (1-indexed, executed in order)")
    query: str | None = Field(
        default=None,
        description="Static REM dialect query (mutually exclusive with intent)",
    )
    intent: str | None = Field(
        default=None,
        description="Natural language intent - LLM builds query from this + previous results",
    )
    name: str | None = Field(default=None, description="Optional name for referencing results")
    depends_on: list[str] | None = Field(
        default=None,
        description="Names of previous stages whose results are passed as context to LLM",
    )


class QueryRequest(BaseModel):
    """Request body for REM query execution."""

    query: str | None = Field(
        default=None,
        description="Query string - either REM dialect syntax or natural language. Required for rem-dialect and natural-language modes.",
        examples=[
            "LOOKUP sarah-chen",
            "SEARCH resources 'API design' LIMIT 10",
            "Find all documents by Sarah",
        ],
    )

    mode: QueryMode = Field(
        default=QueryMode.REM_DIALECT,
        description="Query mode: 'rem-dialect' (default), 'natural-language', or 'staged-plan'",
    )

    model: str = Field(
        default="openai:gpt-4.1",
        description=(
            "LLM model for natural-language mode. "
            "Default: openai:gpt-4.1. "
            "Recommended for speed: cerebras:qwen-3-32b (requires CEREBRAS_API_KEY)"
        ),
    )

    plan_only: bool = Field(
        default=False,
        description="If true with natural-language mode, return generated query without executing",
    )

    plan: list[QueryPlanStage] | None = Field(
        default=None,
        description="Multi-stage query plan for staged-plan mode. Each stage executes in order.",
    )

    previous_results: list[StagedPlanResult] | None = Field(
        default=None,
        description=(
            "Results from previous turns for plan continuation. "
            "Pass this back from the response's stage_results to continue a multi-turn plan."
        ),
    )

    resume_from_stage: int | None = Field(
        default=None,
        description="Stage number to resume from (1-indexed). Stages before this are skipped.",
    )


class QueryResponse(BaseModel):
    """Response from REM query execution."""

    query_type: str = Field(..., description="Type of query executed (LOOKUP, SEARCH, FUZZY, SQL, TRAVERSE)")
    query: str = Field(..., description="The query that was executed (original or generated)")
    results: list[dict[str, Any]] = Field(default_factory=list, description="Query results")
    count: int = Field(..., description="Number of results")

    # Natural language mode fields
    mode: QueryMode = Field(..., description="Query mode used")
    generated_query: str | None = Field(default=None, description="Generated REM query (natural-language mode only)")
    confidence: float | None = Field(default=None, description="Confidence score (natural-language mode only)")
    reasoning: str | None = Field(default=None, description="Query reasoning (natural-language mode only)")
    warning: str | None = Field(default=None, description="Warning message if any")
    plan_only: bool = Field(default=False, description="If true, query was not executed (plan mode)")

    # Staged plan mode fields
    stage_results: list[dict[str, Any]] | None = Field(
        default=None,
        description="Results from each stage (staged-plan mode only)",
    )


@router.post(
    "/query",
    response_model=QueryResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid query or missing required fields"},
        500: {"model": ErrorResponse, "description": "Query execution failed"},
        501: {"model": ErrorResponse, "description": "Feature not yet implemented"},
        503: {"model": ErrorResponse, "description": "Database not configured or unavailable"},
    },
)
async def execute_query(
    request: QueryRequest,
    x_user_id: str | None = Header(default=None, description="User ID for query isolation (optional, uses default if not provided)"),
) -> QueryResponse:
    """
    Execute a REM query.

    Supports three modes:

    **rem-dialect** (default): Execute REM query syntax directly.
    - LOOKUP "entity-key" - O(1) key-value lookup
    - FUZZY "text" THRESHOLD 0.3 - Fuzzy text matching
    - SEARCH table "semantic query" LIMIT 10 - Vector similarity search
    - TRAVERSE FROM "entity" TYPE "rel" DEPTH 2 - Graph traversal
    - SQL SELECT * FROM table WHERE ... - Direct SQL (SELECT only)

    **natural-language**: Convert question to REM query via LLM.
    - Uses REM Query Agent to parse intent
    - Auto-executes if confidence >= 0.7
    - Returns warning for low-confidence queries

    **staged-plan**: Execute a multi-stage query plan.
    - Pass plan=[{stage: 1, query: "...", name: "..."}, ...] instead of query
    - Stages execute in order with context passing between them
    - TODO: Implementation pending in RemService

    **Model Selection**:
    - Default: openai:gpt-4.1 (reliable, widely available)
    - Speed: cerebras:qwen-3-32b (requires CEREBRAS_API_KEY)

    Returns:
        QueryResponse with results and metadata
    """
    if not settings.postgres.enabled:
        raise HTTPException(
            status_code=503,
            detail="Database not configured. Set POSTGRES__ENABLED=true",
        )

    try:
        # Get database service and ensure connected
        db = get_postgres_service()
        if db is None:
            raise HTTPException(status_code=503, detail="Database service unavailable")

        # Connect if not already connected
        if db.pool is None:
            await db.connect()

        rem_service = RemService(db)

        # Use effective_user_id from settings if not provided
        effective_user_id = x_user_id or settings.test.effective_user_id

        if request.mode == QueryMode.STAGED_PLAN:
            # Staged plan mode - execute multi-stage query plan
            # TODO: Implementation pending in RemService.execute_staged_plan()
            if not request.plan:
                raise HTTPException(
                    status_code=400,
                    detail="staged-plan mode requires 'plan' field with list of QueryPlanStage",
                )

            logger.info(f"Staged plan query: {len(request.plan)} stages")

            # TODO: Call rem_service.execute_staged_plan(request.plan, x_user_id)
            # For now, return a 501 Not Implemented
            raise HTTPException(
                status_code=501,
                detail="staged-plan mode not yet implemented. See RemService TODO.",
            )

        elif request.mode == QueryMode.NATURAL_LANGUAGE:
            # Natural language mode - use agent to convert
            if not request.query:
                raise HTTPException(
                    status_code=400,
                    detail="natural-language mode requires 'query' field",
                )

            logger.info(f"Natural language query: {request.query[:100]}... (model={request.model})")

            result = await rem_service.ask_rem(
                natural_query=request.query,
                tenant_id=effective_user_id,
                llm_model=request.model,
                plan_mode=request.plan_only,
            )

            # Build response
            response = QueryResponse(
                query_type=result.get("results", {}).get("query_type", "UNKNOWN"),
                query=request.query,
                results=result.get("results", {}).get("results", []),
                count=result.get("results", {}).get("count", 0),
                mode=QueryMode.NATURAL_LANGUAGE,
                generated_query=result.get("query"),
                confidence=result.get("confidence"),
                reasoning=result.get("reasoning"),
                warning=result.get("warning"),
                plan_only=result.get("plan_mode", False),
            )

            return response

        else:
            # REM dialect mode - parse and execute directly
            if not request.query:
                raise HTTPException(
                    status_code=400,
                    detail="rem-dialect mode requires 'query' field",
                )

            logger.info(f"REM dialect query: {request.query[:100]}...")

            parser = RemQueryParser()
            query_type, parameters = parser.parse(request.query)

            # Create and execute RemQuery
            rem_query = RemQuery.model_validate({
                "query_type": query_type,
                "parameters": parameters,
                "user_id": effective_user_id,
            })

            result = await rem_service.execute_query(rem_query)

            return QueryResponse(
                query_type=result["query_type"],
                query=request.query,
                results=result.get("results", []),
                count=result.get("count", 0),
                mode=QueryMode.REM_DIALECT,
            )

    except HTTPException:
        # Re-raise HTTPExceptions (400, 501, etc.) without wrapping
        raise
    except ValueError as e:
        # Parse errors
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Query execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"Query execution failed: {str(e)}")
