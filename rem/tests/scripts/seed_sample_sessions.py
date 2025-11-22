"""Seed database with sample conversation sessions for testing.

This script creates realistic conversation data in the database for manual testing
of session management, compression, and LOOKUP features.

Usage:
    python -m rem.tests.scripts.seed_sample_sessions --tenant-id test-acme
    python -m rem.tests.scripts.seed_sample_sessions --all  # Creates multiple scenarios
"""

import argparse
import asyncio
import uuid
from datetime import datetime

from loguru import logger

from rem.services.postgres import get_postgres_service
from rem.services.session import SessionMessageStore
from rem.settings import settings
from rem.tests.fixtures import ALL_SAMPLE_CONVERSATIONS


async def seed_conversation(
    tenant_id: str, session_id: str, user_id: str, conversation: list[dict]
):
    """
    Seed a single conversation into the database.

    Args:
        tenant_id: Tenant identifier
        session_id: Session identifier
        user_id: User identifier
        conversation: List of message dicts
    """
    if not settings.postgres.enabled:
        logger.error("Postgres is disabled. Cannot seed data.")
        return

    db = get_postgres_service()
    store = SessionMessageStore(db=db, user_id=tenant_id)

    # Store conversation with compression
    compressed = await store.store_session_messages(
        session_id=session_id,
        messages=conversation,
        user_id=user_id,
        compress=True,
    )

    logger.info(
        f"Seeded {len(conversation)} messages to session {session_id} "
        f"(compressed: {sum(1 for m in compressed if m.get('_compressed', False))} messages)"
    )

    # Print compression stats
    for idx, msg in enumerate(compressed):
        if msg.get("_compressed"):
            entity_key = msg.get("_entity_key")
            original_len = msg.get("_original_length", 0)
            compressed_len = len(msg.get("content", ""))
            logger.debug(
                f"  Message {idx}: compressed from {original_len} to {compressed_len} chars "
                f"(LOOKUP key: {entity_key})"
            )


async def seed_all_samples(tenant_id: str):
    """
    Seed all sample conversations with unique session IDs.

    Args:
        tenant_id: Tenant identifier for all sessions
    """
    user_id = f"demo-user-{uuid.uuid4().hex[:8]}"

    logger.info(f"Seeding all sample conversations for tenant: {tenant_id}")
    logger.info(f"Demo user ID: {user_id}")

    session_ids = {}

    for name, conversation in ALL_SAMPLE_CONVERSATIONS.items():
        session_id = f"demo-{name}-{uuid.uuid4()}"
        session_ids[name] = session_id

        logger.info(f"Seeding conversation: {name}")
        await seed_conversation(
            tenant_id=tenant_id,
            session_id=session_id,
            user_id=user_id,
            conversation=conversation,
        )

    logger.info("=" * 60)
    logger.info("Seeding complete! Session IDs:")
    logger.info("=" * 60)
    for name, session_id in session_ids.items():
        logger.info(f"  {name}: {session_id}")
    logger.info("=" * 60)
    logger.info(f"Tenant ID: {tenant_id}")
    logger.info(f"User ID: {user_id}")
    logger.info("=" * 60)
    logger.info("\nTo test session reloading, use these headers:")
    logger.info(f"  X-Tenant-Id: {tenant_id}")
    logger.info(f"  X-User-Id: {user_id}")
    logger.info(f"  X-Session-Id: <one of the session IDs above>")
    logger.info("\nExample CURL command:")
    logger.info(
        f"""
curl -X POST http://localhost:8000/api/v1/chat/completions \\
  -H "X-Tenant-Id: {tenant_id}" \\
  -H "X-User-Id: {user_id}" \\
  -H "X-Session-Id: {session_ids.get('rem_intro', 'session-id')}" \\
  -H "Content-Type: application/json" \\
  -d '{{
    "model": "openai:gpt-4o-mini",
    "messages": [{{"role": "user", "content": "What did we discuss?"}}],
    "stream": false
  }}'
    """
    )


async def demonstrate_lookup_retrieval(tenant_id: str, session_id: str):
    """
    Demonstrate REM LOOKUP feature for retrieving compressed messages.

    Args:
        tenant_id: Tenant identifier
        session_id: Session identifier containing compressed messages
    """
    if not settings.postgres.enabled:
        logger.error("Postgres is disabled. Cannot demonstrate LOOKUP.")
        return

    db = get_postgres_service()
    store = SessionMessageStore(db=db, user_id=tenant_id)

    logger.info(f"Demonstrating LOOKUP retrieval for session: {session_id}")

    # Load messages (compressed)
    messages = await store.load_session_messages(
        session_id=session_id, decompress=False
    )

    logger.info(f"Loaded {len(messages)} messages")

    # Find compressed messages
    for idx, msg in enumerate(messages):
        if store.compressor.is_compressed(msg):
            entity_key = store.compressor.get_entity_key(msg)
            logger.info(f"\nCompressed message {idx}:")
            logger.info(f"  Entity key: {entity_key}")
            logger.info(f"  Compressed content preview: {msg['content'][:200]}...")

            # Retrieve full content via LOOKUP
            full_content = await store.retrieve_message(entity_key)
            if full_content:
                logger.info(f"  Full content length: {len(full_content)} chars")
                logger.info(f"  Full content preview: {full_content[:300]}...")
                logger.info("  ✓ LOOKUP retrieval successful!")
            else:
                logger.warning("  ✗ LOOKUP retrieval failed")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Seed database with sample conversation sessions"
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default=f"test-tenant-{uuid.uuid4().hex[:8]}",
        help="Tenant identifier (default: random)",
    )
    parser.add_argument(
        "--session-id",
        type=str,
        help="Specific session ID to seed (default: random for each conversation)",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        default=f"demo-user-{uuid.uuid4().hex[:8]}",
        help="User identifier (default: random)",
    )
    parser.add_argument(
        "--conversation",
        type=str,
        choices=list(ALL_SAMPLE_CONVERSATIONS.keys()),
        help="Specific conversation to seed (default: all)",
    )
    parser.add_argument(
        "--all", action="store_true", help="Seed all sample conversations"
    )
    parser.add_argument(
        "--demo-lookup",
        action="store_true",
        help="Demonstrate LOOKUP retrieval after seeding",
    )

    args = parser.parse_args()

    if not settings.postgres.enabled:
        logger.error("Postgres is disabled. Cannot seed data.")
        logger.info("Set POSTGRES__ENABLED=true in your environment")
        return

    if args.all:
        await seed_all_samples(args.tenant_id)

        if args.demo_lookup:
            # Demo LOOKUP on compression test conversation
            logger.info("\n" + "=" * 60)
            logger.info("Demonstrating LOOKUP retrieval...")
            logger.info("=" * 60)
            # Find a session with compressed messages
            # For now, just log instructions
            logger.info(
                "\nTo demonstrate LOOKUP, run this command with a specific session ID:"
            )
            logger.info(
                "  python -m rem.tests.scripts.seed_sample_sessions --demo-lookup --session-id <session-id>"
            )

    elif args.demo_lookup and args.session_id:
        await demonstrate_lookup_retrieval(args.tenant_id, args.session_id)

    elif args.conversation:
        session_id = args.session_id or f"demo-{args.conversation}-{uuid.uuid4()}"
        conversation = ALL_SAMPLE_CONVERSATIONS[args.conversation]

        await seed_conversation(
            tenant_id=args.tenant_id,
            session_id=session_id,
            user_id=args.user_id,
            conversation=conversation,
        )

        logger.info(f"\nSession seeded successfully!")
        logger.info(f"  Tenant ID: {args.tenant_id}")
        logger.info(f"  Session ID: {session_id}")
        logger.info(f"  User ID: {args.user_id}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
