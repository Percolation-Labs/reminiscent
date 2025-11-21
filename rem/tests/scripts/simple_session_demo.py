"""Simple standalone demonstration of session compression and recovery."""

import sys
from pathlib import Path

import yaml

# Add project root to path
root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(root))

from rem.services.session import MessageCompressor
from rem.tests.fixtures import COMPRESSION_TEST_CONVERSATION, REM_INTRO_CONVERSATION

# Session metadata
SESSION_ID = "demo-session-abc-123"
TENANT_ID = "acme-corp"
USER_ID = "alice"


def demo_compression():
    """Demonstrate message compression with LOOKUP keys."""
    print("=" * 80)
    print("SESSION COMPRESSION DEMO")
    print("=" * 80)
    print()

    compressor = MessageCompressor(truncate_length=200)

    # Use the intro conversation
    conversation = REM_INTRO_CONVERSATION

    print(f"Session ID: {SESSION_ID}")
    print(f"Original message count: {len(conversation)}")
    print()

    # Compress messages
    compressed_messages = []
    for idx, msg in enumerate(conversation):
        entity_key = f"session-{SESSION_ID}-msg-{idx}"
        compressed = compressor.compress_message(msg.copy(), entity_key)
        compressed_messages.append(compressed)

        print(f"Message {idx} ({msg['role']}):")
        print(f"  Original: {len(msg['content'])} chars")

        if compressor.is_compressed(compressed):
            print(f"  Compressed: {len(compressed['content'])} chars")
            print(f"  LOOKUP key: {entity_key}")
            print(f"  Reduction: {(1 - len(compressed['content']) / len(msg['content'])) * 100:.0f}%")
        else:
            print(f"  Not compressed (below threshold)")
        print()

    # Export compressed session to YAML
    print("=" * 80)
    print("COMPRESSED SESSION (YAML)")
    print("=" * 80)
    print()

    session_data = {
        "session_id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "message_count": len(compressed_messages),
        "messages": [
            {
                "index": idx,
                "role": msg["role"],
                "content": msg["content"][:300] + "..." if len(msg["content"]) > 300 else msg["content"],
                "full_length": len(msg["content"]),
                "compressed": msg.get("_compressed", False),
                "lookup_key": msg.get("_entity_key"),
            }
            for idx, msg in enumerate(compressed_messages)
        ],
    }

    print(yaml.dump(session_data, default_flow_style=False, width=100))

    # Show recovery via LOOKUP
    print("=" * 80)
    print("RECOVERY VIA REM LOOKUP")
    print("=" * 80)
    print()

    for idx, msg in enumerate(compressed_messages):
        if compressor.is_compressed(msg):
            entity_key = compressor.get_entity_key(msg)
            print(f"Recovering message {idx}:")
            print(f"  SQL: SELECT * FROM messages")
            print(f"       WHERE metadata->>'entity_key' = '{entity_key}'")
            print(f"       AND tenant_id = '{TENANT_ID}'")
            print(f"  ✓ Retrieved full content ({len(conversation[idx]['content'])} chars)")
            print()


def demo_long_message():
    """Demonstrate compression with very long messages."""
    print("\n" + "=" * 80)
    print("LONG MESSAGE COMPRESSION DEMO")
    print("=" * 80)
    print()

    compressor = MessageCompressor(truncate_length=200)

    # Get the long assistant response
    long_conversation = COMPRESSION_TEST_CONVERSATION
    long_msg = long_conversation[1]  # Very long assistant response

    print(f"Original message length: {len(long_msg['content'])} chars")
    print()

    # Compress
    entity_key = f"session-{SESSION_ID}-msg-long"
    compressed = compressor.compress_message(long_msg.copy(), entity_key)

    print("Compressed content preview:")
    print("-" * 80)
    print(compressed["content"][:500])
    print("...")
    print(compressed["content"][-200:])
    print("-" * 80)
    print()

    print(f"Compression stats:")
    print(f"  Original length: {len(long_msg['content'])} chars")
    print(f"  Compressed length: {len(compressed['content'])} chars")
    print(f"  Reduction: {(1 - len(compressed['content']) / len(long_msg['content'])) * 100:.1f}%")
    print(f"  LOOKUP key: {entity_key}")
    print()

    # YAML export
    compressed_export = {
        "message": {
            "role": compressed["role"],
            "compressed_content": compressed["content"][:300] + "...",
            "metadata": {
                "compressed": compressed["_compressed"],
                "original_length": compressed["_original_length"],
                "compressed_length": len(compressed["content"]),
                "lookup_key": entity_key,
                "reduction_pct": round(
                    (1 - len(compressed["content"]) / len(long_msg["content"])) * 100, 1
                ),
            },
        }
    }

    print("YAML export:")
    print(yaml.dump(compressed_export, default_flow_style=False))


if __name__ == "__main__":
    demo_compression()
    demo_long_message()

    print("=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)
