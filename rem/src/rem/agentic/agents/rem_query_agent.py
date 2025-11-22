"""
REM Query Agent - Converts natural language to REM queries.

This agent:
1. Analyzes user intent from natural language
2. Determines optimal REM query type (LOOKUP, FUZZY, SEARCH, SQL, TRAVERSE)
3. Generates structured REM query with parameters
4. Returns concise output with confidence score
5. Explains reasoning for low confidence (<0.7)

PostgreSQL Dialect Awareness:
- Knows when to use KV_STORE (LOOKUP/FUZZY) vs primary tables (SQL)
- Understands when vector search (SEARCH) is needed vs text search (FUZZY)
- Can compose multi-step queries with TRAVERSE for graph exploration

Output Design:
- Minimal tokens for fast generation and low cost
- Structured output for easy parsing
- Explanations only for low confidence or complex queries
"""

from typing import Any

from pydantic import BaseModel, Field

from ...models.core import QueryType


class REMQueryOutput(BaseModel):
    """
    REM Query Agent structured output.

    Simplified to 3 primitive values for Cerebras Qwen compatibility.
    """

    query: str = Field(
        description="Generated REM query string in natural syntax. Examples: 'LOOKUP sarah-chen', 'SEARCH database table=resources', 'FUZZY Sara threshold=0.3'"
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1). 1.0 = exact match, 0.8-0.9 = high confidence, 0.5-0.7 = moderate, <0.5 = low"
    )

    reasoning: str = Field(
        default="",
        description="Explanation only if confidence < 0.7. Otherwise empty string."
    )


# Agent schema for REM Query Agent
REM_QUERY_AGENT_SCHEMA = {
    "type": "object",
    "description": """You are a REM Query Agent that converts natural language to REM query strings.

REM Query Syntax:

1. LOOKUP <entity-key> - O(1) entity lookup by natural key
   Example: "Show me Sarah Chen" → LOOKUP sarah-chen

2. FUZZY <text> [threshold=0.3] [limit=10] - Trigram text similarity
   Example: "Find people named Sara" → FUZZY Sara threshold=0.3 limit=10

3. SEARCH <query> table=<name> [field=content] [limit=10] - Semantic vector search
   Example: "Documents about databases" → SEARCH database table=resources limit=10

4. SQL table=<name> where=<clause> [limit=100] - Direct table query
   Example: "Meetings in Q4" → SQL table=moments where="moment_type='meeting' AND created_at>='2024-10-01'" limit=100

5. TRAVERSE <entity-key> [depth=1] [rel_type=<type>] - Graph traversal
   Example: "What does Sarah manage?" → TRAVERSE sarah-chen depth=1 rel_type=manages

Query Selection:
- Entity by name → LOOKUP (fastest)
- Partial/typo → FUZZY
- Concept/topic → SEARCH
- Time/filter → SQL
- Relationships → TRAVERSE

Examples:

Q: "Show me Sarah Chen"
A: {query: "LOOKUP sarah-chen", confidence: 1.0, reasoning: ""}

Q: "Find people named Sara"
A: {query: "FUZZY Sara", confidence: 0.9, reasoning: ""}

Q: "Documents about database migration"
A: {query: "SEARCH database migration table=resources", confidence: 0.95, reasoning: ""}

Q: "Meetings in Q4 2024"
A: {query: "SQL table=moments where=\"moment_type='meeting' AND created_at>='2024-10-01' AND created_at<'2025-01-01'\"", confidence: 0.9, reasoning: ""}

Q: "What does Sarah manage?"
A: {query: "TRAVERSE sarah-chen rel_type=manages", confidence: 0.85, reasoning: ""}

Guidelines:
- Confidence: 1.0 = exact, 0.9 = clear, 0.7-0.8 = good, <0.7 = explain in reasoning
- Only provide reasoning if confidence < 0.7
- Keep queries simple and concise
""",
    "properties": {
        "query": {
            "type": "string",
            "description": "REM query string in natural syntax"
        },
        "confidence": {
            "type": "number",
            "description": "Confidence score (0-1)"
        },
        "reasoning": {
            "type": "string",
            "description": "Explanation (only if confidence < 0.7)",
            "default": ""
        }
    },
    "required": ["query", "confidence"],
    "additionalProperties": False,
    "json_schema_extra": {
        "fully_qualified_name": "rem.agents.REMQueryAgent",
        "tools": [],
        "resources": []
    }
}


async def create_rem_query_agent(
    llm_provider: str | None = None,
    llm_model: str | None = None
):
    """
    Create REM Query Agent for natural language to REM query conversion.

    Args:
        llm_provider: LLM provider (defaults to settings.llm.default_model)
        llm_model: LLM model override

    Returns:
        Configured Pydantic AI Agent
    """
    from ...agentic.providers.pydantic_ai import create_pydantic_ai_agent
    from ...agentic.context import AgentContext
    from ...settings import settings

    # Determine model
    if llm_model:
        model = llm_model
    elif llm_provider:
        model = llm_provider
    else:
        # Check for query_agent specific setting, otherwise use default
        model = getattr(settings.llm, 'query_agent_model', None) or settings.llm.default_model

    # Create context
    context = AgentContext(
        default_model=model,
        tenant_id="system",  # Query agent is system-level
    )

    # Create agent with schema
    agent = await create_pydantic_ai_agent(
        context=context,
        agent_schema_override=REM_QUERY_AGENT_SCHEMA,
        result_type=REMQueryOutput,
        strip_model_description=True,
    )

    return agent


async def ask_rem(
    natural_query: str,
    llm_provider: str | None = None,
    llm_model: str | None = None
) -> REMQueryOutput:
    """
    Convert natural language query to structured REM query.

    Args:
        natural_query: User's question in natural language
        llm_provider: Optional LLM provider override
        llm_model: Optional LLM model override

    Returns:
        REMQueryOutput with query_type, parameters, confidence, reasoning

    Example:
        result = await ask_rem("Show me Sarah Chen")
        # REMQueryOutput(
        #     query_type=QueryType.LOOKUP,
        #     parameters={"entity_key": "sarah-chen"},
        #     confidence=1.0,
        #     reasoning=None
        # )
    """
    agent = await create_rem_query_agent(llm_provider, llm_model)

    result = await agent.run(natural_query)

    # Handle different Pydantic AI versions
    if hasattr(result, "data"):
        return result.data
    elif hasattr(result, "output"):
        return result.output
    else:
        return result
