# REM Agentic Framework

This folder contains the core agentic framework for REM, providing a provider-agnostic abstraction for building and executing AI agents with structured outputs, MCP tool integration, and observability.

## Architecture Overview

```
agentic/
├── README.md                    # This file
├── context.py                   # AgentContext - session and configuration
├── query.py                     # AgentQuery - structured agent input
├── agents/                      # Built-in agents
│   └── rem_query_agent.py      # Natural language to REM query conversion
└── providers/
    └── pydantic_ai.py          # Pydantic AI agent factory
```

## Core Concepts

### 1. Agent Schemas (JSON Schema)

Agent schemas are **JSON Schema documents** that define both the agent's behavior AND structured output format. This design pattern comes from the `carrier` project and provides several key advantages:

- **Single source of truth**: One schema defines prompt, output structure, and tool configuration
- **Framework-agnostic**: JSON Schema can be converted to any framework's format
- **Tooling support**: JSON Schema validators, editors, and documentation generators work out of the box

#### Agent Schema Structure

```json
{
  "type": "object",
  "description": "SYSTEM PROMPT: This description becomes the agent's system prompt. Explain the agent's purpose, capabilities, and behavioral guidelines here.",
  "properties": {
    "answer": {
      "type": "string",
      "description": "The query answer with supporting evidence"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Confidence score for the answer"
    },
    "sources": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Entity keys used as evidence"
    }
  },
  "required": ["answer", "confidence"],
  "json_schema_extra": {
    "fully_qualified_name": "rem.agents.QueryAgent",
    "tools": [
      {"name": "lookup_entity", "mcp_server": "rem"},
      {"name": "search_knowledge", "mcp_server": "rem"}
    ],
    "resources": [
      {"uri_pattern": "rem://resources/.*", "mcp_server": "rem"}
    ]
  }
}
```

#### Key Schema Sections

##### `description` - System Prompt
The top-level `description` field contains the **system prompt** for the agent. This is where you define:
- Agent's role and purpose
- Behavioral guidelines
- Task-specific instructions
- Output formatting requirements

##### `properties` - Structured Output Fields
The `properties` section defines the **structured output schema**. Each property:
- Has a JSON Schema type (`string`, `number`, `array`, `object`, etc.)
- Has a `description` explaining what the field should contain
- May have validation constraints (`minimum`, `maximum`, `pattern`, etc.)

##### `json_schema_extra` - Metadata and Tools
The `json_schema_extra` section contains:

- **`fully_qualified_name`**: Python module path for the agent (e.g., `rem.agents.QueryAgent`)
- **`tools`**: MCP tools available to the agent
  ```json
  {
    "name": "lookup_entity",
    "mcp_server": "rem",
    "description": "Optional override description"
  }
  ```
- **`resources`**: MCP resources accessible to the agent
  ```json
  {
    "uri_pattern": "rem://resources/.*",
    "mcp_server": "rem"
  }
  ```

### 2. Pydantic AI Integration

The `providers/pydantic_ai.py` module converts JSON Schema agents to Pydantic AI format.

#### JSON Schema → Pydantic Model Conversion

Pydantic AI requires a Pydantic `BaseModel` for structured output. We convert JSON Schema to Pydantic using the `json-schema-to-pydantic` library:

```python
from json_schema_to_pydantic import PydanticModelBuilder

builder = PydanticModelBuilder()
OutputModel = builder.create_pydantic_model(
    agent_schema,
    root_schema=agent_schema
)
```

This handles:
- Nested objects
- Arrays and validation constraints
- Required fields
- Type conversions (JSON Schema types → Python types)

#### Pydantic Docstrings vs JSON Schema Descriptions

**Important Design Pattern**: Pydantic converts docstrings to JSON Schema `description` fields:

```python
class QueryOutput(BaseModel):
    """Agent output with answer and confidence."""  # ← This becomes schema description
    answer: str = Field(description="The query answer")
    confidence: float = Field(ge=0, le=1)
```

When sent to the LLM, the Pydantic model's **docstring duplicates the system prompt** (already in `schema.description`). To avoid redundancy and reduce token usage:

**We STRIP the model-level description from the response schema**:

```python
def _create_schema_wrapper(result_type: type[BaseModel], strip_description: bool = True):
    """Strip model docstring from schema sent to LLM."""
    if not strip_description:
        return result_type

    class SchemaWrapper(result_type):
        @classmethod
        def model_json_schema(cls, **kwargs):
            schema = super().model_json_schema(**kwargs)
            schema.pop("description", None)  # Remove top-level description
            return schema

    return SchemaWrapper
```

**Why this matters**:
- JSON Schema `description` → System prompt (tells agent WHAT to do)
- Pydantic model schema → Response format (tells agent HOW to structure output)
- Stripping the model description prevents sending the same instructions twice

### 3. MCP Tool Integration

REM agents **only support MCP (Model Context Protocol) tools and resources**. This design decision provides:

- **Standardization**: All tools use the same protocol
- **Interoperability**: MCP tools work across different agent frameworks
- **Simplicity**: Single integration point instead of framework-specific tool APIs

#### Tool Configuration

Tools are declared in `json_schema_extra.tools`:

```json
{
  "tools": [
    {
      "name": "lookup_entity",
      "mcp_server": "rem",
      "description": "Optional override for tool description"
    }
  ]
}
```

The `mcp_server` value maps to environment variables:
- `rem` → `MCP_SERVER_REM` (e.g., `http://rem-mcp:8000`)
- `search` → `MCP_SERVER_SEARCH`

#### Resource Configuration

Resources are MCP's way of exposing retrievable content:

```json
{
  "resources": [
    {
      "uri_pattern": "rem://resources/.*",
      "mcp_server": "rem"
    }
  ]
}
```

Resources are converted to tool calls by the provider factory.

### 4. Agent Context

`AgentContext` (defined in `context.py`) provides session and configuration for agent execution:

```python
class AgentContext(BaseModel):
    user_id: str | None           # User identifier
    tenant_id: str                # Tenant for multi-tenancy (REM requirement)
    session_id: str | None        # Conversation/session ID
    default_model: str            # LLM model name
    agent_schema_uri: str | None  # Schema reference (e.g., "rem-agents-query-agent")
```

#### Context Headers

Contexts can be constructed from HTTP headers:

| Header | Field | Example |
|--------|-------|---------|
| `X-User-Id` | `user_id` | `user123` |
| `X-Tenant-Id` | `tenant_id` | `acme-corp` |
| `X-Session-Id` | `session_id` | `sess-456` |
| `X-Model-Name` | `default_model` | `anthropic:claude-sonnet-4-5-20250929` |
| `X-Agent-Schema` | `agent_schema_uri` | `rem-agents-query-agent` |

```python
context = AgentContext.from_headers(request.headers)
agent = await create_pydantic_ai_agent(context)
```

### 5. Agent Query

`AgentQuery` (defined in `query.py`) provides structured input for agent execution:

```python
class AgentQuery(BaseModel):
    query: str          # Primary user question/task
    knowledge: str      # Retrieved context (markdown + fenced JSON)
    scratchpad: str | dict  # Working memory for multi-turn reasoning
```

Example usage:

```python
query = AgentQuery(
    query="Find all documents Sarah authored",
    knowledge="""
    # Entity: sarah-chen
    Type: person/employee
    Role: Senior Engineer
    Projects: [Project Alpha, TiDB Migration]
    """,
    scratchpad={"stage": "entity_lookup", "visited": ["sarah-chen"]}
)

prompt = query.to_prompt()
result = await agent.run(prompt)
```

## Provider Factories

### Pydantic AI Provider

The `providers/pydantic_ai.py` module is the reference implementation:

```python
agent = await create_pydantic_ai_agent(
    context=context,                    # Optional: AgentContext with session info
    agent_schema_override=schema,       # Optional: Explicit schema (bypasses context.agent_schema_uri)
    model_override="claude-opus-4",     # Optional: Model override
    result_type=OutputModel,            # Optional: Pydantic model for output
    strip_model_description=True        # Strip docstring from response schema
)
```

**Key Implementation Details**:

1. **Schema Loading**: Loads agent schema from `context.agent_schema_uri` or uses `agent_schema_override`
2. **System Prompt**: Extracted from `schema.description`
3. **Dynamic Model**: Converts `schema.properties` to Pydantic model using `json-schema-to-pydantic`
4. **MCP Tools**: Loads tools from `schema.json_schema_extra.tools`
5. **OTEL Instrumentation**: Conditionally enabled via `settings.otel.enabled`

### Provider Interface

The framework is designed to support multiple agent frameworks if needed. Each provider implements the same interface:
- Input: JSON Schema + AgentContext
- Output: Framework-specific agent instance
- Responsibilities: Schema conversion, tool loading, model configuration

## Evaluators

Evaluators follow the **same pattern as agents** - they are JSON Schema documents that define:
- Evaluation criteria (in `description`)
- Structured evaluation output (in `properties`)
- Tools needed for evaluation (in `json_schema_extra`)

### Evaluator Schema Example

```json
{
  "type": "object",
  "description": "Evaluate agent responses for accuracy and completeness. Check if the answer correctly uses the provided evidence and addresses all aspects of the query.",
  "properties": {
    "accuracy_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "How accurate is the answer based on evidence"
    },
    "completeness_score": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Does the answer address all parts of the query"
    },
    "reasoning": {
      "type": "string",
      "description": "Explanation of scores"
    }
  },
  "required": ["accuracy_score", "completeness_score", "reasoning"],
  "json_schema_extra": {
    "fully_qualified_name": "rem.evaluators.AccuracyEvaluator",
    "evaluation_type": "accuracy"
  }
}
```

### Phoenix Integration (TODO)

Arize Phoenix supports OpenTelemetry-based LLM observability. Evaluators can be registered with Phoenix to:

1. **Trace Evaluation**: Automatically evaluate traced agent runs
2. **Dataset Evaluation**: Batch evaluate against test datasets
3. **Dashboard Integration**: View evaluation metrics in Phoenix UI

Example integration pattern:

```python
# TODO: Implement in future
from phoenix.evals import run_evals
from .providers.pydantic_ai import create_pydantic_ai_agent

# Load evaluator schema
evaluator_schema = load_schema("rem-evaluators-accuracy")

# Create evaluator agent
evaluator = await create_pydantic_ai_agent(
    agent_schema_override=evaluator_schema
)

# Register with Phoenix
run_evals(
    dataframe=traces_df,
    evaluators=[evaluator],
    provide_explanation=True
)
```

## Testing

### Example Agent Schemas

Test agent schemas live in `tests/data/agents/`:

```
tests/
└── data/
    └── agents/
        ├── query_agent.json          # Example query agent
        ├── summarization_agent.json  # Example summarization agent
        └── evaluators/
            └── accuracy_evaluator.json
```

### Unit Tests

Unit tests for agent conversion are in `tests/unit/agentic/providers/`:

```python
# tests/unit/agentic/providers/test_pydantic_ai.py
import pytest
from rem.agentic.providers.pydantic_ai import create_pydantic_ai_agent

@pytest.mark.asyncio
async def test_agent_from_schema(query_agent_schema):
    """Test creating Pydantic AI agent from JSON Schema."""
    agent = await create_pydantic_ai_agent(
        agent_schema_override=query_agent_schema
    )

    assert agent is not None
    assert agent.system_prompt == query_agent_schema["description"]
    # Test structured output, tools, etc.
```

## Design Principles

1. **JSON Schema as Source of Truth**: All agent definitions start as JSON Schema
2. **Provider Agnostic**: Framework-specific implementations in `providers/`
3. **MCP Only**: Standardize on MCP for tool/resource integration
4. **Description Stripping**: Prevent prompt duplication in structured output schemas
5. **Evaluators = Agents**: Use same pattern for evaluation as for agent execution
6. **Observable by Default**: OTEL instrumentation built into agent factories

## Usage Example

```python
from rem.agentic.context import AgentContext
from rem.agentic.query import AgentQuery
from rem.agentic.providers.pydantic_ai import create_pydantic_ai_agent

# 1. Load agent schema
schema = {
    "type": "object",
    "description": "Answer REM queries using LOOKUP and TRAVERSE operations...",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    },
    "required": ["answer", "confidence"],
    "json_schema_extra": {
        "tools": [{"name": "lookup_entity", "mcp_server": "rem"}]
    }
}

# 2. Create context
context = AgentContext(
    user_id="user123",
    tenant_id="acme-corp",
    session_id="sess-456"
)

# 3. Create agent
agent = await create_pydantic_ai_agent(
    context=context,
    agent_schema_override=schema
)

# 4. Build query
query = AgentQuery(
    query="Who manages Project Alpha?",
    knowledge="# Recent LOOKUP results\n...",
    scratchpad={"stage": "initial_lookup"}
)

# 5. Execute
result = await agent.run(query.to_prompt())

print(result.data.answer)
print(f"Confidence: {result.data.confidence}")
```

## Built-in Agents

### REM Query Agent

The REM Query Agent converts natural language questions into structured REM queries. It's a specialized agent that understands the PostgreSQL dialect and knows when to use different query types.

**Location**: `rem/agentic/agents/rem_query_agent.py`

**Usage**:

```python
from rem.agentic.agents import ask_rem

# Simple usage
result = await ask_rem("Show me Sarah Chen")
# REMQueryOutput(
#     query_type=QueryType.LOOKUP,
#     parameters={"entity_key": "sarah-chen"},
#     confidence=1.0,
#     reasoning=None
# )

# With custom model
result = await ask_rem(
    "Find documents about databases",
    llm_model="gpt-4o-mini"
)
# REMQueryOutput(
#     query_type=QueryType.SEARCH,
#     parameters={
#         "query_text": "database",
#         "table_name": "resources",
#         "field_name": "content",
#         "limit": 10
#     },
#     confidence=0.95,
#     reasoning=None
# )
```

**Query Types**:

- `LOOKUP` - O(1) entity lookup by natural key (fastest)
- `FUZZY` - Trigram text similarity (pg_trgm) for partial/misspelled names
- `SEARCH` - Semantic vector similarity using embeddings
- `SQL` - Direct table queries with WHERE clauses for temporal/filtered queries
- `TRAVERSE` - Recursive graph traversal for relationship exploration

**Settings**:

```python
# In .env or environment variables
LLM__QUERY_AGENT_MODEL=gpt-4o-mini  # Fast, cheap model for query generation
```

If `query_agent_model` is not set, the agent uses `settings.llm.default_model`.

**Design**:

- Token-optimized output (minimal fields)
- Reasoning only provided when confidence < 0.7 or multi-step queries
- PostgreSQL dialect aware (knows about KV_STORE, embeddings tables)
- Can generate multi-step query plans for complex questions

## Future Work

- [ ] Phoenix evaluator integration
- [ ] Agent schema registry (load schemas by URI)
- [ ] Schema validation and versioning
- [ ] Multi-turn conversation management
- [ ] Agent composition (agents calling agents)
- [ ] Alternative provider implementations (if needed)
