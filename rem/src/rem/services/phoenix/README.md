# Phoenix Evaluation Framework for REM

Lean, two-phase evaluation system for REM agents using Arize Phoenix.

---

## Quick Start

### Prerequisites

```bash
# Port-forward Phoenix (if on Kubernetes)
kubectl port-forward -n observability svc/phoenix-svc 6006:6006

# Set API key
export PHOENIX_API_KEY=<your-api-key>

# Verify connection
rem experiments dataset list
```

### Two-Phase Workflow

**Phase 1: SME Creates Golden Set**
```bash
rem experiments dataset create rem-lookup-golden \
  --from-csv golden.csv \
  --input-keys query \
  --output-keys expected_label,expected_type \
  --metadata-keys difficulty,query_type
```

**Phase 2: Run Evaluation**
```bash
rem experiments run rem-lookup-golden \
  --agent ask_rem \
  --evaluator rem-lookup-correctness
```

**View Results**
```bash
open http://localhost:6006
```

---

## Architecture

### Two-Phase Evaluation Pattern

```
Phase 1: SME Golden Set Creation
├─ SMEs create (input, reference) pairs
├─ No agent execution required
└─ Stored in Phoenix for reuse

Phase 2: Automated Evaluation
├─ Run agents on golden sets → outputs
├─ Run evaluators → scores
└─ Track results in Phoenix
```

**Why Two Phases?**
- SMEs focus on domain knowledge (what's correct)
- Automation handles systematic testing (how well agents perform)
- Enables regression testing as agents evolve

### Components

```
Services (rem/src/rem/services/phoenix/)
├─ client.py - PhoenixClient for datasets/experiments
└─ config.py - Connection configuration

Providers (rem/src/rem/agentic/providers/phoenix.py)
├─ Evaluator factory (mirrors Pydantic AI pattern)
└─ Schema-based LLM-as-a-Judge evaluators

Evaluator Schemas (rem/schemas/evaluators/)
├─ Agent Evaluators (end-to-end)
│  ├─ rem-lookup-correctness.yaml
│  └─ rem-search-correctness.yaml
└─ RAG Evaluators (component-level)
   ├─ rem-retrieval-precision.yaml (RAGAS-inspired)
   ├─ rem-retrieval-recall.yaml (RAGAS-inspired)
   └─ rem-faithfulness.yaml (RAGAS-inspired)

CLI Commands (rem/src/rem/cli/commands/experiments.py)
├─ rem experiments dataset list/create/add
├─ rem experiments run
├─ rem experiments prompt list/create
└─ rem experiments trace list
```

---

## Evaluator Types

### Agent Evaluators (End-to-End)

Evaluate complete agent output quality.

**rem-lookup-correctness.yaml**
- Dimensions: Correctness, Completeness, Performance Contract
- Pass threshold: >= 0.75
- Use for: LOOKUP query evaluation

**rem-search-correctness.yaml**
- Dimensions: Relevance, Completeness, Ranking Quality
- Pass threshold: >= 0.70
- Use for: SEARCH query evaluation

### RAG Evaluators (Component-Level)

Evaluate retrieval layer independently (RAGAS concepts, no dependency).

**rem-retrieval-precision.yaml**
- Measures: Relevant entities / Total retrieved entities
- Evaluates ranking quality (are relevant items ranked high?)
- Inspired by RAGAS context_precision

**rem-retrieval-recall.yaml**
- Measures: Retrieved expected / Total expected entities
- Evaluates coverage (did we get all expected entities?)
- Inspired by RAGAS context_recall

**rem-faithfulness.yaml**
- Measures: Supported claims / Total claims in answer
- Detects hallucinations (agent making up info not in context)
- Inspired by RAGAS faithfulness

**Usage:**
```bash
# Evaluate retrieval quality
rem experiments run rem-search-golden \
  --agent ask_rem \
  --evaluator rem-retrieval-precision,rem-retrieval-recall

# Evaluate faithfulness
rem experiments run rem-lookup-golden \
  --agent ask_rem \
  --evaluator rem-faithfulness
```

---

## How Agents with Tools Work

**Phoenix doesn't "run" agents** - you provide task functions.

### Task Function Pattern

```python
# You write this
async def ask_rem_task(example: dict) -> dict:
    """Task function that Phoenix calls for each example."""
    query = example["input"]["query"]

    # Create agent with MCP tools
    agent = Agent(
        model="claude-sonnet-4-5",
        tools=[ask_rem, search_entities, lookup_entity]  # Your MCP tools
    )

    # Run agent (tools get called)
    result = await agent.run(query)

    # Return output (Phoenix stores this)
    return result.data.model_dump()

# Phoenix orchestrates
experiment = client.run_experiment(
    dataset="rem-lookup-golden",
    task=ask_rem_task,  # Phoenix calls this for each example
    evaluators=[correctness_evaluator]
)
```

### What Phoenix Does

1. **Orchestrates**: Calls your task function for each dataset example
2. **Observes**: Captures OTEL traces (agent execution + tool calls)
3. **Evaluates**: Runs evaluators on (input, output, expected)
4. **Tracks**: Stores results and scores in UI

### MCP Tools Configuration

Tools are specified in agent schemas:

```yaml
# rem/schemas/agents/ask-rem.yaml
json_schema_extra:
  tools:
    - name: ask_rem
      mcp_server: rem
      usage: "Execute REM queries (LOOKUP, SEARCH, TRAVERSE, SQL)"
```

When agent is created, `create_pydantic_ai_agent()`:
1. Reads agent schema
2. Loads MCP tools from `json_schema_extra.tools`
3. Connects to MCP server (FastMCP at `/api/v1/mcp`)
4. Registers tools with agent

### OTEL Traces

If instrumentation enabled (`settings.otel.enabled`):

```
Trace: experiment-run
├─ Span: agent_run (parent)
│  ├─ input: "LOOKUP person:sarah-chen"
│  └─ output: {"answer": "...", "entities": [...]}
├─ Span: tool_call.ask_rem (child)
│  ├─ input: {"query": "LOOKUP person:sarah-chen"}
│  └─ output: {"entities": [...]}
└─ Span: evaluation.correctness (sibling)
   ├─ scores: {"correctness": 0.95, "completeness": 0.88}
   └─ pass: true
```

Phoenix receives these spans and displays in UI.

---

## CLI Reference

### Dataset Commands

```bash
# List all datasets
rem experiments dataset list

# Create from CSV
rem experiments dataset create <name> \
  --from-csv golden.csv \
  --input-keys query \
  --output-keys expected_label,expected_type \
  --metadata-keys difficulty,query_type

# Add examples to existing dataset
rem experiments dataset add <name> \
  --from-csv new-examples.csv \
  --input-keys query \
  --output-keys expected_label,expected_type
```

### Experiment Commands

```bash
# Run agent only
rem experiments run <dataset> \
  --experiment <name> \
  --agent ask_rem

# Run evaluator only
rem experiments run <dataset> \
  --experiment <name> \
  --evaluator rem-lookup-correctness

# Run agent + evaluators
rem experiments run <dataset> \
  --experiment <name> \
  --agent ask_rem \
  --evaluator rem-lookup-correctness,rem-faithfulness
```

### Trace Commands

```bash
# List recent traces
rem experiments trace list --project rem-agents --days 7 --limit 50
```

---

## API Reference

### PhoenixClient

```python
from rem.services.phoenix import PhoenixClient

client = PhoenixClient()

# Dataset management
datasets = client.list_datasets()
dataset = client.get_dataset("rem-lookup-golden")
dataset = client.create_dataset_from_data(
    name="rem-test",
    inputs=[{"query": "LOOKUP person:sarah-chen"}],
    outputs=[{"label": "sarah-chen", "type": "person"}],
    metadata=[{"difficulty": "easy"}]
)

# Experiment execution
experiment = client.run_experiment(
    dataset="rem-lookup-golden",
    task=ask_rem_task,
    evaluators=[correctness_eval, faithfulness_eval],
    experiment_name="rem-v1"
)

# Trace retrieval
traces = client.get_traces(
    project_name="rem-agents",
    limit=50
)
```

### Evaluator Provider

```python
from rem.agentic.providers.phoenix import (
    create_evaluator_from_schema,
    load_evaluator_schema
)

# Load schema
schema = load_evaluator_schema("rem-lookup-correctness")

# Create evaluator
evaluator = create_evaluator_from_schema("rem-lookup-correctness")

# Use in experiment
result = evaluator({
    "input": {"query": "LOOKUP person:sarah-chen"},
    "output": {"label": "sarah-chen", ...},
    "expected": {"label": "sarah-chen", ...}
})
# Returns: {"score": 0.95, "label": "correct", "explanation": "..."}
```

---

## Best Practices

### Golden Set Quality

**Good:**
- Diverse examples (easy, medium, hard)
- Edge cases included
- Clear expected outputs
- Metadata for filtering

**Poor:**
- Only easy examples
- Ambiguous expected outputs
- No metadata
- Too small (< 10 examples)

### Evaluator Design

**Good:**
- Multiple dimensions (correctness, completeness, etc.)
- Clear scoring rubric
- Strict grading (catches hallucinations)
- Detailed feedback

**Poor:**
- Single dimension (just "score")
- Vague rubric
- Lenient grading
- No explanations

### Iterative Improvement

1. Create initial golden set (10-20 examples)
2. Run baseline evaluation
3. Identify failure modes
4. Add edge cases to golden set
5. Improve agent or prompts
6. Re-run evaluation
7. Compare results over time

**Track Progress:**
- Use versioned experiment names: `rem-v1-baseline`, `rem-v2-improved`
- Add metadata: `{"agent_version": "v2", "prompt_version": "2024-11-20"}`
- Compare scores in Phoenix UI

---

## Troubleshooting

### Connection Issues

**Problem:** "Connection refused"

```bash
# Check port-forward
lsof -i :6006

# Restart port-forward
kubectl port-forward -n observability svc/phoenix-svc 6006:6006
```

### Authentication Issues

**Problem:** "401 Unauthorized"

```bash
# Check API key
echo $PHOENIX_API_KEY

# Set if empty
export PHOENIX_API_KEY=<your-key>
```

### Dataset Not Found

```bash
# List all datasets (check spelling, case-sensitive)
rem experiments dataset list
```

### Evaluator Schema Not Found

```bash
# Check schema exists
ls rem/schemas/evaluators/

# Load without file extension
# ✓ "rem-lookup-correctness"
# ✗ "rem-lookup-correctness.yaml"
```

---

## Related Documentation

- [REM CLAUDE.md](../../../CLAUDE.md) - Overall REM architecture
- [Phoenix Official Docs](https://docs.arize.com/phoenix) - Phoenix platform
- [Carrier Evaluation](https://github.com/anthropics/carrier/docs/03-evaluation.md) - Inspiration for two-phase approach

---

## Summary

REM's Phoenix evaluation framework provides:

✅ **Two-phase workflow** - SMEs create golden sets, automation runs evaluations
✅ **Lean service layer** - Clean API for datasets/experiments
✅ **Evaluator provider** - Schema-based LLM-as-a-Judge pattern
✅ **CLI commands** - Simple workflow for creating datasets and running experiments
✅ **Comprehensive schemas** - Agent evaluators + RAG evaluators (RAGAS-inspired, no dependency)
✅ **Agent + Tools support** - OTEL tracing of MCP tool calls
✅ **Systematic tracking** - Phoenix integration for analysis over time

**Next Steps:**
1. Create your first golden set (`rem experiments dataset create`)
2. Run baseline evaluation (`rem experiments run`)
3. Iterate and improve agents
4. Track progress in Phoenix UI (`open http://localhost:6006`)
