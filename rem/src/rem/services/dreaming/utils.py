"""
Dreaming utilities - Common functions for dreaming services.
"""

from typing import Any


def merge_graph_edges(
    existing_edges: list[dict[str, Any]], new_edges: list[dict[str, Any]]
) -> list[dict[str, Any]]:
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
    edges_map: dict[tuple[str, str], dict[str, Any]] = {}

    # Add existing edges
    for edge in existing_edges:
        key = (edge.get("dst", ""), edge.get("rel_type", ""))
        edges_map[key] = edge

    # Add new edges (replace if higher weight)
    for edge in new_edges:
        key = (edge.get("dst", ""), edge.get("rel_type", ""))
        if key not in edges_map or edge.get("weight", 0) > edges_map[key].get(
            "weight", 0
        ):
            edges_map[key] = edge

    return list(edges_map.values())
