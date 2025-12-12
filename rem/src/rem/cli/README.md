# REM CLI - Agent Testing Guide

## Overview

The `rem ask` command provides a CLI interface for testing Pydantic AI agents with YAML-based schemas. It supports both streaming and non-streaming modes, structured output, and optional OTEL/Phoenix instrumentation.

## Installation

```bash
# Install REM with all dependencies
cd /Users/sirsh/code/mr_saoirse/remstack/rem
uv pip install -e .

# Verify installation
rem --help
```

## Basic Usage

```bash
# Simple question (non-streaming by default)
rem ask simple "What is 2+2?"

# Streaming mode for real-time output
rem ask simple "What is 2+2?" --stream

# With specific model
rem ask simple "What is 2+2?" --model openai:gpt-4o-mini

# Structured output
rem ask query "Find all documents by Sarah" --model openai:gpt-4o-mini

# Process file and save output
rem ask contract-analyzer -i rem/tests/data/content-examples/service_agreement.txt -o output.yaml
```

## File Processing

The `--input-file` option allows you to process files directly instead of providing a text query:

```bash
# Extract data from contract (text file)
rem ask contract-analyzer \
  -i rem/tests/data/content-examples/service_agreement.txt \
  -o output.yaml

# Extract from PDF contract
rem ask contract-analyzer \
  -i rem/tests/data/content-examples/pdf/service_contract.pdf \
  -o output.yaml

# With specific model
rem ask contract-analyzer \
  -i rem/tests/data/content-examples/service_agreement.txt \
  -o output.yaml \
  -m anthropic:claude-sonnet-4-5-20250929

# Output to console (default)
rem ask contract-analyzer -i rem/tests/data/content-examples/service_agreement.txt

# Stream output in real-time
rem ask contract-analyzer -i rem/tests/data/content-examples/service_agreement.txt --stream
```

**Schema name resolution:**
- Short names: `contract-analyzer` → `schemas/agents/examples/contract-analyzer.yaml`
- With folder: `examples/contract-analyzer` → `schemas/agents/examples/contract-analyzer.yaml`
- Core agents: `moment-builder` → `schemas/agents/core/moment-builder.yaml`
- Full paths: `schemas/agents/examples/contract-analyzer.yaml` (as-is)
```

**Supported file types:**
- Documents: PDF, DOCX, PPTX, XLSX (via Kreuzberg)
- Text: TXT, MD, Markdown, code files
- Schemas: YAML, JSON
- Audio: MP3, WAV, M4A (via Whisper API)

See [examples/README.md](../../../examples/README.md) for complete contract extraction examples.
```

## Command Options

```
rem ask NAME [QUERY] [OPTIONS]

Arguments:
  NAME   Agent schema name (YAML files in schemas/agents/)
         - Short name: contract-analyzer → schemas/agents/examples/contract-analyzer.yaml
         - With folder: examples/contract-analyzer → schemas/agents/examples/contract-analyzer.yaml
         - Core agent: moment-builder → schemas/agents/core/moment-builder.yaml
         - Full path: schemas/agents/examples/contract-analyzer.yaml

  QUERY  User query to send to the agent (optional if --input-file is used)

Options:
  --model, -m TEXT            LLM model (default: from settings)
  --temperature, -t FLOAT     Temperature 0.0-1.0 (not yet implemented)
  --max-turns INTEGER         Maximum turns for execution (default: 10)
  --version, -v TEXT          Schema version for registry lookup
  --stream / --no-stream      Enable/disable streaming (default: disabled)
  --input-file, -i PATH       Read input from file (PDF, TXT, Markdown, etc.)
  --output-file, -o PATH      Write output to file (YAML format)
  --user-id TEXT              User ID for context (default: cli-user)
  --session-id TEXT           Session ID for context (default: auto-generated)
```

## Agent Schema Format

Agent schemas are YAML files following JSON Schema with embedded metadata:

```yaml
type: object
description: |
  System prompt for the agent.

  This describes what the agent does and how it should behave.

properties:
  answer:
    type: string
    description: The response to the user's query

  confidence:
    type: number
    minimum: 0
    maximum: 1
    description: Confidence score for the response

required:
  - answer

json_schema_extra:
  fully_qualified_name: "rem.agents.SimpleAgent"
  version: "1.0.0"
  tools: []        # MCP tool configurations (future)
  resources: []    # MCP resource configurations (future)
```

## Example Schemas

### Simple Agent (`schemas/agents/examples/simple.yaml`)

A basic conversational agent that returns simple text answers:

```yaml
type: object
description: |
  A simple conversational agent that provides helpful, friendly responses.

  You are a helpful AI assistant. Answer questions clearly and concisely.
  If you don't know something, say so. Be friendly and professional.

properties:
  answer:
    type: string
    description: The response to the user's query

required:
  - answer

json_schema_extra:
  fully_qualified_name: "rem.agents.SimpleAgent"
  version: "1.0.0"
  tools: []
  resources: []
```

### Query Agent (`schemas/agents/examples/query.yaml`)

An agent that provides structured output with confidence scores:

```yaml
type: object
description: |
  REM Query Agent - Converts natural language questions to REM queries.

  You are a specialized agent that understands REM (Resources Entities Moments) queries.
  Your job is to interpret user questions and provide answers with confidence scores.

properties:
  answer:
    type: string
    description: The answer to the user's query with supporting details

  confidence:
    type: number
    minimum: 0
    maximum: 1
    description: Confidence score (0.0-1.0) for this answer

  query_type:
    type: string
    enum:
      - LOOKUP
      - FUZZY
      - TRAVERSE
      - UNKNOWN
    description: The type of REM query that would best answer this question

required:
  - answer
  - confidence
  - query_type

json_schema_extra:
  fully_qualified_name: "rem.agents.QueryAgent"
  version: "1.0.0"
  tools: []
  resources: []
```

## Streaming vs Non-Streaming

### Non-Streaming Mode (default)

Uses `agent.run()` to return complete structured result at once:

```bash
rem ask simple "Explain quantum computing"
```

Output:
```json
{
  "answer": "Quantum computing uses quantum mechanical phenomena..."
}
```

**Best for:**
- Saving output to files
- Structured data extraction
- Processing files with complex schemas
- Programmatic usage

### Streaming Mode

Uses `agent.iter()` to stream events in real-time:
- Tool call markers: `[Calling: tool_name]`
- Text content deltas as they arrive
- Final structured result after completion

```bash
rem ask simple "Explain quantum computing" --stream
```

Output:
```
[Calling: final_result]
Quantum computing uses quantum mechanical phenomena like superposition...

{
  "answer": "Quantum computing uses quantum mechanical phenomena..."
}
```

**Best for:**
- Interactive conversations
- Long-running queries where you want to see progress
- Debugging agent behavior

## Implementation Details

### Architecture

```
CLI (ask.py)
  ├── load_schema_from_file() - YAML file loading
  ├── load_schema_from_registry() - TODO: Database/cache lookup
  ├── run_agent_streaming() - agent.iter() with event streaming
  └── run_agent_non_streaming() - agent.run() for complete result

Agent Factory (providers/pydantic_ai.py)
  ├── create_pydantic_ai_agent() - Main factory
  ├── _create_model_from_schema() - JSON Schema → Pydantic model
  └── _create_schema_wrapper() - Strip description for LLM

OTEL (otel/setup.py)
  ├── setup_instrumentation() - Initialize OTLP exporters
  └── set_agent_resource_attributes() - Set span attributes
```

### Design Patterns

1. **JsonSchema to Pydantic Pattern**
   - Agent schemas are JSON Schema with embedded metadata
   - `description` field becomes system prompt
   - `properties` field becomes Pydantic output model
   - Dynamic model creation using `json-schema-to-pydantic`

2. **Streaming with agent.iter() Pattern**
   - Use `agent.iter()` for complete execution (not `run_stream()`)
   - `agent.iter()` captures tool calls, `run_stream()` stops after first output
   - Stream tool call events with `[Calling: tool_name]` markers
   - Stream text content deltas as they arrive

3. **Conditional OTEL Instrumentation**
   - OTEL disabled by default for local development
   - Enabled in production via `OTEL__ENABLED=true`
   - Applied at agent creation time: `Agent(..., instrument=settings.otel.enabled)`

## Environment Variables

Set API keys for LLM providers:

```bash
# In ~/.bash_profile or ~/.zshrc
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Optional: OTEL/Phoenix configuration
export OTEL__ENABLED=true
export OTEL__SERVICE_NAME=rem-cli
export OTEL__COLLECTOR_ENDPOINT=http://localhost:4318
export PHOENIX__ENABLED=true
export PHOENIX__COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
```

## Observability (Optional)

### OTEL Configuration

Enable distributed tracing with OpenTelemetry:

```bash
# Enable OTEL
export OTEL__ENABLED=true
export OTEL__SERVICE_NAME=rem-cli
export OTEL__COLLECTOR_ENDPOINT=http://localhost:4318
export OTEL__PROTOCOL=http

# Run agent with tracing
rem ask query "Find documents" --model openai:gpt-4o-mini
```

### Phoenix Integration

Enable LLM observability with Arize Phoenix:

```bash
# Start Phoenix locally
docker run -p 6006:6006 arizephoenix/phoenix:latest

# Enable Phoenix
export PHOENIX__ENABLED=true
export PHOENIX__COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces
export PHOENIX__PROJECT_NAME=rem-cli

# Run agent with Phoenix tracing
rem ask query "Find documents" --model openai:gpt-4o-mini

# View traces at http://localhost:6006
```

## Schema Registry (TODO)

The schema registry is stubbed but not yet implemented. To implement:

1. **Database Schema**:
   ```sql
   CREATE TABLE agent_schemas (
     id UUID PRIMARY KEY,
     name TEXT NOT NULL,
     version TEXT NOT NULL,
     schema_json JSONB NOT NULL,
     created_at TIMESTAMPTZ DEFAULT NOW(),
     UNIQUE(name, version)
   );
   ```

2. **Cache Layer**:
   - Redis for fast lookups
   - In-memory cache for CLI

3. **Versioning**:
   - Semantic versioning (1.0.0, 1.1.0, etc.)
   - Latest version fallback

Once implemented, you can load agents by name:

```bash
# Load latest version
rem ask query "Find documents"

# Load specific version
rem ask query "Find documents" --version 1.2.0
```

## Testing

```bash
# Test simple agent (default non-streaming)
rem ask simple "What is 2+2?" --model openai:gpt-4o-mini

# Test simple agent (streaming)
rem ask simple "What is 2+2?" --stream --model openai:gpt-4o-mini

# Test structured output
rem ask query "Find all documents by Sarah" --model openai:gpt-4o-mini

# Test file processing
rem ask contract-analyzer -i examples/contract.pdf -o output.yaml

# Test with different models
rem ask simple "Hello" --model openai:gpt-4o
rem ask simple "Hello" --model anthropic:claude-sonnet-4-5-20250929
```

## Troubleshooting

### API Key Not Found

```bash
# Set API key in environment
export OPENAI_API_KEY="sk-..."

# Or source your profile
source ~/.bash_profile
```

### Schema Registry Not Implemented

```
Schema registry not implemented yet. Please use a file path instead.
```

Use file paths until registry is implemented:
```bash
rem ask simple "query"
```

### Model Not Found

Ensure you're using the correct model format:
- OpenAI: `openai:gpt-4o-mini`, `openai:gpt-4o`
- Anthropic: `anthropic:claude-sonnet-4-5-20250929`

## Data Visibility: PUBLIC vs PRIVATE

**IMPORTANT: All ingested data is PUBLIC by default.** This is the correct behavior
for shared knowledge bases (ontologies, procedures, reference data).

### Why PUBLIC by Default?

Most data in REM should be searchable by all users:
- Clinical ontologies (disorders, symptoms, drugs)
- Procedures and protocols (SCID-5, PHQ-9, etc.)
- Reference documentation
- Shared domain knowledge

The `rem_lookup()` function searches for data where `user_id IS NULL`, which means
public data. If you set `user_id` on data, it becomes invisible to other users.

### Ingesting Public Data (Default)

```bash
# Standard ingestion - data is PUBLIC
rem process ingest ontology/procedures/ --table ontologies

# From S3 - also PUBLIC
rem process ingest s3://bucket/docs/reference.pdf
```

### Ingesting Private Data (Rare)

Private data requires explicit `--make-private` flag:

```bash
# Private user data - requires --make-private and --user-id
rem process ingest personal-notes.md --make-private --user-id user-123
```

**When to use private data:**
- User-uploaded personal documents
- Session-specific content
- User notes and annotations

**NEVER use private data for:**
- Ontologies and reference material
- Clinical procedures and protocols
- Shared knowledge bases
- Anything that should be searchable by agents

### Common Mistake

If agents can't find data via `search_rem`, the most common cause is that the data
was ingested with a `user_id` set. Check with:

```sql
SELECT name, user_id FROM ontologies WHERE name = 'phq-9-procedure';
-- user_id should be NULL for public data
```

Fix by setting user_id to NULL:
```sql
UPDATE ontologies SET user_id = NULL WHERE user_id IS NOT NULL;
UPDATE kv_store SET user_id = NULL WHERE entity_type = 'ontologies' AND user_id IS NOT NULL;
```

## Next Steps

1. **Implement Schema Registry**
   - PostgreSQL table for schema storage
   - Redis cache for fast lookups
   - Version management

2. **Add MCP Tool Support**
   - Dynamic tool loading from schema
   - MCP server configuration

3. **Temperature Override**
   - Pass temperature to agent.run()
   - Model-specific settings

4. **CLI Improvements**
   - Interactive mode
   - Multi-turn conversations
   - Session management
