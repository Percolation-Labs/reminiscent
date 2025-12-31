#!/usr/bin/env python3
"""
Session Analysis Script - Analyze what agents see in conversation history per turn.

This script runs an intake simulation and after each turn:
1. Exports the raw database messages for the session
2. Shows what the agent would see when the session is reloaded
3. Highlights tool messages and their visibility
"""

import httpx
import json
import uuid
import time
import asyncio
import asyncpg
from datetime import datetime

# Configuration
API_URL = "http://localhost:8001/api/v1/chat/completions"
DB_URL = "postgresql://rem:rem@localhost:5050/rem"

# Simulation 1: Standard Multi-Turn Intake (6-8 turns)
SIMULATION_MESSAGES = [
    "Hi, I've been having trouble with anxiety lately",
    "It started about 3 months ago when I lost my job. It's been constant since then",
    "I'd say it's about a 7 out of 10. I can't focus and I've been avoiding seeing friends",
    "No, I haven't had any thoughts like that. No history of that either",
    "I feel down sometimes but not most days. I still enjoy things. I do worry a lot though, hard to relax",
    "I'm not on any medications. I drink socially, maybe 2 drinks a week",
    "Work is hard to focus on. Sleep is rough, takes me forever to fall asleep, maybe 5 hours total. My partner is supportive though",
    "I think that covers it"
]


async def get_db_connection():
    """Get async database connection."""
    return await asyncpg.connect(DB_URL)


async def export_session_messages(conn, session_id: str, user_id: str) -> list[dict]:
    """Export all messages for a session from the database."""
    query = """
        SELECT
            id,
            content,
            message_type,
            session_id,
            user_id,
            metadata,
            created_at
        FROM messages
        WHERE session_id = $1
          AND user_id = $2
          AND deleted_at IS NULL
        ORDER BY created_at ASC
    """
    rows = await conn.fetch(query, session_id, user_id)

    messages = []
    for row in rows:
        metadata = row["metadata"]
        # metadata is already a dict from JSONB
        if metadata is None:
            metadata = {}
        elif isinstance(metadata, str):
            metadata = json.loads(metadata)

        msg = {
            "id": str(row["id"]),
            "role": row["message_type"],
            "content": row["content"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "metadata": metadata,
        }
        messages.append(msg)

    return messages


def format_message_for_display(msg: dict, max_content_len: int = 200) -> str:
    """Format a message for display, truncating content if needed."""
    role = msg.get("role", "unknown")
    content = msg.get("content", "")
    metadata = msg.get("metadata", {})

    # Truncate content for display
    if len(content) > max_content_len:
        display_content = content[:max_content_len] + f"... [{len(content)} chars total]"
    else:
        display_content = content

    # Format based on role
    if role == "tool":
        tool_name = metadata.get("tool_name", "unknown_tool")
        tool_call_id = metadata.get("tool_call_id", "")[:8] if metadata.get("tool_call_id") else ""
        return f"  [TOOL: {tool_name}] (call_id: {tool_call_id}...)\n    {display_content}"
    elif role == "user":
        return f"  [USER]\n    {display_content}"
    elif role == "assistant":
        return f"  [ASSISTANT]\n    {display_content}"
    else:
        return f"  [{role.upper()}]\n    {display_content}"


def simulate_session_reload(messages: list[dict]) -> list[dict]:
    """
    Simulate what the agent would see when session is reloaded.

    This mimics SessionMessageStore.load_session_messages() behavior:
    - User messages: returned as-is
    - Tool messages: returned as-is with metadata (NEVER compressed)
    - Assistant messages: may be compressed if long (>400 chars)
    """
    MIN_LENGTH_FOR_COMPRESSION = 400
    TRUNCATE_LENGTH = 200

    reloaded = []
    for idx, msg in enumerate(messages):
        role = msg.get("role", "")
        content = msg.get("content", "")
        metadata = msg.get("metadata", {})

        reloaded_msg = {
            "role": role,
            "content": content,
        }

        # For tool messages, reconstruct tool call metadata
        if role == "tool":
            if metadata.get("tool_call_id"):
                reloaded_msg["tool_call_id"] = metadata["tool_call_id"]
            if metadata.get("tool_name"):
                reloaded_msg["tool_name"] = metadata["tool_name"]
            if metadata.get("tool_arguments"):
                reloaded_msg["tool_arguments"] = metadata["tool_arguments"]

        # Compress long ASSISTANT messages (never tool messages)
        if role == "assistant" and len(content) > MIN_LENGTH_FOR_COMPRESSION:
            n = TRUNCATE_LENGTH
            start = content[:n]
            end = content[-n:]
            entity_key = f"session-msg-{idx}"
            reloaded_msg["content"] = f"{start}\n\n... [Message truncated - REM LOOKUP {entity_key} to recover full content] ...\n\n{end}"
            reloaded_msg["_compressed"] = True

        reloaded.append(reloaded_msg)

    return reloaded


def simulate_pydantic_conversion(reloaded_messages: list[dict]) -> list[str]:
    """
    Simulate conversion to pydantic-ai message format.

    This shows what the LLM would see in its context window.
    Returns a simplified representation of the pydantic message types.
    """
    pydantic_messages = []

    i = 0
    while i < len(reloaded_messages):
        msg = reloaded_messages[i]
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            pydantic_messages.append(f"ModelRequest[UserPromptPart]: {content[:100]}...")

        elif role == "assistant":
            # Check if there are following tool messages
            tool_calls = []
            j = i + 1
            while j < len(reloaded_messages) and reloaded_messages[j].get("role") == "tool":
                tool_msg = reloaded_messages[j]
                tool_name = tool_msg.get("tool_name", "unknown")
                tool_calls.append(tool_name)
                j += 1

            if tool_calls:
                pydantic_messages.append(f"ModelResponse[ToolCallPart x{len(tool_calls)}: {', '.join(tool_calls)}, TextPart]")
                pydantic_messages.append(f"ModelRequest[ToolReturnPart x{len(tool_calls)}]")
            else:
                pydantic_messages.append(f"ModelResponse[TextPart]: {content[:100]}...")

            i = j - 1  # Skip tool messages we processed

        elif role == "tool":
            # Orphan tool message
            tool_name = msg.get("tool_name", "unknown")
            pydantic_messages.append(f"ModelResponse[ToolCallPart: {tool_name}]")
            pydantic_messages.append(f"ModelRequest[ToolReturnPart: {tool_name}]")

        i += 1

    return pydantic_messages


async def run_simulation_turn(
    user_msg: str,
    conversation: list[dict],
    user_id: str,
    session_id: str,
) -> tuple[str, list[dict]]:
    """
    Run a single turn of the simulation.

    Returns:
        Tuple of (assistant_response, tool_events)
    """
    conversation.append({"role": "user", "content": user_msg})

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                API_URL,
                headers={
                    "X-Agent-Schema": "intake",
                    "X-User-Id": user_id,
                    "X-Session-Id": session_id,
                },
                json={"messages": conversation, "stream": True},
                timeout=120.0,
            )
            response.raise_for_status()

            content = ""
            tool_events = []

            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                if line == "data: [DONE]":
                    break

                try:
                    evt = json.loads(line[6:])

                    # Capture tool_call SSE events
                    if evt.get("type") == "tool_call":
                        tool_events.append({
                            "tool_name": evt.get("tool_name"),
                            "tool_call_id": evt.get("tool_call_id"),
                            "arguments": evt.get("arguments", {}),
                        })

                    # Capture content
                    delta = evt.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        content += delta["content"]

                except json.JSONDecodeError:
                    continue

            conversation.append({"role": "assistant", "content": content})
            return content, tool_events

        except Exception as e:
            print(f"Error during API call: {e}")
            return f"[ERROR: {e}]", []


async def main():
    """Run the full simulation with per-turn database export."""

    # Generate unique session/user IDs
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())

    print("=" * 80)
    print("SESSION ANALYSIS: What the Agent Sees Per Turn")
    print("=" * 80)
    print(f"\nUser ID:    {user_id}")
    print(f"Session ID: {session_id}")
    print(f"Simulation: Standard Multi-Turn Intake (8 turns)")
    print("=" * 80)

    # Connect to database
    conn = await get_db_connection()

    conversation = []

    try:
        for turn_num, user_msg in enumerate(SIMULATION_MESSAGES, 1):
            print(f"\n{'='*80}")
            print(f"TURN {turn_num}")
            print(f"{'='*80}")

            print(f"\n>>> USER: {user_msg}")

            # Run the turn
            assistant_response, tool_events = await run_simulation_turn(
                user_msg, conversation, user_id, session_id
            )

            # Show tool events from SSE
            if tool_events:
                print(f"\n📧 SSE TOOL EVENTS:")
                for te in tool_events:
                    call_id = te.get('tool_call_id') or 'N/A'
                    call_id_short = call_id[:8] if len(call_id) > 8 else call_id
                    print(f"  - {te.get('tool_name', 'unknown')} (call_id: {call_id_short})")

            # Show assistant response (truncated)
            print(f"\n<<< ASSISTANT: {assistant_response[:200]}...")

            # Wait a moment for DB writes to complete
            await asyncio.sleep(0.5)

            # Export database state
            print(f"\n📦 DATABASE STATE (after turn {turn_num}):")
            db_messages = await export_session_messages(conn, session_id, user_id)

            if not db_messages:
                print("  [No messages found in database yet]")
            else:
                print(f"  Total messages in DB: {len(db_messages)}")
                print(f"\n  Raw messages:")
                for msg in db_messages:
                    print(format_message_for_display(msg))

            # Show what agent would see on reload
            print(f"\n🔄 AGENT VIEW (what the agent sees on next turn):")
            reloaded = simulate_session_reload(db_messages)
            pydantic_repr = simulate_pydantic_conversion(reloaded)

            for pr in pydantic_repr:
                print(f"  {pr}")

            # Count message types
            user_count = sum(1 for m in db_messages if m["role"] == "user")
            assistant_count = sum(1 for m in db_messages if m["role"] == "assistant")
            tool_count = sum(1 for m in db_messages if m["role"] == "tool")

            print(f"\n📊 SUMMARY: {user_count} user, {assistant_count} assistant, {tool_count} tool messages")

            # Delay between turns
            if turn_num < len(SIMULATION_MESSAGES):
                print("\n⏳ Waiting 2 seconds before next turn...")
                await asyncio.sleep(2)

        # Final export
        print(f"\n{'='*80}")
        print("FINAL SESSION EXPORT")
        print(f"{'='*80}")

        final_messages = await export_session_messages(conn, session_id, user_id)

        # Export to file
        export_file = f"/tmp/session_export_{session_id[:8]}.json"
        with open(export_file, "w") as f:
            json.dump({
                "session_id": session_id,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
                "messages": final_messages,
            }, f, indent=2, default=str)

        print(f"\nExported {len(final_messages)} messages to: {export_file}")

        # Show tool message details
        print(f"\n📋 TOOL MESSAGE DETAILS:")
        for msg in final_messages:
            if msg["role"] == "tool":
                metadata = msg.get("metadata", {})
                tool_name = metadata.get("tool_name", "unknown")
                print(f"\n  Tool: {tool_name}")
                print(f"  Call ID: {metadata.get('tool_call_id', 'N/A')}")
                print(f"  Content preview: {msg['content'][:300]}...")
                if metadata.get("tool_arguments"):
                    print(f"  Arguments: {json.dumps(metadata['tool_arguments'], indent=4)[:500]}...")

    finally:
        await conn.close()

    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(main())
