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
# Update user models for tenant
rem-dreaming user-model --tenant-id=tenant-123

# Extract moments for tenant
rem-dreaming moments --tenant-id=tenant-123 --lookback-hours=24

# Build resource affinity (semantic mode)
rem-dreaming affinity --tenant-id=tenant-123 --lookback-hours=168

# Build resource affinity (LLM mode)
rem-dreaming affinity --tenant-id=tenant-123 --use-llm --limit=100

# Run all operations (recommended for daily cron)
rem-dreaming full --tenant-id=tenant-123

# Process all active tenants
rem-dreaming full --all-tenants
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
from typing import Any, Optional
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """Dreaming task types."""

    USER_MODEL = "user_model"
    MOMENTS = "moments"
    AFFINITY = "affinity"
    ONTOLOGY = "ontology"  # Extract domain-specific knowledge from files
    FULL = "full"


class AffinityMode(str, Enum):
    """Resource affinity modes."""

    SEMANTIC = "semantic"  # Fast vector similarity
    LLM = "llm"  # Intelligent LLM-based assessment


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

    Note: Uses user_id as the primary grain. Later we can add tenant_id
    for enterprise grouping of users.
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

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()

    async def update_user_model(
        self,
        user_id: str,
        max_sessions: int = 100,
        max_moments: int = 20,
        max_resources: int = 20,
    ) -> dict[str, Any]:
        """
        Update user model from recent activity.

        Reads recent sessions, moments, and resources to generate
        a comprehensive user profile summary using LLM analysis.

        Process:
        1. Query REM for recent sessions, moments, resources for this user
        2. Generate user summary using LLM
        3. Update User entity with summary and metadata
        4. Add graph edges to key resources and moments

        Args:
            user_id: User to process
            max_sessions: Max sessions to analyze
            max_moments: Max moments to include
            max_resources: Max resources to include

        Returns:
            Statistics about user model update
        """
        # TODO: Implement using REM query API
        # Use REM LOOKUP and FUZZY queries to fetch recent activity
        # Generate summary with LLM via REM chat completion endpoint
        # Update User entity via REM repository

        # Stub implementation
        return {
            "user_id": user_id,
            "sessions_analyzed": 0,
            "moments_included": 0,
            "resources_included": 0,
            "user_updated": False,
            "status": "stub_not_implemented",
        }

    async def construct_moments(
        self,
        user_id: str,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Extract moments from resources.

        Analyzes recent resources to identify temporal narratives
        (meetings, coding sessions, conversations) and creates
        Moment entities with temporal boundaries and metadata.

        Process:
        1. Query REM for recent resources for this user (lookback window)
        2. Use LLM to extract temporal narratives
        3. Create Moment entities via REM repository
        4. Link moments to source resources via graph edges
        5. Generate embeddings for moment content

        Args:
            user_id: User to process
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max resources to process

        Returns:
            Statistics about moment construction
        """
        # TODO: Implement using REM query API
        # Query resources with timestamp filter for this user
        # Use LLM to extract moments (via REM chat completions)
        # Create Moment entities via REM repository
        # Link moments to resources via graph edges

        # Stub implementation
        lookback = lookback_hours or self.lookback_hours
        return {
            "user_id": user_id,
            "lookback_hours": lookback,
            "resources_queried": 0,
            "moments_created": 0,
            "embeddings_generated": 0,
            "graph_edges_added": 0,
            "status": "stub_not_implemented",
        }

    async def build_affinity(
        self,
        user_id: str,
        mode: AffinityMode = AffinityMode.SEMANTIC,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Build resource affinity graph.

        Creates semantic relationships between resources using either
        vector similarity (fast) or LLM analysis (intelligent).

        Semantic Mode:
        - Use vector similarity search
        - Create edges for similar resources (threshold: 0.7)
        - Fast and cheap (no LLM calls)

        LLM Mode:
        - Use LLM to assess relationship context
        - Create edges with rich metadata
        - Slow and expensive (many LLM calls)
        - ALWAYS use --limit to control costs

        Process:
        1. Query REM for recent resources for this user
        2. For each resource:
           - Semantic: Query similar resources by vector
           - LLM: Assess relationships using LLM
        3. Create graph edges via REM repository
        4. Update resource entities with affinity edges

        Args:
            user_id: User to process
            mode: Affinity mode (semantic or llm)
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max resources to process (REQUIRED for LLM mode)

        Returns:
            Statistics about affinity construction
        """
        # TODO: Implement using REM query API
        # Query resources with timestamp filter for this user
        # Semantic mode: Use REM vector search
        # LLM mode: Use REM chat completions for relationship assessment
        # Update resources with graph edges via REM repository

        # Stub implementation
        lookback = lookback_hours or self.lookback_hours
        return {
            "user_id": user_id,
            "mode": mode.value,
            "lookback_hours": lookback,
            "resources_processed": 0,
            "edges_created": 0,
            "llm_calls_made": 0 if mode == AffinityMode.LLM else None,
            "status": "stub_not_implemented",
        }

    async def extract_ontologies(
        self,
        user_id: str,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Extract domain-specific knowledge from files using custom agents.

        Finds files processed within lookback window and applies matching
        OntologyConfig rules to extract structured knowledge.

        Process:
        1. Query REM for files processed by this user (lookback window)
        2. For each file, find matching OntologyConfig rules
        3. Load agent schemas from database
        4. Execute agents on file content
        5. Generate embeddings for extracted data
        6. Store Ontology entities

        Args:
            user_id: User to process
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max files to process

        Returns:
            Statistics about ontology extraction
        """
        # TODO: Implement using REM query API + OntologyExtractorService
        # Query files with timestamp filter and processing_status='completed'
        # Load matching OntologyConfigs from database
        # Use OntologyExtractorService to extract ontologies
        # Generate embeddings for embedding_text field

        # Stub implementation
        lookback = lookback_hours or self.lookback_hours
        return {
            "user_id": user_id,
            "lookback_hours": lookback,
            "files_queried": 0,
            "configs_matched": 0,
            "ontologies_created": 0,
            "embeddings_generated": 0,
            "agent_calls_made": 0,
            "status": "stub_not_implemented",
        }

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
                results["ontologies"] = {"error": str(e)}

        # User model update
        try:
            results["user_model"] = await self.update_user_model(
                user_id=user_id,
            )
        except Exception as e:
            results["user_model"] = {"error": str(e)}

        # Moment construction
        try:
            results["moments"] = await self.construct_moments(
                user_id=user_id,
                lookback_hours=lookback,
            )
        except Exception as e:
            results["moments"] = {"error": str(e)}

        # Resource affinity
        affinity_mode = AffinityMode.LLM if use_llm_affinity else AffinityMode.SEMANTIC
        try:
            results["affinity"] = await self.build_affinity(
                user_id=user_id,
                mode=affinity_mode,
                lookback_hours=lookback,
            )
        except Exception as e:
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
