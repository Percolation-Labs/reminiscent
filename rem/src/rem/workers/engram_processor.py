"""
Engram Processor for REM.

Processes engram YAML/JSON files into Resources and Moments following
the p8fs-modules engram specification.

Key Design Principles:
- Engrams ARE Resources (category="engram")
- Human-friendly labels in graph edges (not UUIDs)
- Upsert with JSON merge behavior (never overwrite)
- Dual indexing handled by repository (SQL + embeddings + KV)
- Moment attachment via part_of relationship

Processing Flow:
1. Parse YAML/JSON engram
2. Create Resource from top-level engram fields
3. Upsert Resource (triggers embeddings + KV store population)
4. Create Moments from moments array
5. Link moments to parent engram via graph edges

See: /Users/sirsh/code/p8fs-modules/p8fs/docs/04 engram-specification.md
"""

"""
Engram Processor for REM.

Processes engram YAML/JSON files into Resources and Moments following
the p8fs-modules engram specification.

Key Design Principles:
- Engrams ARE Resources (category="engram")
- Human-friendly labels in graph edges (not UUIDs)
- Upsert with JSON merge behavior (never overwrite)
- Dual indexing handled by repository (SQL + embeddings + KV)
- Moment attachment via part_of relationship

Processing Flow:
1. Parse YAML/JSON engram
2. Create Resource from top-level engram fields
3. Upsert Resource (triggers embeddings + KV store population)
4. Create Moments from moments array
5. Link moments to parent engram via graph edges

See: /Users/sirsh/code/p8fs-modules/p8fs/docs/04 engram-specification.md
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast # Added cast

import yaml

from rem.models.core import InlineEdge
from rem.models.entities import Moment, Resource
from rem.services.postgres import PostgresService

logger = logging.getLogger(__name__)


class EngramProcessor:
    """
    Process engram files into REM Resources and Moments.

    Example usage:
        processor = EngramProcessor(postgres_service)
        result = await processor.process_file(
            file_path="/path/to/engram.yaml",
            tenant_id="acme-corp",
            user_id="sarah-chen"
        )
    """

    def __init__(self, postgres_service: PostgresService):
        """
        Initialize engram processor.

        Args:
            postgres_service: PostgreSQL service for upsert operations
        """
        self.postgres = postgres_service

    async def process_file(
        self,
        file_path: Path | str,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Process an engram file (YAML or JSON).

        Args:
            file_path: Path to engram file
            tenant_id: Tenant ID for multi-tenancy
            user_id: Optional user ID (owner)

        Returns:
            Result dict with resource_id, moment_ids, chunks_created, etc.
        """
        file_path = Path(file_path)

        # Parse file
        with open(file_path) as f:
            if file_path.suffix in (".yaml", ".yml"):
                data = yaml.safe_load(f)
            elif file_path.suffix == ".json":
                import json

                data = json.load(f)
            else:
                raise ValueError(f"Unsupported file format: {file_path.suffix}")

        return await self.process_engram(data, tenant_id, user_id)

    async def process_engram(
        self,
        data: dict[str, Any],
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Process engram data into REM entities.

        Args:
            data: Parsed engram data (dict from YAML/JSON)
            tenant_id: Tenant ID
            user_id: Optional user ID

        Returns:
            Result dict with resource_id, moment_ids, chunks_created, etc.
        """
        # Validate kind
        if data.get("kind") != "engram":
            raise ValueError(f"Expected kind='engram', got: {data.get('kind')}")

        # Extract top-level engram fields
        name = data["name"]
        category = data.get("category", "engram")
        summary = data.get("summary")
        content = data.get("content", "")
        uri = data.get("uri")
        resource_timestamp = data.get("resource_timestamp")
        if resource_timestamp:
            resource_timestamp = datetime.fromisoformat(resource_timestamp)
        else:
            resource_timestamp = datetime.utcnow()

        metadata = data.get("metadata", {})
        graph_edges_data = data.get("graph_edges", [])
        moments_data = data.get("moments", [])

        # Convert graph edges to InlineEdge objects
        graph_edges = []
        for edge_data in graph_edges_data:
            edge = InlineEdge(
                dst=edge_data["dst"],
                rel_type=edge_data["rel_type"],
                weight=edge_data.get("weight", 0.5),
                properties=edge_data.get("properties", {}),
            )
            graph_edges.append(edge)

        # Create Resource (engram)
        resource = Resource(
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            category=category,
            uri=uri,
            content=content,
            timestamp=resource_timestamp,
            metadata=metadata,
            graph_edges=[edge.model_dump() for edge in graph_edges],
        )

        # Upsert resource (triggers embeddings + KV store population)
        logger.info(f"Upserting engram resource: {name}")
        upsert_result = await self.postgres.batch_upsert(
            records=[resource.model_dump(mode="json")],
            model=Resource,
            table_name="resources",
            entity_key_field="name",  # Explicit entity_key for KV store
        )
        resource_id = upsert_result["ids"][0]
        logger.info(f"Upserted resource: {resource_id}")

        # Process attached moments
        moment_ids = []
        if moments_data:
            logger.info(f"Processing {len(moments_data)} moments for engram: {name}")
            moment_ids = await self._process_moments(
                moments_data=moments_data,
                parent_resource_name=name,
                parent_resource_id=resource_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )

        return {
            "resource_id": resource_id,
            "moment_ids": moment_ids,
            "chunks_created": 1 + len(moment_ids),  # Resource + moments
            "embeddings_generated": 0,  # Handled by embedding worker
        }

    async def _process_moments(
        self,
        moments_data: list[dict],
        parent_resource_name: str,
        parent_resource_id: str,
        tenant_id: str,
        user_id: Optional[str] = None,
    ) -> list[str]:
        """
        Create Moments from moments array in engram.

        Args:
            moments_data: List of moment dicts from engram
            parent_resource_name: Parent engram name
            parent_resource_id: Parent engram resource ID
            tenant_id: Tenant ID
            user_id: Optional user ID

        Returns:
            List of moment IDs
        """
        moments = []
        for moment_data in moments_data:
            # Extract moment fields
            name = moment_data["name"]
            content = moment_data["content"]
            summary = moment_data.get("summary")
            moment_type = moment_data.get("moment_type")
            category = moment_data.get("category")
            uri = moment_data.get("uri")

            # Parse timestamps
            starts_timestamp = moment_data.get("starts_timestamp") or moment_data.get("resource_timestamp")
            if starts_timestamp:
                if isinstance(starts_timestamp, str):
                    starts_timestamp = datetime.fromisoformat(starts_timestamp)
            else:
                starts_timestamp = datetime.utcnow()

            ends_timestamp = moment_data.get("ends_timestamp") or moment_data.get("resource_ends_timestamp")
            if ends_timestamp and isinstance(ends_timestamp, str):
                ends_timestamp = datetime.fromisoformat(ends_timestamp)

            emotion_tags = moment_data.get("emotion_tags", [])
            topic_tags = moment_data.get("topic_tags", [])
            present_persons_data = moment_data.get("present_persons", [])
            metadata = moment_data.get("metadata", {})
            graph_edges_data = moment_data.get("graph_edges", [])

            # Create link to parent engram
            parent_edge = InlineEdge(
                dst=parent_resource_name,
                rel_type="part_of",
                weight=1.0,
                properties={
                    "dst_name": parent_resource_name,
                    "dst_id": parent_resource_id,
                    "dst_entity_type": "resource/engram",
                    "match_type": "parent_child",
                    "confidence": 1.0,
                },
            )

            # Combine moment edges with parent edge
            all_edges = [parent_edge]
            for edge_data in graph_edges_data:
                edge = InlineEdge(
                    dst=edge_data["dst"],
                    rel_type=edge_data["rel_type"],
                    weight=edge_data.get("weight", 0.5),
                    properties=edge_data.get("properties", {}),
                )
                all_edges.append(edge)

            # Create Moment entity
            moment = Moment(
                tenant_id=tenant_id,
                user_id=user_id,
                name=name,
                moment_type=moment_type,
                category=category,
                starts_timestamp=starts_timestamp,
                ends_timestamp=ends_timestamp,
                present_persons=present_persons_data,  # Will be validated by Pydantic
                emotion_tags=emotion_tags,
                topic_tags=topic_tags,
                summary=summary or content[:200],  # Fallback to content prefix
                source_resource_ids=[parent_resource_id],
                metadata=metadata,
                graph_edges=[edge.model_dump() for edge in all_edges],
            )
            moments.append(moment)

        # Batch upsert all moments
        if moments:
            logger.info(f"Batch upserting {len(moments)} moments")
            upsert_result = await self.postgres.batch_upsert(
                records=[m.model_dump(mode="json") for m in moments],
                model=Moment,
                table_name="moments",
                entity_key_field="name",  # Explicit entity_key for KV store
            )
            moment_ids = upsert_result["ids"]
            logger.info(f"Upserted {len(moment_ids)} moments")
            return moment_ids

        return []
