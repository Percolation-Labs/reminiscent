"""Test that exports session data to YAML for inspection."""

import yaml
from pathlib import Path

import pytest
from rem.services.session import MessageCompressor


# Load conversations from YAML file
def _load_conversations():
    """Load sample conversations from YAML file."""
    yaml_path = Path(__file__).parent.parent / "data" / "sample_conversations.yaml"
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    return data


CONVERSATIONS = _load_conversations()
REM_INTRO_CONVERSATION = CONVERSATIONS["rem_intro"]
COMPRESSION_TEST_CONVERSATION = CONVERSATIONS["compression_test"]


@pytest.mark.asyncio
async def test_export_compressed_session_to_yaml(tmp_path):
    """Export a compressed session to YAML file for inspection."""
    # Setup
    compressor = MessageCompressor(truncate_length=200)
    session_id = "demo-session-abc-123"
    tenant_id = "acme-corp"
    user_id = "alice"

    # Compress messages
    compressed_msgs = []
    for idx, msg in enumerate(REM_INTRO_CONVERSATION):
        entity_key = f"session-{session_id}-msg-{idx}"
        compressed = compressor.compress_message(msg.copy(), entity_key)
        compressed_msgs.append({
            "index": idx,
            "role": msg["role"],
            "timestamp": msg.get("timestamp"),
            "original_length": len(msg["content"]),
            "compressed_length": len(compressed["content"]),
            "is_compressed": compressed.get("_compressed", False),
            "lookup_key": compressed.get("_entity_key"),
            "content": compressed["content"],
        })

    # Create session export
    session_export = {
        "session_id": session_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "message_count": len(compressed_msgs),
        "compressed_count": sum(1 for m in compressed_msgs if m["is_compressed"]),
        "messages": compressed_msgs,
    }

    # Save to file
    output_file = tmp_path / "compressed_session.yaml"
    with open(output_file, "w") as f:
        yaml.dump(session_export, f, default_flow_style=False, width=100, sort_keys=False)

    # Also print to stdout
    print("\n" + "=" * 80)
    print("COMPRESSED SESSION EXPORT")
    print("=" * 80)
    print(yaml.dump(session_export, default_flow_style=False, width=100, sort_keys=False))

    # Verify file was created
    assert output_file.exists()
    print(f"\n✓ Exported to: {output_file}")


@pytest.mark.asyncio
async def test_export_long_message_compression(tmp_path):
    """Export long message compression to YAML."""
    compressor = MessageCompressor(truncate_length=200)
    session_id = "demo-long-msg-session"

    # Get very long message
    long_msg = COMPRESSION_TEST_CONVERSATION[1]
    entity_key = f"session-{session_id}-msg-1"

    # Compress
    compressed = compressor.compress_message(long_msg.copy(), entity_key)

    # Export
    export_data = {
        "session_id": session_id,
        "message": {
            "index": 1,
            "role": compressed["role"],
            "original_length": len(long_msg["content"]),
            "compressed_length": len(compressed["content"]),
            "reduction_percent": round(
                (1 - len(compressed["content"]) / len(long_msg["content"])) * 100, 1
            ),
            "is_compressed": compressed.get("_compressed", False),
            "lookup_key": compressed.get("_entity_key"),
            "compressed_content": compressed["content"],
        },
    }

    # Save to file
    output_file = tmp_path / "long_message_compression.yaml"
    with open(output_file, "w") as f:
        yaml.dump(export_data, f, default_flow_style=False, width=100, sort_keys=False)

    # Print
    print("\n" + "=" * 80)
    print("LONG MESSAGE COMPRESSION")
    print("=" * 80)
    print(yaml.dump(export_data, default_flow_style=False, width=100, sort_keys=False))

    assert output_file.exists()
    print(f"\n✓ Exported to: {output_file}")
