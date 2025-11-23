"""
Dreaming Worker - REM memory indexing and insight extraction.

The dreaming worker processes user content to build the REM knowledge graph
through three core operations:

1. **User Model Updates**: Extract and update user profiles from activity
2. **Moment Construction**: Identify temporal narratives from resources
3. **Resource Affinity**: Build semantic relationships between resources

Design Philosophy:
- Lean implementation: Push complex utilities to services/repositories
- REM-first: Use REM system for all reads and writes
- Modular: Each operation is independent and composable
- Observable: Rich logging and metrics
- Cloud-native: Designed for Kubernetes CronJob execution

Architecture:
```
┌─────────────────────────────────────────────────────────────┐
│                    Dreaming Worker                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐  │
│  │   User Model  │  │    Moment     │  │   Resource    │  │
│  │   Updater     │  │  Constructor  │  │   Affinity    │  │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘  │
│          │                  │                  │          │
│          └──────────────────┼──────────────────┘          │
│                            │                              │
│                    ┌───────▼───────┐                      │
│                    │  REM Services │                      │
│                    │  - Repository │                      │
│                    │  - Query      │                      │
│                    │  - Embedding  │                      │
│                    └───────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

User Model Updates:
- Reads recent sessions, moments, resources, files
- Generates user summary using LLM
- Updates User entity with latest profile information
- Adds graph edges to key resources and moments

Moment Construction:
- Queries recent resources (lookback window)
- Uses LLM to extract temporal narratives
- Creates Moment entities with temporal boundaries
- Links moments to source resources via graph edges
- Generates embeddings for moment content

Resource Affinity:
- Semantic similarity mode (fast, vector-based)
- LLM mode (intelligent, context-aware)
- Creates graph edges between related resources
- Updates resource entities with affinity edges

CLI Usage:
```bash
# Update user models
rem-dreaming user-model --user-id=user-123

# Extract moments for user
rem-dreaming moments --user-id=user-123 --lookback-hours=24

# Build resource affinity (semantic mode)
rem-dreaming affinity --user-id=user-123 --lookback-hours=168

# Build resource affinity (LLM mode)
rem-dreaming affinity --user-id=user-123 --use-llm --limit=100

# Run all operations (recommended for daily cron)
rem-dreaming full --user-id=user-123

# Process all active users
rem-dreaming full --all-users
```

Environment Variables:
- REM_API_URL: REM API endpoint (default: http://rem-api:8000)
- REM_EMBEDDING_PROVIDER: Embedding provider (default: text-embedding-3-small)
- REM_DEFAULT_MODEL: LLM model (default: gpt-4o)
- REM_LOOKBACK_HOURS: Default lookback window (default: 24)
- OPENAI_API_KEY: OpenAI API key for embeddings/LLM

Kubernetes CronJob:
- Daily execution (3 AM): Full indexing for all tenants
- Resource limits: 512Mi memory, 1 CPU
- Spot instances: Tolerate node affinity
- Completion tracking: Save job results to database

Best Practices:
- Start with small lookback windows (24-48 hours)
- Use semantic mode for frequent updates (cheap, fast)
- Use LLM mode sparingly (expensive, slow)
- Always use --limit with LLM mode to control costs
- Monitor embedding/LLM costs in provider dashboard

Error Handling:
- Graceful degradation: Continue on partial failures
- Retry logic: Exponential backoff for transient errors
- Error reporting: Log errors with context for debugging
- Job status: Save success/failure status to database

Performance:
- Batch operations: Minimize round trips to REM API
- Streaming: Process large result sets incrementally
- Parallelization: Use asyncio for concurrent operations
- Caching: Cache embeddings and LLM responses when possible

Observability:
- Structured logging: JSON logs for parsing
- Metrics: Count processed resources, moments, edges
- Tracing: OpenTelemetry traces for distributed tracing
- Alerts: Notify on job failures or anomalies
"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, TYPE_CHECKING
from uuid import uuid4

import httpx
from loguru import logger
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from ..services.postgres import PostgresService
    from ..services.dreaming.affinity_service import AffinityMode


class TaskType(str, Enum):
    """Dreaming task types."""

    USER_MODEL = "user_model"
    MOMENTS = "moments"
    AFFINITY = "affinity"
    ONTOLOGY = "ontology"  # Extract domain-specific knowledge from files
    FULL = "full"


class DreamingJob(BaseModel):
    """Dreaming job execution record."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    task_type: TaskType
    status: str = "pending"  # pending, running, completed, failed
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class DreamingWorker:
    """
    REM dreaming worker for memory indexing.

    Processes user content to build the REM knowledge graph through
    user model updates, moment construction, and resource affinity.

    This is a lean implementation that delegates complex operations
    to REM services and repositories, keeping the worker focused on
    orchestration and coordination.

    User-ID First Approach:
    - All operations are scoped by user_id (primary identifier)
    - tenant_id field is set equal to user_id in entities (backward compatibility)
    - In single-user deployments, user_id is the only identifier needed
    - In future multi-tenant SaaS, tenant_id could group users (e.g., "acme-corp")
      enabling org-wide dreaming workflows and cross-user knowledge graphs
    - For now, all filtering and isolation is done via user_id
    """

    def __init__(
        self,
        rem_api_url: str = "http://rem-api:8000",
        embedding_provider: str = "text-embedding-3-small",
        default_model: str = "gpt-4o",
        lookback_hours: int = 24,
    ):
        """
        Initialize dreaming worker.

        Args:
            rem_api_url: REM API endpoint
            embedding_provider: Embedding provider for vector search
            default_model: Default LLM model for analysis
            lookback_hours: Default lookback window in hours
        """
        self.rem_api_url = rem_api_url
        self.embedding_provider = embedding_provider
        self.default_model = default_model
        self.lookback_hours = lookback_hours
        self.client = httpx.AsyncClient(base_url=rem_api_url, timeout=300.0)
        self._db: "PostgresService | None" = None  # Lazy-loaded database connection

    async def _ensure_db(self):
        """
        Ensure database connection is established.

        Lazy-loads and caches the database connection for reuse across
        multiple operations. Connection is shared for the lifetime of
        the worker instance.

        Returns:
            PostgresService instance
        """
        if not self._db:
            from rem.services.postgres import get_postgres_service
            self._db = get_postgres_service()
            if not self._db:
                raise RuntimeError("PostgreSQL service not available")
            await self._db.connect()
        return self._db

    async def close(self):
        """Close HTTP client and database connection."""
        await self.client.aclose()
        if self._db:
            await self._db.disconnect()
            self._db = None

    async def update_user_model(
        self,
        user_id: str,
        time_window_days: int = 30,
        max_sessions: int = 100,
        max_moments: int = 20,
        max_resources: int = 20,
    ) -> dict[str, Any]:
        """
        Update user model from recent activity.

        Delegates to user_model_service for implementation.

        Args:
            user_id: User to process
            time_window_days: Days to look back for activity (default: 30)
            max_sessions: Max sessions to analyze
            max_moments: Max moments to include
            max_resources: Max resources to include

        Returns:
            Statistics about user model update
        """
        from rem.services.dreaming import update_user_model as _update_user_model

        db = await self._ensure_db()

        return await _update_user_model(
            user_id=user_id,
            db=db,
            default_model=self.default_model,
            time_window_days=time_window_days,
            max_messages=max_sessions,  # Map max_sessions to max_messages parameter
            max_moments=max_moments,
            max_resources=max_resources,
        )

    async def construct_moments(
        self,
        user_id: str,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Extract moments from resources.

        Delegates to moment_service for implementation.

        Args:
            user_id: User to process
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max resources to process

        Returns:
            Statistics about moment construction
        """
        from rem.services.dreaming import construct_moments as _construct_moments

        lookback = lookback_hours or self.lookback_hours
        db = await self._ensure_db()

        return await _construct_moments(
            user_id=user_id,
            db=db,
            default_model=self.default_model,
            lookback_hours=lookback,
            limit=limit,
        )

    async def build_affinity(
        self,
        user_id: str,
        mode: Optional["AffinityMode"] = None,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
        similarity_threshold: float = 0.7,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """
        Build resource affinity graph.

        Delegates to affinity_service for implementation.

        Args:
            user_id: User to process
            mode: Affinity mode (semantic or llm)
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max resources to process (REQUIRED for LLM mode)
            similarity_threshold: Minimum similarity score for semantic mode (default: 0.7)
            top_k: Number of similar resources to find per resource (default: 3)

        Returns:
            Statistics about affinity construction
        """
        from rem.services.dreaming import build_affinity as _build_affinity
        from rem.services.dreaming.affinity_service import AffinityMode

        # Default to SEMANTIC mode if not provided
        if mode is None:
            mode = AffinityMode.SEMANTIC

        lookback = lookback_hours or self.lookback_hours
        db = await self._ensure_db()

        return await _build_affinity(
            user_id=user_id,
            db=db,
            mode=mode,  # Pass enum member, handled by service
            default_model=self.default_model,
            lookback_hours=lookback,
            limit=limit,
            similarity_threshold=similarity_threshold,
            top_k=top_k,
        )

    async def extract_ontologies(
        self,
        user_id: str,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Extract domain-specific knowledge from files using custom agents.

        Delegates to ontology_service for implementation.

        Args:
            user_id: User to process
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max files to process

        Returns:
            Statistics about ontology extraction
        """
        from rem.services.dreaming import extract_ontologies as _extract_ontologies

        lookback = lookback_hours or self.lookback_hours
        return await _extract_ontologies(
            user_id=user_id,
            lookback_hours=lookback,
            limit=limit,
        )

    async def process_full(
        self,
        user_id: str,
        use_llm_affinity: bool = False,
        lookback_hours: Optional[int] = None,
        extract_ontologies: bool = True,
    ) -> dict[str, Any]:
        """
        Run complete dreaming workflow.

        Executes all dreaming operations in sequence:
        1. Extract ontologies from files (if enabled)
        2. Update user model
        3. Construct moments
        4. Build resource affinity

        Recommended for daily cron execution.

        Args:
            user_id: User to process
            use_llm_affinity: Use LLM mode for affinity (expensive)
            lookback_hours: Hours to look back
            extract_ontologies: Whether to run ontology extraction (default: True)

        Returns:
            Aggregated statistics from all operations
        """
        lookback = lookback_hours or self.lookback_hours
        results = {
            "user_id": user_id,
            "lookback_hours": lookback,
            "ontologies": {},
            "user_model": {},
            "moments": {},
            "affinity": {},
        }

        # Ontology extraction (runs first to extract knowledge before moments)
        if extract_ontologies:
            try:
                results["ontologies"] = await self.extract_ontologies(
                    user_id=user_id,
                    lookback_hours=lookback,
                )
            except Exception as e:
                logger.exception("Ontology extraction failed")
                results["ontologies"] = {"error": str(e)}

        # User model update
        try:
            results["user_model"] = await self.update_user_model(
                user_id=user_id,
            )
        except Exception as e:
            logger.exception("User model update failed")
            results["user_model"] = {"error": str(e)}

        # Moment construction
        try:
            results["moments"] = await self.construct_moments(
                user_id=user_id,
                lookback_hours=lookback,
            )
        except Exception as e:
            logger.exception("Moment construction failed")
            results["moments"] = {"error": str(e)}

        # Resource affinity
        from rem.services.dreaming.affinity_service import AffinityMode as _AffinityMode
        affinity_mode = _AffinityMode.LLM if use_llm_affinity else _AffinityMode.SEMANTIC
        try:
            results["affinity"] = await self.build_affinity(
                user_id=user_id,
                mode=affinity_mode,
                lookback_hours=lookback,
            )
        except Exception as e:
            logger.exception("Resource affinity building failed")
            results["affinity"] = {"error": str(e)}

        return results

    async def process_all_users(
        self,
        task_type: TaskType = TaskType.FULL,
        use_llm_affinity: bool = False,
        lookback_hours: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """
        Process all active users.

        Queries REM for users with recent activity and processes
        each user according to task_type.

        Args:
            task_type: Task to run for each user
            use_llm_affinity: Use LLM mode for affinity
            lookback_hours: Hours to look back

        Returns:
            List of results for each user
        """
        lookback = lookback_hours or self.lookback_hours

        # TODO: Query REM for active users
        # Filter by recent activity (resources with timestamp > cutoff)
        # Process each user according to task_type

        # Stub implementation
        return [
            {
                "status": "stub_not_implemented",
                "message": "Query REM API for users with recent activity",
            }
        ]


async def main():
    """Main entry point (for testing)."""
    worker = DreamingWorker()
    try:
        # Example: Process single user
        result = await worker.process_full(
            user_id="user-123",
            use_llm_affinity=False,
            lookback_hours=24,
        )
        print(result)
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
