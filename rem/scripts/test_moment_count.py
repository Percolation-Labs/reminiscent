#!/usr/bin/env python
"""Quick test to verify moment builder creates fewer, richer moments."""
import asyncio
import uuid
from rem.agentic.agents import run_moment_builder
from rem.services.postgres import get_postgres_service


async def test():
    db = get_postgres_service()
    await db.connect()

    user_id = str(uuid.uuid4())
    session_id = f'manual-test-{uuid.uuid4().hex[:8]}'

    try:
        # Create test session
        await db.fetch(
            """
            INSERT INTO sessions (id, tenant_id, user_id, name, message_count, created_at, updated_at)
            VALUES (gen_random_uuid(), $1, $1, $2, 10, NOW(), NOW())
            """,
            user_id, session_id
        )

        # Create test messages (8 messages covering multiple topics)
        messages = [
            ('user', 'What is REM and how does it work?'),
            ('assistant', 'REM is a bio-inspired memory system for AI agents. It provides multi-index organization with vector embeddings, knowledge graphs, and temporal indexing.'),
            ('user', 'How do LOOKUP queries work?'),
            ('assistant', 'LOOKUP provides O(1) entity retrieval by label. Just use: LOOKUP "entity-name" and it returns all entities with that name across tables.'),
            ('user', 'What about vector search?'),
            ('assistant', 'Vector search uses embeddings for semantic similarity. Use: SEARCH "your query" LIMIT 10. It finds conceptually similar content.'),
            ('user', 'Can you explain graph traversal?'),
            ('assistant', 'TRAVERSE navigates relationships between entities. Example: TRAVERSE manages FROM "Sarah" DEPTH 2 returns Sarah and her team hierarchy.'),
        ]

        for i, (role, content) in enumerate(messages):
            await db.fetch(
                """
                INSERT INTO messages (id, tenant_id, user_id, session_id, message_type, content, created_at, updated_at)
                VALUES (gen_random_uuid(), $1, $1, $2, $3, $4, NOW() + ($5 || ' minutes')::interval, NOW())
                """,
                user_id, session_id, role, content, str(i)
            )

        print(f"Created {len(messages)} test messages")

        # Run moment builder
        result = await run_moment_builder(session_id=session_id, user_id=user_id, force=True)
        print(f"\n✅ Result: {result.moments_created} moments created, partition={result.partition_event_inserted}")

        # Reconnect and check moments
        await db.connect()
        moments = await db.fetch(
            "SELECT name, summary, topic_tags FROM moments WHERE user_id = $1 ORDER BY created_at",
            user_id
        )

        print(f"\n📝 Moments in DB: {len(moments)}")
        for m in moments:
            print(f"\n  Name: {m['name']}")
            print(f"  Summary: {m['summary'][:150]}...")
            print(f"  Topics: {m['topic_tags']}")

    finally:
        # Cleanup
        await db.connect()
        await db.fetch("DELETE FROM moments WHERE user_id = $1", user_id)
        await db.fetch("DELETE FROM messages WHERE user_id = $1", user_id)
        await db.fetch("DELETE FROM sessions WHERE user_id = $1", user_id)
        print("\n🧹 Cleaned up test data")


if __name__ == "__main__":
    asyncio.run(test())
