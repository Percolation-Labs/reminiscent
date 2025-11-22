"""
Affinity Service - Builds resource relationship graph.

Creates semantic relationships between resources using either
vector similarity (fast) or LLM analysis (intelligent).
"""

import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from loguru import logger

from ...agentic.providers.pydantic_ai import create_agent
from ...agentic.serialization import serialize_agent_result
from ...models.core import QueryType, RemQuery, SearchParameters
from ...models.entities.resource import Resource
from ...services.postgres.repository import Repository
from ...services.postgres.service import PostgresService
from ...services.rem.service import RemService
from .utils import merge_graph_edges


class AffinityMode(str, Enum):
    """Resource affinity modes."""

    SEMANTIC = "semantic"  # Fast vector similarity
    LLM = "llm"  # Intelligent LLM-based assessment


async def build_affinity(
    user_id: str,
    db: PostgresService,
    mode: AffinityMode = AffinityMode.SEMANTIC,
    default_model: str = "gpt-4o",
    lookback_hours: int = 24,
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
        db: Database service (already connected)
        mode: Affinity mode (semantic or llm)
        default_model: LLM model for analysis (default: gpt-4o)
        lookback_hours: Hours to look back (default: 24)
        limit: Max resources to process (REQUIRED for LLM mode)
        similarity_threshold: Minimum similarity score for semantic mode (default: 0.7)
        top_k: Number of similar resources to find per resource (default: 3)

    Returns:
        Statistics about affinity construction
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    # Create repositories and REM service
    resource_repo = Repository(Resource, "resources", db=db)
    rem_service = RemService(postgres_service=db)

    # Register Resource model for REM queries
    rem_service.register_model("resources", Resource)

    # Query recent resources
    resources = await resource_repo.find(
        filters={
            "user_id": user_id,
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
            "mode": mode.value,
            "lookback_hours": lookback_hours,
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
            Path(__file__).parent.parent.parent
            / "schemas"
            / "agents"
            / "resource-affinity-assessor.yaml"
        )

        if not schema_path.exists():
            raise FileNotFoundError(
                f"ResourceAffinityAssessor schema not found: {schema_path}"
            )

        with open(schema_path) as f:
            agent_schema = yaml.safe_load(f)

        affinity_agent = await create_agent(
            agent_schema_override=agent_schema,
            model_override=default_model,
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
                    user_id=user_id,
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
        merged_edges = merge_graph_edges(existing_edges, new_edges)

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
        "mode": mode.value,
        "lookback_hours": lookback_hours,
        "resources_processed": resources_processed,
        "edges_created": total_edges_created,
        "llm_calls_made": llm_calls_made if mode == AffinityMode.LLM else None,
        "status": "success",
    }
