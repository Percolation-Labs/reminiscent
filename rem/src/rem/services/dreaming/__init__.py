"""
Dreaming Services - REM memory indexing and insight extraction.

This module provides services for building the REM knowledge graph through:
- User model updates: Extract and update user profiles from activity
- Moment construction: Identify temporal narratives from resources
- Resource affinity: Build semantic relationships between resources
- Ontology extraction: Extract domain-specific structured knowledge from files

Each service is designed to be used independently or composed together
in the DreamingWorker orchestrator for complete memory indexing workflows.

Usage:
    from rem.services.dreaming import (
        update_user_model,
        construct_moments,
        build_affinity,
        extract_ontologies,
        AffinityMode,
    )

    # Update user model from recent activity
    result = await update_user_model(user_id="user-123", db=db)

    # Extract moments from resources
    result = await construct_moments(user_id="user-123", db=db, lookback_hours=24)

    # Build resource affinity (semantic mode)
    result = await build_affinity(
        user_id="user-123",
        db=db,
        mode=AffinityMode.SEMANTIC,
        lookback_hours=168,
    )

    # Extract ontologies (stub - not yet implemented)
    result = await extract_ontologies(user_id="user-123", lookback_hours=24)
"""

from .affinity_service import AffinityMode, build_affinity
from .moment_service import construct_moments
from .ontology_service import extract_ontologies
from .user_model_service import update_user_model
from .utils import merge_graph_edges

__all__ = [
    "update_user_model",
    "construct_moments",
    "build_affinity",
    "extract_ontologies",
    "AffinityMode",
    "merge_graph_edges",
]
