"""
User Model Service - Updates user profiles from activity.

Analyzes recent sessions, moments, and resources to generate
comprehensive user profile summaries using LLM analysis.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger

from ...agentic.providers.pydantic_ai import create_agent
from ...agentic.serialization import serialize_agent_result
from ...models.entities.moment import Moment
from ...models.entities.resource import Resource
from ...models.entities.session import Session
from ...models.entities.user import User
from ...services.postgres.repository import Repository
from ...services.postgres.service import PostgresService


async def update_user_model(
    user_id: str,
    db: PostgresService,
    default_model: str = "gpt-4o",
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
        db: Database service (already connected)
        default_model: LLM model for analysis (default: gpt-4o)
        time_window_days: Days to look back for activity (default: 30)
        max_sessions: Max sessions to analyze
        max_moments: Max moments to include
        max_resources: Max resources to include

    Returns:
        Statistics about user model update
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=time_window_days)

    # Create repositories
    session_repo = Repository(Session, "sessions", db=db)
    moment_repo = Repository(Moment, "moments", db=db)
    resource_repo = Repository(Resource, "resources", db=db)
    user_repo = Repository(User, "users", db=db)

    # Build filters using user_id
    filters = {"user_id": user_id}

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
        Path(__file__).parent.parent.parent
        / "schemas"
        / "agents"
        / "user-profile-builder.yaml"
    )

    if not schema_path.exists():
        raise FileNotFoundError(f"UserProfileBuilder schema not found: {schema_path}")

    with open(schema_path) as f:
        agent_schema = yaml.safe_load(f)

    # Prepare input data for agent
    input_data = {
        "user_id": user_id,
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
        model_override=default_model,
    )

    result = await agent.run(json.dumps(input_data, indent=2))

    # Serialize result (critical for Pydantic models!)
    profile_data = serialize_agent_result(result.output)

    logger.info(
        f"Generated user profile. Summary: {profile_data.get('summary', '')[:100]}..."
    )

    # Get or create User entity
    user = await user_repo.get_by_id(user_id, user_id)

    if not user:
        # Create new user
        user = User(
            id=user_id,
            tenant_id=user_id,  # Set tenant_id = user_id
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
    from .utils import merge_graph_edges

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
    user.graph_edges = merge_graph_edges(user.graph_edges or [], graph_edges)
    user.updated_at = datetime.now(timezone.utc)

    # Save user
    await user_repo.upsert(user)

    return {
        "user_id": user_id,
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
