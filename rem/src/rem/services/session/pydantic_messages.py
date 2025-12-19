"""Convert stored session messages to pydantic-ai native message format.

This module enables proper conversation history replay by converting our simplified
storage format into pydantic-ai's native ModelRequest/ModelResponse types.

Key insight: When we store tool results, we only store the result (ToolReturnPart).
But LLM APIs require matching ToolCallPart for each ToolReturnPart. So we synthesize
the ToolCallPart from stored metadata (tool_name, tool_call_id, tool_arguments).

Storage format (our simplified format):
    {"role": "user", "content": "..."}
    {"role": "assistant", "content": "..."}
    {"role": "tool", "content": "{...}", "tool_name": "...", "tool_call_id": "...", "tool_arguments": {...}}

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
from typing import Any

from loguru import logger
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)


def session_to_pydantic_messages(
    session_history: list[dict[str, Any]],
) -> list[ModelMessage]:
    """Convert stored session messages to pydantic-ai ModelMessage format.

    Handles the conversion of our simplified storage format to pydantic-ai's
    native message types, including synthesizing ToolCallPart for tool results.

    Args:
        session_history: List of message dicts from SessionMessageStore.load_session_messages()
            Each dict has: role, content, and optionally tool_name, tool_call_id, tool_arguments

    Returns:
        List of ModelMessage (ModelRequest | ModelResponse) ready for agent.run(message_history=...)

    Note:
        - System prompts are NOT included - pydantic-ai handles those via the Agent
        - Tool results require synthesized ToolCallPart to satisfy LLM API requirements
        - The first message in session_history should be "user" role (from context builder)
    """
    messages: list[ModelMessage] = []

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
                tool_arguments = tool_msg.get("tool_arguments", {})
                tool_content = tool_msg.get("content", "{}")

                # Parse tool content if it's a JSON string
                if isinstance(tool_content, str):
                    try:
                        tool_result = json.loads(tool_content)
                    except json.JSONDecodeError:
                        tool_result = {"raw": tool_content}
                else:
                    tool_result = tool_content

                # Synthesize ToolCallPart (what the model "called")
                tool_calls.append(ToolCallPart(
                    tool_name=tool_name,
                    args=tool_arguments if tool_arguments else {},
                    tool_call_id=tool_call_id,
                ))

                # Create ToolReturnPart (the actual result)
                tool_returns.append(ToolReturnPart(
                    tool_name=tool_name,
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
            tool_arguments = msg.get("tool_arguments", {})
            tool_content = msg.get("content", "{}")

            # Parse tool content
            if isinstance(tool_content, str):
                try:
                    tool_result = json.loads(tool_content)
                except json.JSONDecodeError:
                    tool_result = {"raw": tool_content}
            else:
                tool_result = tool_content

            # Synthesize the tool call (ModelResponse with ToolCallPart)
            messages.append(ModelResponse(
                parts=[ToolCallPart(
                    tool_name=tool_name,
                    args=tool_arguments if tool_arguments else {},
                    tool_call_id=tool_call_id,
                )],
                model_name="recovered",
            ))

            # Add the tool return (ModelRequest with ToolReturnPart)
            messages.append(ModelRequest(
                parts=[ToolReturnPart(
                    tool_name=tool_name,
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
