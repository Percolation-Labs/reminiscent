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
from loguru import logger
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

    Multi-Tenancy Note:
    - Currently assumes tenant_id is nullable and supports user_id as primary identifier
    - In single-user deployments, tenant_id can be None or same as user_id
    - In future, tenant_id will group enterprise users together (e.g., "acme-corp")
      enabling org-wide dreaming workflows and cross-user knowledge graphs
    - For now, all operations are user-scoped even when tenant_id is provided
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
        tenant_id: str,
        time_window_days: int = 30,
        max_sessions: int = 100,
        max_moments: int = 20,
        max_resources: int = 20,
    ) -> dict[str, Any]:
        """
        Update user model from recent activity.

        Reads recent sessions, moments, and resources to generate
        a comprehensive user profile summary using LLM analysis.

        Process:
        1. Query PostgreSQL for recent sessions, moments, resources for this user
        2. Load UserProfileBuilder agent schema
        3. Generate user profile using LLM
        4. Update User entity with profile data and metadata
        5. Add graph edges to key resources and moments

        Args:
            user_id: User to process
            tenant_id: Tenant ID for multi-tenancy isolation (nullable, see class docstring)
            time_window_days: Days to look back for activity (default: 30)
            max_sessions: Max sessions to analyze
            max_moments: Max moments to include
            max_resources: Max resources to include

        Returns:
            Statistics about user model update
        """
        import json
        from datetime import timezone
        from pathlib import Path

        from ..agentic.providers.pydantic_ai import create_agent
        from ..agentic.serialization import serialize_agent_result
        from ..models.entities.moment import Moment
        from ..models.entities.resource import Resource
        from ..models.entities.session import Session
        from ..models.entities.user import User
        from ..services.postgres.repository import Repository
        from ..services.postgres.service import PostgresService

        cutoff = datetime.now(timezone.utc) - timedelta(days=time_window_days)

        # Initialize database connection
        from rem.services.postgres import get_postgres_service
        db = get_postgres_service()
        await db.connect()

        try:
            # Create repositories
            session_repo = Repository(Session, "sessions", db=db)
            moment_repo = Repository(Moment, "moments", db=db)
            resource_repo = Repository(Resource, "resources", db=db)
            user_repo = Repository(User, "users", db=db)

            # Build filters (tenant_id is optional)
            filters = {"user_id": user_id}
            if tenant_id:
                filters["tenant_id"] = tenant_id

            # Query recent sessions
            sessions = await session_repo.find(
                filters=filters,
                order_by="created_at DESC",
                limit=max_sessions,
            )
            sessions = [s for s in sessions if s.created_at >= cutoff]

            # Query recent moments
            moments = await moment_repo.find(
                filters=filters,
                order_by="starts_timestamp DESC",
                limit=max_moments,
            )
            moments = [m for m in moments if m.starts_timestamp >= cutoff]

            # Query recent resources
            resources = await resource_repo.find(
                filters=filters,
                order_by="resource_timestamp DESC",
                limit=max_resources,
            )
            resources = [
                r for r in resources if r.resource_timestamp and r.resource_timestamp >= cutoff
            ]

            if not sessions and not moments and not resources:
                return {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "time_window_days": time_window_days,
                    "sessions_analyzed": 0,
                    "moments_included": 0,
                    "resources_included": 0,
                    "user_updated": False,
                    "status": "no_data",
                }

            logger.info(
                f"Building user profile for {user_id}: "
                f"{len(sessions)} sessions, {len(moments)} moments, {len(resources)} resources"
            )

            # Load UserProfileBuilder agent schema
            schema_path = (
                Path(__file__).parent.parent
                / "schemas"
                / "agents"
                / "user-profile-builder.yaml"
            )

            if not schema_path.exists():
                raise FileNotFoundError(f"UserProfileBuilder schema not found: {schema_path}")

            import yaml

            with open(schema_path) as f:
                agent_schema = yaml.safe_load(f)

            # Prepare input data for agent
            input_data = {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "time_window_days": time_window_days,
                "sessions": [
                    {
                        "id": s.id,
                        "query": s.query[:500],  # Limit for token efficiency
                        "response": s.response[:500] if s.response else "",
                        "created_at": s.created_at.isoformat(),
                        "metadata": s.metadata,
                    }
                    for s in sessions
                ],
                "moments": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "moment_type": m.moment_type,
                        "emotion_tags": m.emotion_tags,
                        "topic_tags": m.topic_tags,
                        "present_persons": [
                            {"id": p.id, "name": p.name, "role": p.role}
                            for p in m.present_persons
                        ],
                        "starts_timestamp": m.starts_timestamp.isoformat(),
                        "summary": m.summary[:300] if m.summary else "",
                    }
                    for m in moments
                ],
                "resources": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "category": r.category,
                        "content": r.content[:1000] if r.content else "",  # First 1000 chars
                        "resource_timestamp": (
                            r.resource_timestamp.isoformat() if r.resource_timestamp else None
                        ),
                    }
                    for r in resources
                ],
            }

            # Create and run UserProfileBuilder agent
            agent = await create_agent(
                agent_schema_override=agent_schema,
                model_override=self.default_model,
            )

            result = await agent.run(json.dumps(input_data, indent=2))

            # Serialize result (critical for Pydantic models!)
            profile_data = serialize_agent_result(result.output)

            logger.info(
                f"Generated user profile. Summary: {profile_data.get('summary', '')[:100]}..."
            )

            # Get or create User entity
            user = await user_repo.get_by_id(user_id, tenant_id or user_id)

            if not user:
                # Create new user
                user = User(
                    id=user_id,
                    tenant_id=tenant_id or user_id,  # Use user_id if tenant_id is None
                    user_id=user_id,
                    name=user_id,  # Default to user_id, can be updated later
                    metadata={},
                    graph_edges=[],
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

            # Update user metadata with full profile
            user.metadata = user.metadata or {}
            user.metadata.update(
                {
                    "profile": profile_data,
                    "profile_generated_at": datetime.now(timezone.utc).isoformat(),
                    "profile_time_window_days": time_window_days,
                }
            )

            # Update user model fields from profile
            user.summary = profile_data.get("summary", "")
            user.interests = [
                area for area in profile_data.get("expertise_areas", [])
            ] + [
                interest for interest in profile_data.get("learning_interests", [])
            ]
            user.preferred_topics = profile_data.get("recommended_tags", [])

            # Determine activity level based on data volume
            total_activity = len(sessions) + len(moments) + len(resources)
            if total_activity >= 50:
                user.activity_level = "active"
            elif total_activity >= 10:
                user.activity_level = "moderate"
            else:
                user.activity_level = "inactive"

            user.last_active_at = datetime.now(timezone.utc)

            # Build graph edges to key resources and moments
            graph_edges = []

            # Add edges to recent resources (top 5)
            for resource in resources[:5]:
                graph_edges.append(
                    {
                        "dst": resource.id,
                        "rel_type": "recently_worked_on",
                        "weight": 0.8,
                        "properties": {
                            "entity_type": "resource",
                            "dst_name": resource.name,
                            "dst_category": resource.category,
                        },
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Add edges to recent moments (top 5)
            for moment in moments[:5]:
                graph_edges.append(
                    {
                        "dst": moment.id,
                        "rel_type": "participated_in",
                        "weight": 0.9,
                        "properties": {
                            "entity_type": "moment",
                            "dst_name": moment.name,
                            "dst_moment_type": moment.moment_type,
                        },
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

            # Merge edges with existing
            user.graph_edges = self._merge_edges(user.graph_edges or [], graph_edges)
            user.updated_at = datetime.now(timezone.utc)

            # Save user
            await user_repo.upsert(user)

            return {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "time_window_days": time_window_days,
                "sessions_analyzed": len(sessions),
                "moments_included": len(moments),
                "resources_included": len(resources),
                "current_projects": len(profile_data.get("current_projects", [])),
                "technical_stack_size": len(profile_data.get("technical_stack", [])),
                "key_collaborators": len(profile_data.get("key_collaborators", [])),
                "graph_edges_added": len(graph_edges),
                "user_updated": True,
                "status": "success",
            }

        finally:
            await db.disconnect()

    async def construct_moments(
        self,
        user_id: str,
        tenant_id: str,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Extract moments from resources.

        Analyzes recent resources to identify temporal narratives
        (meetings, coding sessions, conversations) and creates
        Moment entities with temporal boundaries and metadata.

        Process:
        1. Query PostgreSQL for recent resources and sessions for this user
        2. Load MomentBuilder agent schema from filesystem
        3. Run agent to extract moments from data
        4. Create Moment entities via Repository
        5. Link moments to source resources via graph edges
        6. Embeddings auto-generated by embedding worker

        Args:
            user_id: User to process
            tenant_id: Tenant ID for multi-tenancy isolation
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max resources to process

        Returns:
            Statistics about moment construction
        """
        import json
        from datetime import timezone
        from pathlib import Path

        from ..agentic.providers.pydantic_ai import create_agent
        from ..agentic.serialization import serialize_agent_result
        from ..models.entities.moment import Moment
        from ..models.entities.resource import Resource
        from ..models.entities.session import Session
        from ..services.postgres.repository import Repository
        from ..services.postgres.service import PostgresService
        from ..settings import settings

        lookback = lookback_hours or self.lookback_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)

        # Initialize database connection
        from rem.services.postgres import get_postgres_service
        db = get_postgres_service()
        await db.connect()

        try:
            # Create repositories
            resource_repo = Repository(Resource, "resources", db=db)
            session_repo = Repository(Session, "sessions", db=db)
            moment_repo = Repository(Moment, "moments", db=db)

            # Query recent resources
            resources = await resource_repo.find(
                filters={
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                },
                order_by="resource_timestamp DESC",
                limit=limit,
            )

            # Filter by timestamp (SQL doesn't support comparisons in find yet)
            resources = [
                r for r in resources if r.resource_timestamp and r.resource_timestamp >= cutoff
            ]

            # Query recent sessions
            sessions = await session_repo.find(
                filters={
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                },
                order_by="created_at DESC",
                limit=limit,
            )

            # Filter by timestamp
            sessions = [s for s in sessions if s.created_at >= cutoff]

            if not resources and not sessions:
                return {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "lookback_hours": lookback,
                    "resources_queried": 0,
                    "sessions_queried": 0,
                    "moments_created": 0,
                    "graph_edges_added": 0,
                    "status": "no_data",
                }

            # Load MomentBuilder agent schema
            schema_path = (
                Path(__file__).parent.parent
                / "schemas"
                / "agents"
                / "moment-builder.yaml"
            )

            if not schema_path.exists():
                raise FileNotFoundError(f"MomentBuilder schema not found: {schema_path}")

            import yaml

            with open(schema_path) as f:
                agent_schema = yaml.safe_load(f)

            # Prepare input data for agent
            input_data = {
                "resources": [
                    {
                        "id": r.id,
                        "name": r.name,
                        "category": r.category,
                        "content": r.content,
                        "resource_timestamp": (
                            r.resource_timestamp.isoformat() if r.resource_timestamp else None
                        ),
                    }
                    for r in resources
                ],
                "sessions": [
                    {
                        "id": s.id,
                        "query": s.query,
                        "response": s.response,
                        "created_at": s.created_at.isoformat(),
                        "metadata": s.metadata,
                    }
                    for s in sessions
                ],
            }

            # Create and run MomentBuilder agent
            agent = await create_agent(
                agent_schema_override=agent_schema,
                model_override=self.default_model,
            )

            result = await agent.run(json.dumps(input_data, indent=2))

            # Serialize result (critical for Pydantic models!)
            output_data = serialize_agent_result(result.output)

            # Extract moments
            moments_data = output_data.get("moments", [])
            analysis_summary = output_data.get("analysis_summary", "")

            logger.info(
                f"MomentBuilder extracted {len(moments_data)} moments. Summary: {analysis_summary}"
            )

            # Create Moment entities
            created_moments = []
            total_edges = 0

            for moment_data in moments_data:
                # Map resource_timestamp/resource_ends_timestamp to starts_timestamp/ends_timestamp
                starts_ts_str = moment_data.get("resource_timestamp")
                ends_ts_str = moment_data.get("resource_ends_timestamp")

                if not starts_ts_str:
                    logger.warning(f"Skipping moment without start timestamp: {moment_data.get('name')}")
                    continue

                starts_ts = datetime.fromisoformat(starts_ts_str.replace("Z", "+00:00"))
                ends_ts = (
                    datetime.fromisoformat(ends_ts_str.replace("Z", "+00:00"))
                    if ends_ts_str
                    else None
                )

                # Build graph edges to source resources
                source_resource_ids = moment_data.get("source_resource_ids", [])
                source_session_ids = moment_data.get("source_session_ids", [])

                graph_edges = []

                # Add edges to source resources
                for resource_id in source_resource_ids:
                    graph_edges.append(
                        {
                            "dst": resource_id,
                            "rel_type": "extracted_from",
                            "weight": 1.0,
                            "properties": {
                                "entity_type": "resource",
                                "extraction_method": "moment_builder_agent",
                            },
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

                # Add edges to source sessions
                for session_id in source_session_ids:
                    graph_edges.append(
                        {
                            "dst": session_id,
                            "rel_type": "extracted_from",
                            "weight": 0.8,
                            "properties": {
                                "entity_type": "session",
                                "extraction_method": "moment_builder_agent",
                            },
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )

                # Create Moment entity
                moment = Moment(
                    id=str(uuid4()),
                    tenant_id=tenant_id,
                    user_id=user_id,
                    name=moment_data.get("name"),
                    moment_type=moment_data.get("moment_type"),
                    category=moment_data.get("moment_type"),  # Use moment_type as category
                    starts_timestamp=starts_ts,
                    ends_timestamp=ends_ts,
                    present_persons=[
                        {"id": p["id"], "name": p["name"], "role": p.get("comment")}
                        for p in moment_data.get("present_persons", [])
                    ],
                    emotion_tags=moment_data.get("emotion_tags", []),
                    topic_tags=moment_data.get("topic_tags", []),
                    summary=moment_data.get("content"),  # Use content as summary
                    source_resource_ids=source_resource_ids,
                    graph_edges=graph_edges,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )

                # Save to database (embeddings auto-generated by embedding worker)
                await moment_repo.upsert(moment)
                created_moments.append(moment)
                total_edges += len(graph_edges)

                logger.debug(
                    f"Created moment: {moment.name} ({moment.moment_type}) with {len(graph_edges)} edges"
                )

            return {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "lookback_hours": lookback,
                "resources_queried": len(resources),
                "sessions_queried": len(sessions),
                "moments_created": len(created_moments),
                "graph_edges_added": total_edges,
                "analysis_summary": analysis_summary,
                "status": "success",
            }

        finally:
            await db.disconnect()

    async def build_affinity(
        self,
        user_id: str,
        tenant_id: str,
        mode: AffinityMode = AffinityMode.SEMANTIC,
        lookback_hours: Optional[int] = None,
        limit: Optional[int] = None,
        similarity_threshold: float = 0.7,
        top_k: int = 3,
    ) -> dict[str, Any]:
        """
        Build resource affinity graph.

        Creates semantic relationships between resources using either
        vector similarity (fast) or LLM analysis (intelligent).

        Semantic Mode:
        - Use vector similarity search via REM SEARCH query
        - Create edges for similar resources (threshold: 0.7)
        - Fast and cheap (no LLM calls)

        LLM Mode:
        - Use LLM to assess relationship context
        - Create edges with rich metadata
        - Slow and expensive (many LLM calls)
        - ALWAYS use --limit to control costs

        Process:
        1. Query PostgreSQL for recent resources for this user
        2. For each resource:
           - Semantic: Query similar resources by vector using REM SEARCH
           - LLM: Assess relationships using ResourceAffinityAssessor agent
        3. Create graph edges with deduplication (keep highest weight)
        4. Update resource entities with affinity edges

        Args:
            user_id: User to process
            tenant_id: Tenant ID for multi-tenancy isolation
            mode: Affinity mode (semantic or llm)
            lookback_hours: Hours to look back (default: self.lookback_hours)
            limit: Max resources to process (REQUIRED for LLM mode)
            similarity_threshold: Minimum similarity score for semantic mode (default: 0.7)
            top_k: Number of similar resources to find per resource (default: 3)

        Returns:
            Statistics about affinity construction
        """
        import json
        from datetime import timezone
        from pathlib import Path

        from ..agentic.providers.pydantic_ai import create_agent
        from ..agentic.serialization import serialize_agent_result
        from ..models.core import QueryType, RemQuery, SearchParameters
        from ..models.entities.resource import Resource
        from ..services.postgres.repository import Repository
        from ..services.postgres.service import PostgresService
        from ..services.rem.service import RemService

        lookback = lookback_hours or self.lookback_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)

        # Initialize database connection
        from rem.services.postgres import get_postgres_service
        db = get_postgres_service()
        await db.connect()

        try:
            # Create repositories and REM service
            resource_repo = Repository(Resource, "resources", db=db)
            rem_service = RemService(postgres_service=db)

            # Register Resource model for REM queries
            rem_service.register_model("resources", Resource)

            # Query recent resources
            resources = await resource_repo.find(
                filters={
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                },
                order_by="resource_timestamp DESC",
                limit=limit,
            )

            # Filter by timestamp
            resources = [
                r for r in resources if r.resource_timestamp and r.resource_timestamp >= cutoff
            ]

            if not resources:
                return {
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "mode": mode.value,
                    "lookback_hours": lookback,
                    "resources_processed": 0,
                    "edges_created": 0,
                    "llm_calls_made": 0 if mode == AffinityMode.LLM else None,
                    "status": "no_data",
                }

            logger.info(
                f"Building affinity for {len(resources)} resources in {mode.value} mode"
            )

            # Statistics tracking
            resources_processed = 0
            total_edges_created = 0
            llm_calls_made = 0

            # Load LLM agent for relationship assessment if needed
            affinity_agent = None
            if mode == AffinityMode.LLM:
                schema_path = (
                    Path(__file__).parent.parent
                    / "schemas"
                    / "agents"
                    / "resource-affinity-assessor.yaml"
                )

                if not schema_path.exists():
                    raise FileNotFoundError(
                        f"ResourceAffinityAssessor schema not found: {schema_path}"
                    )

                import yaml

                with open(schema_path) as f:
                    agent_schema = yaml.safe_load(f)

                affinity_agent = await create_agent(
                    agent_schema_override=agent_schema,
                    model_override=self.default_model,
                )

            # Process each resource
            for resource in resources:
                if not resource.content:
                    logger.debug(f"Skipping resource {resource.id} - no content for embedding")
                    continue

                # Find similar resources
                similar_resources = []

                if mode == AffinityMode.SEMANTIC:
                    # Use REM SEARCH for vector similarity
                    try:
                        search_query = RemQuery(
                            query_type=QueryType.SEARCH,
                            tenant_id=tenant_id,
                            parameters=SearchParameters(
                                table="resources",
                                query_text=resource.content[:1000],  # Use first 1000 chars
                                field="content",
                                limit=top_k + 1,  # +1 to exclude self
                                threshold=similarity_threshold,
                            ),
                        )

                        search_result = await rem_service.execute_query(search_query)
                        candidates = search_result.get("results", [])

                        # Filter out self and collect similar resources
                        for candidate in candidates:
                            if candidate.get("id") != resource.id:
                                similar_resources.append(
                                    {
                                        "resource": next(
                                            (r for r in resources if r.id == candidate["id"]),
                                            None,
                                        ),
                                        "similarity_score": candidate.get("similarity", 0.0),
                                        "relationship_type": "semantic_similar",
                                        "relationship_strength": "moderate",
                                        "edge_labels": [],
                                    }
                                )

                    except Exception as e:
                        logger.warning(
                            f"Vector search failed for resource {resource.id}: {e}"
                        )
                        continue

                elif mode == AffinityMode.LLM:
                    # Use LLM to assess relationships with all other resources
                    for other_resource in resources:
                        if other_resource.id == resource.id:
                            continue

                        # Prepare input for agent
                        input_data = {
                            "resource_a": {
                                "id": resource.id,
                                "name": resource.name,
                                "category": resource.category,
                                "content": resource.content[:2000],  # Limit for token efficiency
                                "resource_timestamp": (
                                    resource.resource_timestamp.isoformat()
                                    if resource.resource_timestamp
                                    else None
                                ),
                            },
                            "resource_b": {
                                "id": other_resource.id,
                                "name": other_resource.name,
                                "category": other_resource.category,
                                "content": other_resource.content[:2000],
                                "resource_timestamp": (
                                    other_resource.resource_timestamp.isoformat()
                                    if other_resource.resource_timestamp
                                    else None
                                ),
                            },
                        }

                        # Run agent
                        result = await affinity_agent.run(json.dumps(input_data, indent=2))
                        llm_calls_made += 1

                        # Serialize result
                        assessment = serialize_agent_result(result.output)

                        # If relationship exists, add to similar resources
                        if assessment.get("relationship_exists"):
                            # Map strength to weight
                            strength_to_weight = {
                                "strong": 0.9,
                                "moderate": 0.7,
                                "weak": 0.4,
                            }
                            weight = strength_to_weight.get(
                                assessment.get("relationship_strength", "moderate"), 0.7
                            )

                            similar_resources.append(
                                {
                                    "resource": other_resource,
                                    "similarity_score": weight,
                                    "relationship_type": assessment.get(
                                        "relationship_type", "related"
                                    ),
                                    "relationship_strength": assessment.get(
                                        "relationship_strength", "moderate"
                                    ),
                                    "edge_labels": assessment.get("edge_labels", []),
                                    "reasoning": assessment.get("reasoning", ""),
                                }
                            )

                        # Limit LLM comparisons to top_k
                        if len(similar_resources) >= top_k:
                            break

                # Create graph edges for similar resources
                new_edges = []
                for similar in similar_resources[:top_k]:
                    if not similar["resource"]:
                        continue

                    # Map similarity score to weight
                    if mode == AffinityMode.SEMANTIC:
                        # Semantic mode: map similarity score directly
                        weight = min(similar["similarity_score"], 1.0)
                    else:
                        # LLM mode: use assessed weight
                        weight = similar["similarity_score"]

                    # Create InlineEdge
                    edge = {
                        "dst": similar["resource"].id,  # Use ID for now, could use name
                        "rel_type": similar["relationship_type"],
                        "weight": weight,
                        "properties": {
                            "entity_type": "resource",
                            "dst_name": similar["resource"].name,
                            "dst_category": similar["resource"].category,
                            "match_type": mode.value,
                            "similarity_score": similar["similarity_score"],
                            "relationship_strength": similar.get("relationship_strength"),
                            "edge_labels": similar.get("edge_labels", []),
                            "reasoning": similar.get("reasoning", ""),
                        },
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    new_edges.append(edge)

                # Merge with existing edges (deduplication: keep highest weight)
                existing_edges = resource.graph_edges or []
                merged_edges = self._merge_edges(existing_edges, new_edges)

                # Update resource with merged edges
                resource.graph_edges = merged_edges
                await resource_repo.upsert(resource)

                resources_processed += 1
                edges_added = len(new_edges)
                total_edges_created += edges_added

                logger.debug(
                    f"Processed resource {resource.id} ({resource.name}): "
                    f"found {len(similar_resources)} similar resources, "
                    f"added {edges_added} edges"
                )

            return {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "mode": mode.value,
                "lookback_hours": lookback,
                "resources_processed": resources_processed,
                "edges_created": total_edges_created,
                "llm_calls_made": llm_calls_made if mode == AffinityMode.LLM else None,
                "status": "success",
            }

        finally:
            await db.disconnect()

    def _merge_edges(
        self, existing_edges: list[dict], new_edges: list[dict]
    ) -> list[dict]:
        """
        Merge graph edges with deduplication.

        Keep highest weight edge for each (dst, rel_type) pair.
        This prevents duplicate edges while preserving the strongest relationships.

        Args:
            existing_edges: Current edges on the resource
            new_edges: New edges to add

        Returns:
            Merged list of edges with duplicates removed
        """
        edges_map = {}

        # Add existing edges
        for edge in existing_edges:
            key = (edge.get("dst"), edge.get("rel_type"))
            edges_map[key] = edge

        # Add new edges (replace if higher weight)
        for edge in new_edges:
            key = (edge.get("dst"), edge.get("rel_type"))
            if key not in edges_map or edge.get("weight", 0) > edges_map[key].get(
                "weight", 0
            ):
                edges_map[key] = edge

        return list(edges_map.values())

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
        tenant_id: str,
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
            tenant_id: Tenant ID for multi-tenancy isolation
            use_llm_affinity: Use LLM mode for affinity (expensive)
            lookback_hours: Hours to look back
            extract_ontologies: Whether to run ontology extraction (default: True)

        Returns:
            Aggregated statistics from all operations
        """
        lookback = lookback_hours or self.lookback_hours
        results = {
            "user_id": user_id,
            "tenant_id": tenant_id,
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
                tenant_id=tenant_id,
            )
        except Exception as e:
            logger.exception("User model update failed")
            results["user_model"] = {"error": str(e)}

        # Moment construction
        try:
            results["moments"] = await self.construct_moments(
                user_id=user_id,
                tenant_id=tenant_id,
                lookback_hours=lookback,
            )
        except Exception as e:
            logger.exception("Moment construction failed")
            results["moments"] = {"error": str(e)}

        # Resource affinity
        affinity_mode = AffinityMode.LLM if use_llm_affinity else AffinityMode.SEMANTIC
        try:
            results["affinity"] = await self.build_affinity(
                user_id=user_id,
                tenant_id=tenant_id,
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
            tenant_id="test-tenant",
            use_llm_affinity=False,
            lookback_hours=24,
        )
        print(result)
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
