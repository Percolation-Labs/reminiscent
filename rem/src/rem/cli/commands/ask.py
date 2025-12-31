"""
CLI command for testing Pydantic AI agents.

Usage:
    rem ask query-agent "Find all documents by Sarah" --model anthropic:claude-sonnet-4-5-20250929
    rem ask schemas/query-agent.yaml "What is the weather?" --temperature 0.7 --max-turns 5
    rem ask my-agent "Hello" --stream --version 1.2.0
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import click
from loguru import logger

from ...agentic.context import AgentContext
from ...agentic.providers.pydantic_ai import create_agent
from ...agentic.query import AgentQuery
from ...settings import settings
from ...utils.schema_loader import load_agent_schema


async def load_schema_from_registry(
    name: str, version: str | None = None
) -> dict[str, Any]:
    """
    Load agent schema from registry (database or cache).

    TODO: Implement schema registry with:
    - Database table: agent_schemas (name, version, schema_json, created_at)
    - Cache layer: Redis/in-memory for fast lookups
    - Versioning: semantic versioning with latest fallback

    Args:
        name: Schema name (e.g., "query-agent", "rem-agents-query-agent")
        version: Optional version (e.g., "1.2.0", defaults to latest)

    Returns:
        Agent schema as dictionary

    Example:
        schema = await load_schema_from_registry("query-agent", version="1.0.0")
    """
    # TODO: Implement database/cache lookup
    # from ...db import get_db_pool
    # async with get_db_pool() as pool:
    #     if version:
    #         query = "SELECT schema_json FROM agent_schemas WHERE name = $1 AND version = $2"
    #         row = await pool.fetchrow(query, name, version)
    #     else:
    #         query = "SELECT schema_json FROM agent_schemas WHERE name = $1 ORDER BY created_at DESC LIMIT 1"
    #         row = await pool.fetchrow(query, name)
    #
    #     if not row:
    #         raise ValueError(f"Schema not found: {name} (version: {version or 'latest'})")
    #
    #     return json.loads(row["schema_json"])

    raise NotImplementedError(
        f"Schema registry not implemented yet. Please use a file path instead.\n"
        f"Attempted to load: {name} (version: {version or 'latest'})"
    )


async def run_agent_streaming(
    agent,
    prompt: str,
    max_turns: int = 10,
    context: AgentContext | None = None,
    max_iterations: int | None = None,
    user_message: str | None = None,
) -> None:
    """
    Run agent in streaming mode using the SAME code path as the API.

    This uses stream_openai_response_with_save from the API to ensure:
    1. Tool calls are saved as separate "tool" messages (not embedded in content)
    2. Assistant response is clean text only (no [Calling: ...] markers)
    3. CLI testing is equivalent to API testing

    The CLI displays tool calls as [Calling: tool_name] for visibility,
    but these are NOT saved to the database.

    Args:
        agent: Pydantic AI agent
        prompt: Complete prompt (includes system context + history + query)
        max_turns: Maximum turns for agent execution (not used in current API)
        context: Optional AgentContext for session persistence
        max_iterations: Maximum iterations/requests (from agent schema or settings)
        user_message: The user's original message (for database storage)
    """
    import json
    from rem.api.routers.chat.streaming import stream_openai_response_with_save, save_user_message

    logger.info("Running agent in streaming mode...")

    try:
        # Save user message BEFORE streaming (same as API, using shared utility)
        if context and context.session_id and user_message:
            await save_user_message(
                session_id=context.session_id,
                user_id=context.user_id,
                content=user_message,
            )

        # Use the API streaming code path for consistency
        # This properly handles tool calls and message persistence
        model_name = getattr(agent, 'model', 'unknown')
        if hasattr(model_name, 'model_name'):
            model_name = model_name.model_name
        elif hasattr(model_name, 'name'):
            model_name = model_name.name
        else:
            model_name = str(model_name)

        async for chunk in stream_openai_response_with_save(
            agent=agent.agent if hasattr(agent, 'agent') else agent,
            prompt=prompt,
            model=model_name,
            session_id=context.session_id if context else None,
            user_id=context.user_id if context else None,
            agent_context=context,
        ):
            # Parse SSE chunks for CLI display
            if chunk.startswith("event: tool_call"):
                # Extract tool call info from next data line
                continue
            elif chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                try:
                    data_str = chunk[6:].strip()
                    if data_str:
                        data = json.loads(data_str)
                        # Check for tool_call event
                        if data.get("type") == "tool_call":
                            tool_name = data.get("tool_name", "tool")
                            status = data.get("status", "")
                            if status == "started":
                                print(f"\n[Calling: {tool_name}]", flush=True)
                        # Check for text content (OpenAI format)
                        elif "choices" in data and data["choices"]:
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                print(content, end="", flush=True)
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

        print("\n")  # Final newline after streaming
        logger.info("Final structured result:")

    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        raise


async def run_agent_non_streaming(
    agent,
    prompt: str,
    max_turns: int = 10,
    output_file: Path | None = None,
    context: AgentContext | None = None,
    plan: bool = False,
    max_iterations: int | None = None,
) -> dict[str, Any] | None:
    """
    Run agent in non-streaming mode using agent.run() with usage limits.

    Args:
        agent: Pydantic AI agent
        prompt: Complete prompt (includes system context + history + query)
        max_turns: Maximum turns for agent execution (not used in current API)
        output_file: Optional path to save output
        context: Optional AgentContext for session persistence
        plan: If True, output only the generated query (for query-agent)
        max_iterations: Maximum iterations/requests (from agent schema or settings)

    Returns:
        Output data if successful, None otherwise
    """
    from pydantic_ai import UsageLimits
    from rem.utils.date_utils import to_iso_with_z, utc_now

    logger.info("Running agent in non-streaming mode...")

    try:
        # Run agent and get complete result with usage limits
        usage_limits = UsageLimits(request_limit=max_iterations) if max_iterations else None
        result = await agent.run(prompt, usage_limits=usage_limits)

        # Extract output data
        output_data = None
        assistant_content = None
        if hasattr(result, "output"):
            output = result.output
            from rem.agentic.serialization import serialize_agent_result
            output_data = serialize_agent_result(output)

            if plan and isinstance(output_data, dict) and "query" in output_data:
                # Plan mode: Output only the query
                # Use sql formatting if possible or just raw string
                assistant_content = output_data["query"]
                print(assistant_content)
            else:
                # Normal mode
                assistant_content = json.dumps(output_data, indent=2)
                print(assistant_content)
        else:
            # Fallback for text-only results
            assistant_content = str(result)
            print(assistant_content)

        # Save to file if requested
        if output_file and output_data:
            await _save_output_file(output_file, output_data)

        # Save session messages (if session_id provided and postgres enabled)
        if context and context.session_id and settings.postgres.enabled:
            from ...services.session.compression import SessionMessageStore

            # Extract just the user query from prompt
            # Prompt format from ContextBuilder: system + history + user message
            # We need to extract the last user message
            user_message_content = prompt.split("\n\n")[-1] if "\n\n" in prompt else prompt

            user_message = {
                "role": "user",
                "content": user_message_content,
                "timestamp": to_iso_with_z(utc_now()),
            }

            assistant_message = {
                "role": "assistant",
                "content": assistant_content,
                "timestamp": to_iso_with_z(utc_now()),
            }

            # Store messages with compression
            store = SessionMessageStore(user_id=context.user_id or settings.test.effective_user_id)
            await store.store_session_messages(
                session_id=context.session_id,
                messages=[user_message, assistant_message],
                user_id=context.user_id,
                compress=True,
            )

            logger.debug(f"Saved conversation to session {context.session_id}")

        return output_data

    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        raise


async def _load_input_file(
    file_path: Path, user_id: str | None = None
) -> str:
    """
    Load content from input file using ContentService.

    Simple parse operation - just extracts content without creating Resources.

    Args:
        file_path: Path to input file
        user_id: Optional user ID (not used for simple parse)

    Returns:
        Parsed file content as string (markdown format)
    """
    from ...services.content import ContentService

    # Create ContentService instance
    content_service = ContentService()

    # Parse file (read-only, no database writes)
    logger.info(f"Parsing file: {file_path}")
    result = content_service.process_uri(str(file_path))
    content = result["content"]

    logger.info(
        f"Loaded {len(content)} characters from {file_path.suffix} file using {result['provider']}"
    )
    return content


async def _save_output_file(file_path: Path, data: dict[str, Any]) -> None:
    """
    Save output data to file in YAML format.

    Args:
        file_path: Path to output file
        data: Data to save
    """
    import yaml

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.success(f"Output saved to: {file_path}")


@click.command()
@click.argument("name_or_query")
@click.argument("query", required=False)
@click.option(
    "--model",
    "-m",
    default=None,
    help=f"LLM model (default: {settings.llm.default_model})",
)
@click.option(
    "--temperature",
    "-t",
    type=float,
    default=None,
    help=f"Temperature for generation (default: {settings.llm.default_temperature})",
)
@click.option(
    "--max-turns",
    type=int,
    default=10,
    help="Maximum turns for agent execution (default: 10)",
)
@click.option(
    "--version",
    "-v",
    default=None,
    help="Schema version (for registry lookup, defaults to latest)",
)
@click.option(
    "--stream/--no-stream",
    default=False,
    help="Enable streaming mode (default: disabled)",
)
@click.option(
    "--user-id",
    default=None,
    help="User ID for context (default: from settings.test.effective_user_id)",
)
@click.option(
    "--session-id",
    default=None,
    help="Session ID for context (default: auto-generated)",
)
@click.option(
    "--input-file",
    "-i",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Read input from file instead of QUERY argument (supports PDF, TXT, Markdown)",
)
@click.option(
    "--output-file",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Write output to file (YAML format)",
)
@click.option(
    "--plan",
    is_flag=True,
    default=False,
    help="Output only the generated plan/query (useful for query-agent)",
)
def ask(
    name_or_query: str,
    query: str | None,
    model: str | None,
    temperature: float | None,
    max_turns: int,
    version: str | None,
    stream: bool,
    user_id: str | None,
    session_id: str | None,
    input_file: Path | None,
    output_file: Path | None,
    plan: bool,
):
    """
    Run an agent with a query or file input.

    Arguments:
        NAME_OR_QUERY: Agent schema name OR query string.
        QUERY: Query string (if first arg is agent name).

    Examples:
        # Simple query (uses default 'rem' agent)
        rem ask "What documents did I upload?"

        # Explicit agent
        rem ask contract-analyzer "Analyze this contract"

        # Process file
        rem ask contract-analyzer -i contract.pdf -o output.yaml
    """
    # Smart argument handling
    name = "rem"  # Default agent
    
    if query is None and not input_file:
        # Single argument provided
        # Heuristic: If it looks like a schema file or known agent, treat as name
        # Otherwise treat as query
        if name_or_query.endswith((".yaml", ".yml", ".json")) or name_or_query in ["rem", "query-agent", "rem-query-agent"]:
             # It's an agent name, query is missing (unless input_file)
             name = name_or_query
             # Query remains None, _ask_async will check input_file
        else:
             # It's a query, use default agent
             query = name_or_query
    elif query is not None:
        # Two arguments provided
        name = name_or_query

    # Resolve user_id from settings if not provided
    effective_user_id = user_id or settings.test.effective_user_id

    asyncio.run(
        _ask_async(
            name=name,
            query=query,
            model=model,
            temperature=temperature,
            max_turns=max_turns,
            version=version,
            stream=stream,
            user_id=effective_user_id,
            session_id=session_id,
            input_file=input_file,
            output_file=output_file,
            plan=plan,
        )
    )


async def _ask_async(
    name: str,
    query: str | None,
    model: str | None,
    temperature: float | None,
    max_turns: int,
    version: str | None,
    stream: bool,
    user_id: str,
    session_id: str | None,
    input_file: Path | None,
    output_file: Path | None,
    plan: bool,
):
    """Async implementation of ask command."""
    import uuid
    from ...agentic.context_builder import ContextBuilder

    # Validate input arguments
    if not query and not input_file:
        logger.error("Either QUERY argument or --input-file must be provided")
        sys.exit(1)

    if query and input_file:
        logger.error("Cannot use both QUERY argument and --input-file")
        sys.exit(1)

    # Load input from file if specified
    if input_file:
        logger.info(f"Loading input from file: {input_file}")
        query = await _load_input_file(input_file, user_id=user_id)

    # Load schema using centralized utility
    # Handles both file paths and schema names automatically
    # Falls back to database LOOKUP if not found in filesystem
    logger.info(f"Loading schema: {name} (version: {version or 'latest'})")
    try:
        schema = load_agent_schema(name, user_id=user_id)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    # Generate session ID if not provided
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.info(f"Generated session ID: {session_id}")

    # Build context with session history using ContextBuilder
    # This provides:
    # - System context message with date and user profile hints
    # - Compressed session history (if session exists)
    # - Proper message structure for agent
    logger.info(f"Building context for user {user_id}, session {session_id}")

    # Prepare new message for ContextBuilder
    new_messages = [{"role": "user", "content": query}]

    # Build context with session history
    context, messages = await ContextBuilder.build_from_headers(
        headers={
            "X-User-Id": user_id,
            "X-Session-Id": session_id,
        },
        new_messages=new_messages,
    )

    # Override model if specified via CLI flag
    if model:
        context.default_model = model

    logger.info(
        f"Creating agent: model={context.default_model}, stream={stream}, max_turns={max_turns}, messages={len(messages)}"
    )

    # Create agent
    agent = await create_agent(
        context=context,
        agent_schema_override=schema,
        model_override=model,
    )

    # Temperature is now handled in agent factory (schema override or settings default)
    if temperature is not None:
        logger.warning(
            f"CLI temperature override ({temperature}) not yet supported. "
            "Use agent schema 'override_temperature' field or LLM__DEFAULT_TEMPERATURE setting."
        )

    # Combine messages into single prompt
    # ContextBuilder already assembled: system context + history + new message
    prompt = "\n\n".join(msg.content for msg in messages)

    # Run agent with session persistence
    if stream:
        await run_agent_streaming(agent, prompt, max_turns=max_turns, context=context, user_message=query)
    else:
        await run_agent_non_streaming(
            agent,
            prompt,
            max_turns=max_turns,
            output_file=output_file,
            context=context,
            plan=plan,
        )

    # Log session ID for reuse
    logger.success(f"Session ID: {session_id} (use --session-id to continue this conversation)")


def register_command(parent_group):
    """Register ask command with parent CLI group."""
    parent_group.add_command(ask)
