"""
Sample data loader for dreaming integration tests.

Creates realistic Resources and Sessions representing a technical team's
work over several days. This data provides meaningful scenarios for testing
moment extraction, resource affinity, and knowledge graph building.

Scenarios covered:
1. Technical discussions (API design, database migration)
2. Team meetings (standups, planning)
3. Personal reflections (quarterly reviews)
4. Incident response (postmortems)

Usage:
    from rem.tests.integration.sample_data.dreaming.load_sample_data import SampleDataLoader

    async with SampleDataLoader(tenant_id="test-tenant", user_id="sarah-chen") as loader:
        summary = await loader.load_all()
        print(summary)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from rem.models.entities.resource import Resource
from rem.models.entities.message import Message
from rem.services.postgres import PostgresService
# TODO: Repositories module doesn't exist - needs refactoring
# from rem.services.repositories.resource_repository import ResourceRepository
# from rem.services.repositories.message_repository import MessageRepository
from rem.settings import settings


class SampleDataLoader:
    """Loads sample data for dreaming integration tests."""

    def __init__(
        self,
        tenant_id: str = "test-tenant-dreaming",
        user_id: str = "sarah-chen",
    ):
        """
        Initialize sample data loader.

        Args:
            tenant_id: Tenant ID for isolation
            user_id: User ID for all created entities
        """
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.base_dir = Path(__file__).parent / "resources"

        # Initialize services
        self.db_service = PostgresService()
        # TODO: Uncomment when repositories module exists
        # self.resource_repo: ResourceRepository | None = None
        # self.message_repo: MessageRepository | None = None
        self.resource_repo: Any | None = None
        self.message_repo: Any | None = None

        # Track created entities
        self.created_resources: list[Resource] = []
        self.created_messages: list[Message] = []

    async def __aenter__(self):
        """Async context manager entry."""
        await self.db_service.__aenter__()
        self.resource_repo = ResourceRepository(self.db_service)
        self.message_repo = MessageRepository(self.db_service)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.db_service.__aexit__(exc_type, exc_val, exc_tb)

    async def load_resource_from_file(
        self,
        filename: str,
        category: str,
        timestamp: datetime,
        graph_paths: list[dict[str, Any]] | None = None,
    ) -> Resource:
        """
        Load resource from markdown file.

        Args:
            filename: Filename in resources/ directory
            category: Resource category (documentation, meeting, reflection, etc.)
            timestamp: Resource timestamp
            graph_paths: Optional initial graph edges (InlineEdge dicts)

        Returns:
            Created Resource entity
        """
        file_path = self.base_dir / filename
        content = file_path.read_text()

        # Extract title from first heading
        lines = content.split("\n")
        name = "Untitled"
        for line in lines:
            if line.startswith("# "):
                name = line[2:].strip()
                break

        resource = Resource(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            name=name,
            category=category,
            content=content,
            graph_paths=graph_paths or [],
            resource_timestamp=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )

        await self.resource_repo.put(resource)
        self.created_resources.append(resource)
        return resource

    async def create_session(
        self,
        query: str,
        response: str,
        timestamp: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """
        Create a message entity.

        Args:
            query: User query/message
            response: Assistant response
            timestamp: Message timestamp
            metadata: Optional message metadata

        Returns:
            Created Message entity
        """
        message = Message(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            role="user",
            content=query,
            metadata=metadata or {},
            created_at=timestamp,
            updated_at=timestamp,
        )

        await self.message_repo.put(message)
        self.created_messages.append(message)
        return message

    async def load_all(self) -> dict[str, Any]:
        """
        Load all sample data.

        Creates a realistic 5-day timeline of work activity:
        - Day 1 (Jan 14): Database migration planning
        - Day 2 (Jan 15): API design discussion
        - Day 3 (Jan 16): Team standup
        - Day 4 (Jan 12): Production incident (earlier for context)
        - Day 5 (Jan 5): Quarterly reflection

        Returns:
            Summary statistics of loaded data
        """
        now = datetime.now(timezone.utc)

        # Timeline: Create data over 5-day period
        day_1 = now - timedelta(days=8)  # Jan 14 (oldest recent work)
        day_2 = now - timedelta(days=7)  # Jan 15
        day_3 = now - timedelta(days=6)  # Jan 16
        day_incident = now - timedelta(days=10)  # Jan 12 (incident)
        day_reflection = now - timedelta(days=17)  # Jan 5 (reflection)

        # Resource 1: Database Migration Plan (Jan 14)
        # Initial graph paths: mentions TiDB (technology), references EKS (project)
        db_migration = await self.load_resource_from_file(
            filename="database_migration_plan.md",
            category="documentation",
            timestamp=day_1,
            graph_paths=[
                {
                    "dst": "tidb-technology",
                    "rel_type": "mentions",
                    "weight": 1.0,
                    "properties": {
                        "entity_type": "technology",
                        "context": "primary topic",
                    },
                    "created_at": day_1.isoformat(),
                },
                {
                    "dst": "eks-cluster",
                    "rel_type": "references",
                    "weight": 0.8,
                    "properties": {
                        "entity_type": "infrastructure",
                        "context": "deployment target",
                    },
                    "created_at": day_1.isoformat(),
                },
            ],
        )

        # Session 1: Query about database migration (Jan 14 afternoon)
        await self.create_session(
            query="What are the key risks in migrating from PostgreSQL to TiDB?",
            response="Based on my analysis, the key risks are: 1) SQL compatibility gaps (array types, some advanced features), 2) Performance characteristics differ for distributed vs single-node, 3) Team learning curve for distributed database operations, 4) Data migration complexity for large tables. Mitigation: phased approach with POC, pilot, and gradual rollout.",
            timestamp=day_1 + timedelta(hours=6),
            metadata={
                "context": "database_migration_planning",
                "related_resource_id": db_migration.id,
            },
        )

        # Resource 2: API Design Discussion (Jan 15 morning)
        # Graph paths: mentions GraphQL (technology), references team members
        api_design = await self.load_resource_from_file(
            filename="api_design_discussion.md",
            category="meeting",
            timestamp=day_2 + timedelta(hours=9),
            graph_paths=[
                {
                    "dst": "graphql-technology",
                    "rel_type": "mentions",
                    "weight": 1.0,
                    "properties": {
                        "entity_type": "technology",
                        "decision": "adopted",
                    },
                    "created_at": (day_2 + timedelta(hours=9)).isoformat(),
                },
                {
                    "dst": "mike-rodriguez",
                    "rel_type": "participant",
                    "weight": 0.9,
                    "properties": {
                        "entity_type": "person",
                        "role": "backend_engineer",
                    },
                    "created_at": (day_2 + timedelta(hours=9)).isoformat(),
                },
                {
                    "dst": "alice-wong",
                    "rel_type": "participant",
                    "weight": 0.9,
                    "properties": {
                        "entity_type": "person",
                        "role": "frontend_engineer",
                    },
                    "created_at": (day_2 + timedelta(hours=9)).isoformat(),
                },
            ],
        )

        # Session 2: Follow-up on API design (Jan 15 afternoon)
        await self.create_session(
            query="How does GraphQL schema stitching work for microservices?",
            response="Schema stitching combines multiple GraphQL schemas into a unified API. Each microservice exposes its own schema, and a gateway layer merges them. Apollo Federation is the modern approach - services define their schema with @key directives, and the gateway composes them automatically. Benefits: type safety, single endpoint, independent service deployment.",
            timestamp=day_2 + timedelta(hours=14),
            metadata={
                "context": "api_design_research",
                "related_resource_id": api_design.id,
            },
        )

        # Resource 3: Team Standup (Jan 16 morning)
        # Graph paths: mentions multiple team members, references projects
        standup = await self.load_resource_from_file(
            filename="morning_standup_notes.md",
            category="meeting",
            timestamp=day_3 + timedelta(hours=9, minutes=30),
            graph_paths=[
                {
                    "dst": "graphql-project",
                    "rel_type": "discusses",
                    "weight": 0.9,
                    "properties": {
                        "entity_type": "project",
                        "status": "in_progress",
                    },
                    "created_at": (day_3 + timedelta(hours=9, minutes=30)).isoformat(),
                },
                {
                    "dst": "tidb-migration-project",
                    "rel_type": "discusses",
                    "weight": 0.9,
                    "properties": {
                        "entity_type": "project",
                        "status": "planning",
                    },
                    "created_at": (day_3 + timedelta(hours=9, minutes=30)).isoformat(),
                },
            ],
        )

        # Session 3: Standup action item (Jan 16 afternoon)
        await self.create_session(
            query="What should I include in the TiDB presentation for leadership?",
            response="Focus on: 1) Business impact (30% cost reduction, unlimited scaling), 2) Risk mitigation (phased approach, rollback plan), 3) Timeline (14 weeks total), 4) Success metrics (latency, cost, uptime). Include comparison table: PostgreSQL RDS vs TiDB on EKS. Address likely questions: MySQL vs PostgreSQL compatibility, team training needs, vendor lock-in.",
            timestamp=day_3 + timedelta(hours=13),
            metadata={
                "context": "presentation_prep",
                "related_resource_id": db_migration.id,
            },
        )

        # Resource 4: Production Incident Postmortem (Jan 12)
        # Earlier than other resources but provides important context
        incident = await self.load_resource_from_file(
            filename="production_incident_postmortem.md",
            category="incident",
            timestamp=day_incident,
            graph_paths=[
                {
                    "dst": "authentication-service",
                    "rel_type": "affected_component",
                    "weight": 1.0,
                    "properties": {
                        "entity_type": "service",
                        "severity": "p1",
                    },
                    "created_at": day_incident.isoformat(),
                },
                {
                    "dst": "alice-wong",
                    "rel_type": "author",
                    "weight": 0.7,
                    "properties": {
                        "entity_type": "person",
                        "context": "code_author",
                    },
                    "created_at": day_incident.isoformat(),
                },
            ],
        )

        # Session 4: Learning from incident (Jan 12 evening)
        await self.create_session(
            query="How can we prevent memory leaks in Node.js middleware?",
            response="Key strategies: 1) Avoid creating new objects in request handlers (move to module scope), 2) Use memory profiling tools (clinic.js, heap snapshots), 3) Set up memory alerts (gradual growth pattern), 4) Add automated checks in CI (memory leak detection), 5) Code review checklist for resource management. For middleware specifically: ensure cleanup in finally blocks, avoid closures that capture request objects.",
            timestamp=day_incident + timedelta(hours=18),
            metadata={
                "context": "incident_learning",
                "related_resource_id": incident.id,
            },
        )

        # Resource 5: Quarterly Reflection (Jan 5)
        # Personal reflection - important for user model updates
        reflection = await self.load_resource_from_file(
            filename="quarterly_reflection.md",
            category="reflection",
            timestamp=day_reflection,
            graph_paths=[
                {
                    "dst": "sarah-chen",
                    "rel_type": "authored_by",
                    "weight": 1.0,
                    "properties": {
                        "entity_type": "person",
                        "type": "self_reflection",
                    },
                    "created_at": day_reflection.isoformat(),
                },
                {
                    "dst": "q4-2024-period",
                    "rel_type": "reflects_on",
                    "weight": 1.0,
                    "properties": {
                        "entity_type": "time_period",
                        "quarter": "Q4",
                        "year": 2024,
                    },
                    "created_at": day_reflection.isoformat(),
                },
            ],
        )

        # Session 5: Goal setting (Jan 5 evening)
        await self.create_session(
            query="Help me break down the Q1 goal: 'API Modernization - GraphQL migration'",
            response="Breaking down into phases:\n\nPhase 1 - Foundation (Weeks 1-2):\n- Set up Apollo Server and Client\n- Define core schema (Customer, Order domains)\n- Create type generation pipeline\n\nPhase 2 - Migration (Weeks 3-6):\n- Migrate 3 highest-traffic endpoints\n- Dual-write pattern for data consistency\n- A/B test performance\n\nPhase 3 - Expansion (Weeks 7-10):\n- Migrate remaining endpoints\n- Deprecate old REST endpoints\n- Documentation and team training\n\nSuccess metrics: 50% reduction in API calls, <200ms p95 latency, zero data consistency issues.",
            timestamp=day_reflection + timedelta(hours=19),
            metadata={
                "context": "goal_planning",
                "related_resource_id": reflection.id,
            },
        )

        return {
            "total_resources": len(self.created_resources),
            "total_messages": len(self.created_messages),
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "date_range": {
                "earliest": day_reflection.isoformat(),
                "latest": day_3.isoformat(),
                "span_days": 17,
            },
            "resource_categories": {
                "documentation": 1,
                "meeting": 2,
                "incident": 1,
                "reflection": 1,
            },
            "graph_edges_created": sum(
                len(r.graph_paths or []) for r in self.created_resources
            ),
        }

    async def cleanup(self) -> dict[str, Any]:
        """
        Delete all created test data.

        Returns:
            Cleanup statistics
        """
        resources_deleted = 0
        sessions_deleted = 0

        # Delete sessions
        for session in self.created_sessions:
            await self.session_repo.delete(session.id, self.tenant_id)
            sessions_deleted += 1

        # Delete resources
        for resource in self.created_resources:
            await self.resource_repo.delete(resource.id, self.tenant_id)
            resources_deleted += 1

        # Clear tracking
        self.created_resources.clear()
        self.created_sessions.clear()

        return {
            "resources_deleted": resources_deleted,
            "sessions_deleted": sessions_deleted,
        }


async def main():
    """Example usage."""
    async with SampleDataLoader() as loader:
        print("Loading sample data for dreaming tests...")
        summary = await loader.load_all()

        print("\nSample data loaded successfully!")
        print(f"Resources created: {summary['total_resources']}")
        print(f"Messages created: {summary['total_messages']}")
        print(f"Graph edges: {summary['graph_edges_created']}")
        print(f"Date range: {summary['date_range']['span_days']} days")
        print(f"\nCategories: {summary['resource_categories']}")

        # Cleanup option
        # cleanup_summary = await loader.cleanup()
        # print(f"\nCleaned up: {cleanup_summary}")


if __name__ == "__main__":
    asyncio.run(main())
