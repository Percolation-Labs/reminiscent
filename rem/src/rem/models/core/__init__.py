"""
REM Core Models

Core types and base models for the REM (Resource-Entity-Moment) system.

REM is a unified memory infrastructure that enables LLM-augmented iterated retrieval
through natural language interfaces. Unlike traditional databases that assume single-shot
queries with known schemas, REM is architected for multi-turn conversations where:

1. LLMs don't know internal IDs - they work with natural language labels
2. Information needs emerge incrementally through exploration
3. Multi-stage exploration is essential: find entity → explore neighborhood → traverse relationships

Key Design Principles:
- Graph edges reference entity LABELS (natural language), not UUIDs
- Natural language surface area for all queries
- Schema-agnostic operations (LOOKUP, FUZZY, TRAVERSE)
- O(1) performance guarantees for entity resolution
- Iterated retrieval with stage tracking and memos
"""

from .core_model import CoreModel
from .inline_edge import InlineEdge, InlineEdges
from .rem_query import (
    FuzzyParameters,
    LookupParameters,
    QueryType,
    RemQuery,
    SearchParameters,
    SQLParameters,
    TraverseParameters,
    TraverseResponse,
    TraverseStage,
)

__all__ = [
    "CoreModel",
    "InlineEdge",
    "InlineEdges",
    "QueryType",
    "LookupParameters",
    "FuzzyParameters",
    "SearchParameters",
    "SQLParameters",
    "TraverseParameters",
    "RemQuery",
    "TraverseStage",
    "TraverseResponse",
]
