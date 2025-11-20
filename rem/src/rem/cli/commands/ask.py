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
from ...agentic.providers.pydantic_ai import create_pydantic_ai_agent
from ...agentic.query import AgentQuery
from ...settings import settings


async def load_schema_from_file(file_path: Path) -> dict[str, Any]:
    """
    Load agent schema from YAML file.

    Args:
        file_path: Path to YAML file containing agent schema

    Returns:
        Agent schema as dictionary

    Example YAML:
        type: object
        description: "Agent that answers queries about documents"
        properties:
          answer:
            type: string
            description: "The answer to the query"
          confidence:
            type: number
            minimum: 0
            maximum: 1
        required:
          - answer
          - confidence
        json_schema_extra:
          fully_qualified_name: "rem.agents.QueryAgent"
          tools: []
          resources: []
    """
    import yaml

    if not file_path.exists():
        raise FileNotFoundError(f"Schema file not found: {file_path}")

    with open(file_path, "r") as f:
        schema = yaml.safe_load(f)

    logger.debug(f"Loaded schema from {file_path}: {list(schema.keys())}")
    return schema


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
            if hasattr(output, "model_dump"):
                print(json.dumps(output.model_dump(), indent=2))
            else:
                print(output)

    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        raise


async def run_agent_non_streaming(
    agent, query_text: str, max_turns: int = 10
) -> None:
    """
    Run agent in non-streaming mode using agent.run().

    Args:
        agent: Pydantic AI agent
        query_text: User query
        max_turns: Maximum turns for agent execution (not used in current API)
    """
    logger.info("Running agent in non-streaming mode...")

    # Create query object
    query = AgentQuery(query=query_text)
    prompt = query.to_prompt()

    try:
        # Run agent and get complete result
        result = await agent.run(prompt)

        # Display result
        logger.info("Agent result:")
        # AgentRunResult has different attributes based on whether result_type is set
        if hasattr(result, "output"):
            output = result.output
            if hasattr(output, "model_dump"):
                print(json.dumps(output.model_dump(), indent=2))
            else:
                print(output)
        else:
            # Fallback for text-only results
            print(result)

    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        raise


@click.command()
@click.argument("name")
@click.argument("query")
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
    default=True,
    help="Enable streaming mode (default: enabled)",
)
@click.option(
    "--user-id",
    default="cli-user",
    help="User ID for context (default: cli-user)",
)
@click.option(
    "--tenant-id",
    default="default",
    help="Tenant ID for context (default: default)",
)
@click.option(
    "--session-id",
    default=None,
    help="Session ID for context (default: auto-generated)",
)
def ask(
    name: str,
    query: str,
    model: str | None,
    temperature: float | None,
    max_turns: int,
    version: str | None,
    stream: bool,
    user_id: str,
    tenant_id: str,
    session_id: str | None,
):
    """
    Test Pydantic AI agent with query.

    NAME can be either:
    - A schema name (e.g., "query-agent") - loads from registry
    - A file path (e.g., "schemas/query-agent.yaml") - loads from file

    QUERY is the user query to send to the agent.

    Examples:
        rem ask query-agent "Find all documents by Sarah"
        rem ask schemas/query-agent.yaml "What is the weather?" --model gpt-4o
        rem ask my-agent "Hello" --stream --temperature 0.7 --max-turns 5
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
            tenant_id=tenant_id,
            session_id=session_id,
        )
    )


async def _ask_async(
    name: str,
    query: str,
    model: str | None,
    temperature: float | None,
    max_turns: int,
    version: str | None,
    stream: bool,
    user_id: str,
    tenant_id: str,
    session_id: str | None,
):
    """Async implementation of ask command."""
    # Determine if name is a file path or schema name
    name_path = Path(name)
    if name_path.exists() and name_path.suffix in [".yaml", ".yml", ".json"]:
        logger.info(f"Loading schema from file: {name_path}")
        schema = await load_schema_from_file(name_path)
    else:
        logger.info(f"Loading schema from registry: {name} (version: {version or 'latest'})")
        try:
            schema = await load_schema_from_registry(name, version=version)
        except NotImplementedError as e:
            logger.error(str(e))
            sys.exit(1)

    # Create agent context
    context = AgentContext(
        user_id=user_id,
        tenant_id=tenant_id,
        session_id=session_id,
        default_model=model or settings.llm.default_model,
    )

    logger.info(
        f"Creating agent: model={context.default_model}, stream={stream}, max_turns={max_turns}"
    )

    # Create agent
    agent = await create_pydantic_ai_agent(
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
        await run_agent_non_streaming(agent, query, max_turns=max_turns)


def register_command(parent_group):
    """Register ask command with parent CLI group."""
    parent_group.add_command(ask)
