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
    agent, query_text: str, max_turns: int = 10
) -> None:
    """
    Run agent in streaming mode using agent.iter().

    Design Pattern (from carrier):
    - Use agent.iter() for complete execution with tool call visibility
    - run_stream() stops after first output, missing tool calls
    - Stream tool call markers: [Calling: tool_name]
    - Stream text content deltas as they arrive
    - Show final structured result

    Args:
        agent: Pydantic AI agent
        query_text: User query
        max_turns: Maximum turns for agent execution (not used in current API)
    """
    logger.info("Running agent in streaming mode...")

    # Create query object
    query = AgentQuery(query=query_text)
    prompt = query.to_prompt()

    try:
        # Import event types for streaming
        from pydantic_ai import Agent as PydanticAgent
        from pydantic_ai.messages import PartStartEvent, PartDeltaEvent, TextPartDelta, ToolCallPart

        # Use agent.iter() to get complete execution with tool calls
        async with agent.iter(prompt) as agent_run:
            async for node in agent_run:
                # Check if this is a model request node (includes tool calls and text)
                if PydanticAgent.is_model_request_node(node):
                    # Stream events from model request
                    async with node.stream(agent_run.ctx) as request_stream:
                        async for event in request_stream:
                            # Tool call start event
                            if isinstance(event, PartStartEvent) and isinstance(
                                event.part, ToolCallPart
                            ):
                                print(f"\n[Calling: {event.part.tool_name}]", flush=True)

                            # Text content delta
                            elif isinstance(event, PartDeltaEvent) and isinstance(
                                event.delta, TextPartDelta
                            ):
                                print(event.delta.content_delta, end="", flush=True)

        print("\n")  # Final newline after streaming

        # Get final result from agent_run
        result = agent_run.result
        if hasattr(result, "output"):
            logger.info("Final structured result:")
            output = result.output
            from rem.agentic.serialization import serialize_agent_result
            print(json.dumps(serialize_agent_result(output), indent=2))

    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        raise


async def run_agent_non_streaming(
    agent, query_text: str, max_turns: int = 10, output_file: Path | None = None
) -> dict[str, Any] | None:
    """
    Run agent in non-streaming mode using agent.run().

    Args:
        agent: Pydantic AI agent
        query_text: User query
        max_turns: Maximum turns for agent execution (not used in current API)
        output_file: Optional path to save output

    Returns:
        Output data if successful, None otherwise
    """
    logger.info("Running agent in non-streaming mode...")

    # Create query object
    query = AgentQuery(query=query_text)
    prompt = query.to_prompt()

    try:
        # Run agent and get complete result
        result = await agent.run(prompt)

        # Extract output data
        output_data = None
        if hasattr(result, "output"):
            output = result.output
            from rem.agentic.serialization import serialize_agent_result
            output_data = serialize_agent_result(output)
            print(json.dumps(output_data, indent=2))
        else:
            # Fallback for text-only results
            print(result)

        # Save to file if requested
        if output_file and output_data:
            await _save_output_file(output_file, output_data)

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
@click.argument("name")
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
    default="cli-user",
    help="User ID for context (default: cli-user)",
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
def ask(
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
):
    """
    Run an agent with a query or file input.

    NAME is the agent schema name (YAML files in schemas/agents/):
    - Short name: "contract-analyzer" → schemas/agents/contract-analyzer.yaml
    - With extension: "contract-analyzer.yaml" → schemas/agents/contract-analyzer.yaml
    - Full path also works: "schemas/agents/contract-analyzer.yaml"

    QUERY is the user query (optional if --input-file is used).

    Examples:
        # Simple query
        rem ask simple-agent "What is 2+2?"

        # Process file
        rem ask contract-analyzer -i contract.pdf -o output.yaml

        # With specific model
        rem ask query-agent "Find documents" -m openai:gpt-4o

        # Streaming mode
        rem ask simple-agent "Hello" --stream
    """
    asyncio.run(
        _ask_async(
            name=name,
            query=query,
            model=model,
            temperature=temperature,
            max_turns=max_turns,
            version=version,
            stream=stream,
            user_id=user_id,
            session_id=session_id,
            input_file=input_file,
            output_file=output_file,
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
):
    """Async implementation of ask command."""
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
    logger.info(f"Loading schema: {name} (version: {version or 'latest'})")
    try:
        schema = load_agent_schema(name)
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)

    # Create agent context
    context = AgentContext(
        user_id=user_id,
        tenant_id=user_id,  # Set tenant_id to user_id for backward compat
        session_id=session_id,
        default_model=model or settings.llm.default_model,
    )

    logger.info(
        f"Creating agent: model={context.default_model}, stream={stream}, max_turns={max_turns}"
    )

    # Create agent
    agent = await create_agent(
        context=context,
        agent_schema_override=schema,
        model_override=model,
    )

    # TODO: Apply temperature override
    # Pydantic AI doesn't have a direct temperature parameter on agent
    # Would need to be passed to run() call or set via model config
    if temperature is not None:
        logger.warning(
            f"Temperature override ({temperature}) not yet implemented. "
            "Using model default or schema config."
        )

    # Run agent
    if stream:
        await run_agent_streaming(agent, query, max_turns=max_turns)
    else:
        await run_agent_non_streaming(agent, query, max_turns=max_turns, output_file=output_file)


def register_command(parent_group):
    """Register ask command with parent CLI group."""
    parent_group.add_command(ask)
