"""Demonstrate session creation, storage, and recovery with YAML export.

This script:
1. Creates a realistic conversation session
2. Stores it in memory (simulating database)
3. Compresses long messages with LOOKUP keys
4. Recovers the session
5. Exports to YAML for inspection
"""

import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

import yaml

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from rem.services.session import MessageCompressor
from rem.tests.fixtures import COMPRESSION_TEST_CONVERSATION, REM_INTRO_CONVERSATION


class MockDB:
    """Mock database for demonstration without Postgres."""

    def __init__(self):
        self.messages = {}

    async def store(self, message_id: str, data: dict):
        self.messages[message_id] = data

    async def retrieve(self, message_id: str) -> dict | None:
        return self.messages.get(message_id)


async def demo_session_lifecycle():
    """Demonstrate full session lifecycle with YAML export."""
    print("=" * 80)
    print("SESSION MANAGEMENT DEMONSTRATION")
    print("=" * 80)
    print()

    # Setup
    tenant_id = "demo-tenant-123"
    session_id = f"session-{uuid.uuid4()}"
    user_id = "alice"

    print(f"Session ID: {session_id}")
    print(f"Tenant ID: {tenant_id}")
    print(f"User ID: {user_id}")
    print()

    # Create compressor
    compressor = MessageCompressor(truncate_length=200)

    # Use simple conversation first
    conversation = REM_INTRO_CONVERSATION

    print("=" * 80)
    print("STEP 1: Original Conversation")
    print("=" * 80)
    print()

    for idx, msg in enumerate(conversation):
        print(f"Message {idx} ({msg['role']}):")
        content = msg["content"]
        print(f"  Length: {len(content)} chars")
        print(f"  Preview: {content[:100]}...")
        print()

    # Compress messages
    print("=" * 80)
    print("STEP 2: Compression")
    print("=" * 80)
    print()

    compressed_messages = []
    for idx, msg in enumerate(conversation):
        entity_key = f"session-{session_id}-msg-{idx}"
        compressed = compressor.compress_message(msg.copy(), entity_key)
        compressed_messages.append(compressed)

        if compressor.is_compressed(compressed):
            print(f"✓ Message {idx} COMPRESSED:")
            print(f"  Original: {msg.get('_original_length', len(msg['content']))} chars")
            print(f"  Compressed: {len(compressed['content'])} chars")
            print(f"  LOOKUP key: {entity_key}")
            print(f"  Reduction: {(1 - len(compressed['content']) / len(msg['content'])) * 100:.1f}%")
        else:
            print(f"○ Message {idx} NOT compressed (too short)")
        print()

    # Export compressed session to YAML
    print("=" * 80)
    print("STEP 3: Compressed Session (YAML)")
    print("=" * 80)
    print()

    compressed_session = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat(),
        "message_count": len(compressed_messages),
        "messages": [
            {
                "role": msg["role"],
                "content": msg["content"],
                "compressed": msg.get("_compressed", False),
                "entity_key": msg.get("_entity_key"),
                "original_length": msg.get("_original_length"),
            }
            for msg in compressed_messages
        ],
    }

    yaml_output = yaml.dump(compressed_session, default_flow_style=False, width=80)
    print(yaml_output)

    # Simulate LOOKUP recovery
    print("=" * 80)
    print("STEP 4: LOOKUP Recovery")
    print("=" * 80)
    print()

    # Simulate retrieving full content for compressed message
    for idx, msg in enumerate(compressed_messages):
        if compressor.is_compressed(msg):
            entity_key = compressor.get_entity_key(msg)
            original_msg = conversation[idx]

            print(f"Recovering message via LOOKUP: {entity_key}")
            print(f"  Query: SELECT * FROM messages WHERE metadata->>'entity_key' = '{entity_key}'")
            print(f"  ✓ Retrieved {len(original_msg['content'])} chars")
            print()

            # Decompress
            decompressed = compressor.decompress_message(msg, original_msg["content"])
            print(f"  Original content matches: {decompressed['content'] == original_msg['content']}")
            print()

    # Export recovered session
    print("=" * 80)
    print("STEP 5: Recovered Session (YAML)")
    print("=" * 80)
    print()

    recovered_session = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "created_at": datetime.utcnow().isoformat(),
        "message_count": len(conversation),
        "messages": [
            {
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": msg.get("timestamp"),
            }
            for msg in conversation
        ],
    }

    yaml_output = yaml.dump(recovered_session, default_flow_style=False, width=80)
    print(yaml_output)


async def demo_long_message_compression():
    """Demonstrate compression with very long messages."""
    print("\n" + "=" * 80)
    print("BONUS: Long Message Compression Demo")
    print("=" * 80)
    print()

    session_id = f"session-{uuid.uuid4()}"
    compressor = MessageCompressor(truncate_length=200)

    # Get long conversation
    conversation = COMPRESSION_TEST_CONVERSATION
    long_message = conversation[1]  # Assistant response

    print(f"Long message length: {len(long_message['content'])} chars")
    print()

    # Compress
    entity_key = f"session-{session_id}-msg-1"
    compressed = compressor.compress_message(long_message.copy(), entity_key)

    print("Compressed version:")
    print("-" * 80)
    print(compressed["content"])
    print("-" * 80)
    print()

    print(f"Compression stats:")
    print(f"  Original: {len(long_message['content'])} chars")
    print(f"  Compressed: {len(compressed['content'])} chars")
    print(f"  Reduction: {(1 - len(compressed['content']) / len(long_message['content'])) * 100:.1f}%")
    print(f"  LOOKUP key: {entity_key}")
    print()

    # Export to YAML
    compressed_data = {
        "message": {
            "role": compressed["role"],
            "content": compressed["content"],
            "metadata": {
                "compressed": compressed.get("_compressed"),
                "entity_key": compressed.get("_entity_key"),
                "original_length": compressed.get("_original_length"),
            },
        }
    }

    print("YAML export:")
    print(yaml.dump(compressed_data, default_flow_style=False))


async def main():
    """Run all demonstrations."""
    await demo_session_lifecycle()
    await demo_long_message_compression()

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
