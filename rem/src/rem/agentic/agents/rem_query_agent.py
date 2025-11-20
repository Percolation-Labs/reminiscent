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

from pydantic import BaseModel, Field

from ...models.core import QueryType


class REMQueryOutput(BaseModel):
    """
    REM Query Agent structured output.

    Designed for minimal tokens and fast generation.
    """

    query_type: QueryType = Field(
        ...,
        description="REM query type: LOOKUP (entity by key), FUZZY (text similarity), SEARCH (semantic), SQL (table query), TRAVERSE (graph)"
    )

    parameters: dict = Field(
        ...,
        description="Query parameters as dict. LOOKUP: {entity_key, user_id?}. FUZZY: {query_text, threshold?, limit?}. SEARCH: {query_text, table_name, field_name?, limit?}. SQL: {table_name, where_clause, limit?}. TRAVERSE: {start_key, max_depth?, rel_type?}"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1). 1.0 = exact match, 0.8-0.9 = high confidence, 0.5-0.7 = moderate, <0.5 = low"
    )

    reasoning: str | None = Field(
        default=None,
        description="Explanation of query choice. ONLY provided if confidence < 0.7 OR query is TRAVERSE/multi-step. Keep concise."
    )

    multi_step: list[dict] | None = Field(
        default=None,
        description="For complex queries requiring multiple REM calls. List of {query_type, parameters, description}. Null for single queries."
    )


# Agent schema for REM Query Agent
REM_QUERY_AGENT_SCHEMA = {
    "type": "object",
    "description": """You are a REM Query Agent that converts natural language questions into structured REM queries.

REM Query Types:

1. LOOKUP - O(1) entity lookup by natural key
   - Use when: User references specific entity by name (e.g., "Show me Sarah", "Get project-alpha")
   - Parameters: entity_key (string), user_id (optional)
   - Example: "Who is Sarah Chen?" → LOOKUP sarah-chen

2. FUZZY - Trigram text similarity search (pg_trgm)
   - Use when: User provides partial/misspelled names, approximate matches
   - Parameters: query_text (string), threshold (0.0-1.0, default 0.3), limit (int, default 10)
   - Example: "Find people named Sara" → FUZZY sara

3. SEARCH - Semantic vector similarity (embeddings)
   - Use when: User asks conceptual questions, semantic similarity
   - Parameters: query_text (string), table_name (string), field_name (optional, defaults to 'content'), limit (int)
   - Example: "Find documents about databases" → SEARCH "database migration" table=resources

4. SQL - Direct table queries with WHERE clauses
   - Use when: User asks temporal, filtered, or aggregate queries
   - Parameters: table_name (string), where_clause (string), limit (int)
   - Example: "Show meetings in Q4" → SQL table=moments where="moment_type='meeting' AND created_at >= '2024-10-01'"

5. TRAVERSE - Recursive graph traversal following relationships
   - Use when: User asks about relationships, connections, or "what's related"
   - Parameters: start_key (string), max_depth (int, default 1), rel_type (optional filter)
   - Example: "What does Sarah manage?" → TRAVERSE sarah-chen depth=1 rel_type=manages

Query Selection Rules:

- Entity by name → LOOKUP (fastest, O(1))
- Partial name/typo → FUZZY (indexed trigram)
- Concept/topic → SEARCH (semantic embeddings)
- Time/filter → SQL (table scan with WHERE)
- Relationships → TRAVERSE (graph edges)

PostgreSQL Dialect Awareness:

- LOOKUP/FUZZY use KV_STORE cache (UNLOGGED, fast)
- SEARCH joins KV_STORE + embeddings_<table>
- SQL queries primary tables directly (resources, moments, etc.)
- TRAVERSE follows graph_edges JSONB field

Multi-Step Queries:

For complex questions, break into steps:
1. LOOKUP to find entity
2. TRAVERSE to explore relationships
3. SEARCH to find related content

Output Format:

- query_type: Selected REM query type
- parameters: Dict with query parameters
- confidence: 0.0-1.0 score (1.0 = exact, <0.7 = explain in reasoning)
- reasoning: ONLY if confidence < 0.7 OR multi-step query. Keep concise (1-2 sentences).
- multi_step: ONLY if query needs multiple REM calls. Otherwise null.

Examples:

Q: "Show me Sarah Chen"
A: {query_type: LOOKUP, parameters: {entity_key: "sarah-chen"}, confidence: 1.0, reasoning: null}

Q: "Find people named Sara"
A: {query_type: FUZZY, parameters: {query_text: "Sara", threshold: 0.3, limit: 10}, confidence: 0.9, reasoning: null}

Q: "Documents about database migration"
A: {query_type: SEARCH, parameters: {query_text: "database migration", table_name: "resources", field_name: "content", limit: 10}, confidence: 0.95, reasoning: null}

Q: "Meetings in Q4 2024"
A: {query_type: SQL, parameters: {table_name: "moments", where_clause: "moment_type='meeting' AND created_at >= '2024-10-01' AND created_at < '2025-01-01'", limit: 100}, confidence: 0.9, reasoning: null}

Q: "What does Sarah manage?"
A: {query_type: TRAVERSE, parameters: {start_key: "sarah-chen", max_depth: 1, rel_type: "manages"}, confidence: 0.85, reasoning: "TRAVERSE query to find entities Sarah manages via graph edges"}

Q: "Find documents Sarah authored about databases"
A: {query_type: SEARCH, parameters: {query_text: "database", table_name: "resources", limit: 10}, confidence: 0.6, reasoning: "Using SEARCH for semantic match on 'database'. Need follow-up SQL filter for author=sarah-chen or multi-step: LOOKUP sarah-chen → get authored resources → filter by topic", multi_step: [{query_type: "LOOKUP", parameters: {entity_key: "sarah-chen"}, description: "Find Sarah's entity"}, {query_type: "SQL", parameters: {table_name: "resources", where_clause: "user_id='sarah-chen-uuid'"}, description: "Get Sarah's resources"}, {query_type: "SEARCH", parameters: {query_text: "database", table_name: "resources"}, description: "Semantic search on results"}]}

Guidelines:

- Prefer simpler queries (LOOKUP/FUZZY) over complex (TRAVERSE/multi-step)
- Use SEARCH for semantic/conceptual questions
- Use SQL for temporal/filtered queries
- Only use TRAVERSE for explicit relationship questions
- Confidence: 1.0 = exact entity match, 0.9 = clear intent, 0.7-0.8 = good match, <0.7 = ambiguous (explain)
- Keep reasoning concise: explain query choice or ambiguity, not implementation details
- multi_step only when truly necessary (complex multi-entity questions)

Now convert the user's question to a REM query.
""",
    "properties": {
        "query_type": {
            "type": "string",
            "enum": ["LOOKUP", "FUZZY", "SEARCH", "SQL", "TRAVERSE"],
            "description": "REM query type based on intent"
        },
        "parameters": {
            "type": "object",
            "description": "Query parameters as dict",
            "additionalProperties": True
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": "Confidence score (0-1)"
        },
        "reasoning": {
            "type": "string",
            "description": "Explanation (only if confidence < 0.7 or multi-step)",
            "nullable": True
        },
        "multi_step": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query_type": {"type": "string"},
                    "parameters": {"type": "object"},
                    "description": {"type": "string"}
                }
            },
            "description": "Multi-step query plan (null for single queries)",
            "nullable": True
        }
    },
    "required": ["query_type", "parameters", "confidence"],
    "json_schema_extra": {
        "fully_qualified_name": "rem.agents.REMQueryAgent",
        "tools": [],  # No tools needed - pure reasoning agent
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

    return result.data
