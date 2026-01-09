"""Convert stored session messages to pydantic-ai native message format.

This module enables proper conversation history replay by converting our simplified
storage format into pydantic-ai's native ModelRequest/ModelResponse types.

Key insight: When we store tool results, we only store the result (ToolReturnPart).
But LLM APIs require matching ToolCallPart for each ToolReturnPart. So we synthesize
the ToolCallPart from stored metadata (tool_name, tool_call_id) and arguments.

Tool arguments can come from two places:
- Parent tool calls (ask_agent): tool_arguments stored in metadata (content = result)
- Child tool calls (register_metadata): arguments parsed from content (content = args as JSON)

Storage format (our simplified format):
    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "..."}
    {"role": "tool", "content": "{...}", "tool_name": "...", "tool_call_id": "...", "tool_arguments": {...}}  # optional

Pydantic-ai format (what the LLM expects):
    ModelRequest(parts=[UserPromptPart(content="...")])
    ModelResponse(parts=[TextPart(content="..."), ToolCallPart(...)])  # Call
    ModelRequest(parts=[ToolReturnPart(...)])  # Result

Example usage:
    from rem.services.session.pydantic_messages import session_to_pydantic_messages

    # Load session history
    session_history = await store.load_session_messages(session_id)

    # Convert to pydantic-ai format
    message_history = session_to_pydantic_messages(session_history)

    # Use with agent.run()
    result = await agent.run(user_prompt, message_history=message_history)
"""

import json
import re
from typing import Any

from loguru import logger
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


def _sanitize_tool_name(tool_name: str) -> str:
    """Sanitize tool name for OpenAI API compatibility.

    OpenAI requires tool names to match pattern: ^[a-zA-Z0-9_-]+$
    This replaces invalid characters (like colons) with underscores.
    """
    return re.sub(r'[^a-zA-Z0-9_-]', '_', tool_name)


def session_to_pydantic_messages(
    session_history: list[dict[str, Any]],
    system_prompt: str | None = None,
) -> list[ModelMessage]:
    """Convert stored session messages to pydantic-ai ModelMessage format.

    Handles the conversion of our simplified storage format to pydantic-ai's
    native message types, including synthesizing ToolCallPart for tool results.

    IMPORTANT: pydantic-ai only auto-adds system prompts when message_history is empty.
    When passing message_history to agent.run(), you MUST include the system prompt
    via the system_prompt parameter here.

    Args:
        session_history: List of message dicts from SessionMessageStore.load_session_messages()
            Each dict has: role, content, and optionally tool_name, tool_call_id, tool_arguments
        system_prompt: The agent's system prompt (from schema description). This is REQUIRED
            for proper agent behavior on subsequent turns, as pydantic-ai won't add it
            automatically when message_history is provided.

    Returns:
        List of ModelMessage (ModelRequest | ModelResponse) ready for agent.run(message_history=...)

    Note:
        - System prompts ARE included as SystemPromptPart when system_prompt is provided
        - Tool results require synthesized ToolCallPart to satisfy LLM API requirements
        - The first message in session_history should be "user" role (from context builder)
    """
    messages: list[ModelMessage] = []

    # CRITICAL: Prepend agent's system prompt if provided
    # This ensures the agent's instructions are present on every turn
    # pydantic-ai only auto-adds system prompts when message_history is empty
    if system_prompt:
        messages.append(ModelRequest(parts=[SystemPromptPart(content=system_prompt)]))
        logger.debug(f"Prepended agent system prompt ({len(system_prompt)} chars) to message history")

    # Track pending tool results to batch them with assistant responses
    # When we see a tool message, we need to:
    # 1. Add a ModelResponse with ToolCallPart (synthesized)
    # 2. Add a ModelRequest with ToolReturnPart (actual result)

    i = 0
    while i < len(session_history):
        msg = session_history[i]
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user":
            # User messages become ModelRequest with UserPromptPart
            messages.append(ModelRequest(parts=[UserPromptPart(content=content)]))

        elif role == "assistant":
            # Assistant text becomes ModelResponse with TextPart
            # Check if there are following tool messages that should be grouped
            tool_calls = []
            tool_returns = []

            # Look ahead for tool messages that follow this assistant message
            j = i + 1
            while j < len(session_history) and session_history[j].get("role") == "tool":
                tool_msg = session_history[j]
                tool_name = tool_msg.get("tool_name", "unknown_tool")
                tool_call_id = tool_msg.get("tool_call_id", f"call_{j}")
                tool_content = tool_msg.get("content", "{}")

                # tool_arguments: prefer explicit field, fallback to parsing content
                tool_arguments = tool_msg.get("tool_arguments")
                if tool_arguments is None and isinstance(tool_content, str) and tool_content:
                    try:
                        tool_arguments = json.loads(tool_content)
                    except json.JSONDecodeError:
                        tool_arguments = {}

                # Parse tool content if it's a JSON string
                if isinstance(tool_content, str):
                    try:
                        tool_result = json.loads(tool_content)
                    except json.JSONDecodeError:
                        tool_result = {"raw": tool_content}
                else:
                    tool_result = tool_content

                # Sanitize tool name for OpenAI API compatibility
                safe_tool_name = _sanitize_tool_name(tool_name)

                # Synthesize ToolCallPart (what the model "called")
                tool_calls.append(ToolCallPart(
                    tool_name=safe_tool_name,
                    args=tool_arguments if tool_arguments else {},
                    tool_call_id=tool_call_id,
                ))

                # Create ToolReturnPart (the actual result)
                tool_returns.append(ToolReturnPart(
                    tool_name=safe_tool_name,
                    content=tool_result,
                    tool_call_id=tool_call_id,
                ))

                j += 1

            # Build the assistant's ModelResponse
            response_parts = []

            # Add tool calls first (if any)
            response_parts.extend(tool_calls)

            # Add text content (if any)
            if content:
                response_parts.append(TextPart(content=content))

            # Only add ModelResponse if we have parts
            if response_parts:
                messages.append(ModelResponse(
                    parts=response_parts,
                    model_name="recovered",  # We don't store model name
                ))

            # Add tool returns as ModelRequest (required by LLM API)
            if tool_returns:
                messages.append(ModelRequest(parts=tool_returns))

            # Skip the tool messages we just processed
            i = j - 1

        elif role == "tool":
            # Orphan tool message (no preceding assistant) - synthesize both parts
            tool_name = msg.get("tool_name", "unknown_tool")
            tool_call_id = msg.get("tool_call_id", f"call_{i}")
            tool_content = msg.get("content", "{}")

            # tool_arguments: prefer explicit field, fallback to parsing content
            tool_arguments = msg.get("tool_arguments")
            if tool_arguments is None and isinstance(tool_content, str) and tool_content:
                try:
                    tool_arguments = json.loads(tool_content)
                except json.JSONDecodeError:
                    tool_arguments = {}

            # Parse tool content
            if isinstance(tool_content, str):
                try:
                    tool_result = json.loads(tool_content)
                except json.JSONDecodeError:
                    tool_result = {"raw": tool_content}
            else:
                tool_result = tool_content

            # Sanitize tool name for OpenAI API compatibility
            safe_tool_name = _sanitize_tool_name(tool_name)

            # Synthesize the tool call (ModelResponse with ToolCallPart)
            messages.append(ModelResponse(
                parts=[ToolCallPart(
                    tool_name=safe_tool_name,
                    args=tool_arguments if tool_arguments else {},
                    tool_call_id=tool_call_id,
                )],
                model_name="recovered",
            ))

            # Add the tool return (ModelRequest with ToolReturnPart)
            messages.append(ModelRequest(
                parts=[ToolReturnPart(
                    tool_name=safe_tool_name,
                    content=tool_result,
                    tool_call_id=tool_call_id,
                )]
            ))

        elif role == "system":
            # Skip system messages - pydantic-ai handles these via Agent.system_prompt
            logger.debug("Skipping system message in session history (handled by Agent)")

        else:
            logger.warning(f"Unknown message role in session history: {role}")

        i += 1

    logger.debug(f"Converted {len(session_history)} stored messages to {len(messages)} pydantic-ai messages")
    return messages


def audit_session_history(
    session_id: str,
    agent_name: str,
    prompt: str,
    raw_session_history: list[dict[str, Any]],
    pydantic_messages_count: int,
) -> None:
    """
    Dump session history to a YAML file for debugging.

    Only runs when DEBUG__AUDIT_SESSION=true. Writes to DEBUG__AUDIT_DIR (default /tmp).
    Appends to the same file for a session, so all agent invocations are in one place.

    Args:
        session_id: The session identifier
        agent_name: Name of the agent being invoked
        prompt: The prompt being sent to the agent
        raw_session_history: The raw session messages from the database
        pydantic_messages_count: Count of converted pydantic-ai messages
    """
    from ...settings import settings

    if not settings.debug.audit_session:
        return

    try:
        import yaml
        from pathlib import Path
        from ...utils.date_utils import utc_now, to_iso

        audit_dir = Path(settings.debug.audit_dir)
        audit_dir.mkdir(parents=True, exist_ok=True)
        audit_file = audit_dir / f"{session_id}.yaml"

        # Create entry for this agent invocation
        entry = {
            "timestamp": to_iso(utc_now()),
            "agent_name": agent_name,
            "prompt": prompt,
            "raw_history_count": len(raw_session_history),
            "pydantic_messages_count": pydantic_messages_count,
            "raw_session_history": raw_session_history,
        }

        # Load existing data or create new
        existing_data: dict[str, Any] = {"session_id": session_id, "invocations": []}
        if audit_file.exists():
            with open(audit_file) as f:
                loaded = yaml.safe_load(f)
                if loaded:
                    # Ensure session_id is always present (backfill if missing)
                    existing_data = {
                        "session_id": loaded.get("session_id", session_id),
                        "invocations": loaded.get("invocations", []),
                    }

        # Append this invocation
        existing_data["invocations"].append(entry)

        with open(audit_file, "w") as f:
            yaml.dump(existing_data, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"DEBUG: Session audit updated: {audit_file}")
    except Exception as e:
        logger.warning(f"DEBUG: Failed to dump session audit: {e}")
