"""
Helper functions for REM Query Agent.

This module provides convenience functions that load the REM Query Agent
from YAML schema and execute queries.
"""

from typing import Any

from pydantic import BaseModel

from .context import AgentContext
from .providers.pydantic_ai import create_agent_from_schema_file


class REMQueryOutput(BaseModel):
    """
    REM Query Agent structured output.

    Matches the schema defined in schemas/agents/core/rem-query-agent.yaml
    """

    query: str
    confidence: float
    reasoning: str = ""


async def ask_rem(
    natural_query: str,
    user_id: str = "system",
    llm_model: str | None = None,
) -> REMQueryOutput:
    """
    Convert natural language query to structured REM query.

    Loads the REM Query Agent from YAML schema and executes the query.

    Args:
        natural_query: User's question in natural language
        user_id: User ID for context (defaults to "system")
        llm_model: Optional LLM model override

    Returns:
        REMQueryOutput with query, confidence, and reasoning

    Example:
        result = await ask_rem("Show me Sarah Chen")
        # REMQueryOutput(
        #     query="LOOKUP sarah-chen",
        #     confidence=1.0,
        #     reasoning=""
        # )
    """
    # Create context (only pass default_model if llm_model is provided)
    context_kwargs = {"user_id": user_id}
    if llm_model is not None:
        context_kwargs["default_model"] = llm_model
    context = AgentContext(**context_kwargs)

    # Load agent from YAML schema
    agent = await create_agent_from_schema_file(
        schema_name_or_path="rem-query-agent",
        context=context,
        model_override=llm_model,  # type: ignore[arg-type]
    )

    # Run query
    result = await agent.run(natural_query)

    # Handle different Pydantic AI versions
    if hasattr(result, "data"):
        output = result.data
    elif hasattr(result, "output"):
        output = result.output
    else:
        output = result

    # Convert to REMQueryOutput if not already
    if isinstance(output, dict):
        return REMQueryOutput(**output)
    elif isinstance(output, REMQueryOutput):
        return output
    else:
        # Fallback: try to extract fields
        return REMQueryOutput(
            query=getattr(output, "query", str(output)),
            confidence=getattr(output, "confidence", 0.5),
            reasoning=getattr(output, "reasoning", ""),
        )
