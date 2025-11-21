# Agentic Chunking

Token-aware chunking for agent inputs that exceed model context windows.

## Overview

When processing large documents, datasets, or session histories with LLM agents, you may encounter context window limits. Agentic chunking solves this by:

1. **Splitting** large inputs into token-aware chunks
2. **Processing** each chunk independently with the same agent
3. **Merging** results using configurable strategies

## Key Features

- **Tiktoken Integration**: Exact token counting for OpenAI models
- **Character Heuristic Fallback**: ~4 chars/token estimate for other providers
- **Model Limits Database**: Pre-configured limits for GPT, Claude, Gemini
- **Smart Chunking**: Preserves line/word boundaries to avoid splitting mid-sentence
- **Merge Strategies**: Concatenate lists, deep merge JSON, or use LLM for intelligent merging

## Quick Start (Recommended: Smart Chunking)

```python
from rem.utils.agentic_chunking import (
    smart_chunk_text,  # Recommended - auto-sizes based on model
    merge_results,
    MergeStrategy,
)

# Smart chunking - automatically handles sizing
chunks = smart_chunk_text(cv_text, model="gpt-4o")

# For most CVs/resumes: chunks = [full_cv]  (no chunking needed!)
# For huge documents: automatically splits optimally

# Process each chunk with agent
results = []
for chunk in chunks:
    result = await agent.run(chunk)
    results.append(result.output.model_dump())  # Always serialize!

# Merge results (no-op if single chunk)
merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)
```

## Quick Start (Manual Chunking)

```python
from rem.utils.agentic_chunking import (
    chunk_text,
    merge_results,
    MergeStrategy,
    get_model_limits,
    estimate_tokens,
)

# Check model limits
limits = get_model_limits("gpt-4o")
print(f"Max input tokens: {limits.max_input}")  # 111616

# Estimate tokens in text
text_tokens = estimate_tokens(large_document, model="gpt-4o")
print(f"Document: {text_tokens} tokens")

# Chunk if necessary
if text_tokens > limits.max_input:
    chunks = chunk_text(large_document, max_tokens=100000, model="gpt-4o")
    print(f"Split into {len(chunks)} chunks")
else:
    chunks = [large_document]

# Process each chunk with agent
results = []
for i, chunk in enumerate(chunks):
    print(f"Processing chunk {i+1}/{len(chunks)}")
    result = await agent.run(chunk)
    results.append(result.output.model_dump())  # Always serialize!

# Merge results
merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)
```

## Model Limits

Pre-configured context limits for major LLM providers:

| Model | Max Context | Max Output | Max Input |
|-------|-------------|------------|-----------|
| gpt-4o | 128K | 16K | 112K |
| gpt-4o-mini | 128K | 16K | 112K |
| o1 | 200K | 100K | 100K |
| claude-sonnet-4 | 200K | 8K | 192K |
| claude-3-5-sonnet | 200K | 8K | 192K |
| gemini-2.0-flash-exp | 1M | 8K | 992K |
| gemini-1.5-pro | 2M | 8K | 1.992M |

**Fuzzy Matching**: Models are matched by family (e.g., "gpt-4o-2024-05-13" → gpt-4o limits)

## Smart vs Manual Chunking

### Smart Chunking (Recommended)

**Use `smart_chunk_text()` for automatic, intelligent chunking:**

```python
chunks = smart_chunk_text(text, model="gpt-4o")
```

**Benefits:**
- ✅ Automatically calculates optimal chunk size from model limits
- ✅ CVs/resumes fit in single chunk (no unnecessary splitting!)
- ✅ Accounts for system prompt overhead
- ✅ Configurable buffer ratio for safety
- ✅ Model-aware (adapts to GPT-4o, Claude, Gemini limits)

**When to use:**
- Processing user documents (CVs, reports, articles)
- When you want maximum utilization of model context
- When chunk size optimization is important

### Manual Chunking

**Use `chunk_text()` when you need explicit control:**

```python
chunks = chunk_text(text, max_tokens=1000, model="gpt-4o")
```

**Benefits:**
- ✅ Explicit control over chunk size
- ✅ Useful for testing with small chunks
- ✅ Good for constrained environments (rate limits, cost control)

**When to use:**
- Testing/development with small chunks
- Rate limit constraints (process X tokens/hour)
- Cost optimization (smaller chunks = predictable costs)
- Specific requirements (e.g., "split every 10K tokens")

### Comparison

| Feature | smart_chunk_text() | chunk_text() |
|---------|-------------------|--------------|
| **Chunk size** | Auto-calculated from model limits | Manual specification |
| **CV handling** | Single chunk (no splitting) | May split unnecessarily |
| **System prompt** | Automatically accounted | Must calculate manually |
| **Model-aware** | Yes (adapts to context windows) | No (fixed max_tokens) |
| **Buffer safety** | Configurable (default 75%) | Must calculate manually |
| **Use case** | Production, real documents | Testing, constraints |

## Token Estimation

### OpenAI Models (Exact)

Uses tiktoken for precise token counting:

```python
from rem.utils.agentic_chunking import estimate_tokens

tokens = estimate_tokens("Hello, world!", model="gpt-4o")
# Returns: 4 (exact count via tiktoken)
```

### Other Models (Heuristic)

Falls back to character-based estimation (~4 chars/token + 5% overhead):

```python
tokens = estimate_tokens("Hello, world!", model="claude-sonnet-4")
# Returns: 3 (heuristic estimate)
```

## Chunking Strategies

### Line-Preserving (Default)

Chunks by lines, preserving line boundaries:

```python
chunks = chunk_text(text, max_tokens=1000, model="gpt-4o", preserve_lines=True)
```

- Splits at `\n` boundaries
- Falls back to character chunking for oversized lines
- Best for structured text (code, markdown, logs)

### Character-Based

Chunks by characters with word boundary preservation:

```python
chunks = chunk_text(text, max_tokens=1000, model="gpt-4o", preserve_lines=False)
```

- Tries to break at spaces
- Useful for prose without newlines

## Merge Strategies

### 1. Concatenate List (Default)

**When to use**: Most structured extraction tasks (lists of items, entities, facts)

**Behavior**:
- Lists: Concatenate (`[1, 2]` + `[3, 4]` → `[1, 2, 3, 4]`)
- Dicts: Update (shallow merge)
- Scalars: Keep first non-None value

**Example**:
```python
results = [
    {"skills": ["Python", "SQL"], "experience_years": 5},
    {"skills": ["Docker", "K8s"], "experience_years": 3}
]

merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)
# {"skills": ["Python", "SQL", "Docker", "K8s"], "experience_years": 5}
```

### 2. Deep JSON Merge

**When to use**: Nested object structures with hierarchies

**Behavior**:
- Lists: Concatenate
- Dicts: Recursively deep merge
- Scalars: Keep first non-None value

**Example**:
```python
results = [
    {"contract": {"parties": ["Alice"], "terms": {"duration": "1 year"}}},
    {"contract": {"parties": ["Bob"], "terms": {"renewal": "auto"}}}
]

merged = merge_results(results, strategy=MergeStrategy.MERGE_JSON)
# {
#   "contract": {
#     "parties": ["Alice", "Bob"],
#     "terms": {"duration": "1 year", "renewal": "auto"}
#   }
# }
```

### 3. LLM Merge (TODO)

**When to use**: Complex semantic merging requiring intelligence

**Behavior**: Use LLM to intelligently merge results (not yet implemented)

## Real-World Examples

### Example 1: Extract Skills from Long CV

```python
from rem.utils.agentic_chunking import smart_chunk_text, merge_results, MergeStrategy
from rem.agentic.providers.pydantic_ai import create_pydantic_ai_agent

# Long CV document
cv_text = load_cv_file("john-doe-cv.txt")  # 5K tokens (typical CV)

# Smart chunking - automatically sizes based on model
# For typical CVs: will return single chunk (no splitting!)
chunks = smart_chunk_text(cv_text, model="gpt-4o")

print(f"Processing CV in {len(chunks)} chunk(s)")
# Output: Processing CV in 1 chunk(s)

# Create agent (using existing schema)
agent = await create_pydantic_ai_agent(
    context=context,
    agent_schema_uri="cv-parser-v1"
)

# Process each chunk
results = []
for i, chunk in enumerate(chunks):
    result = await agent.run(chunk)
    # CRITICAL: Serialize Pydantic models!
    results.append(result.output.model_dump())

# Merge extracted skills (no-op if single chunk)
merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)

print(f"Total skills found: {len(merged['skills'])}")
# Output: Total skills found: 12
```

### Example 2: Analyze Multi-Page Contract

```python
from rem.utils.agentic_chunking import smart_chunk_text, merge_results, MergeStrategy

# Large contract (120 pages, 80K tokens)
contract_text = load_contract("partnership-agreement.pdf")

# Smart chunking with system prompt awareness
system_prompt = """You are a contract analyzer. Extract parties, terms,
obligations, and risk flags from this legal agreement."""

chunks = smart_chunk_text(
    contract_text,
    model="claude-sonnet-4",  # 200K context
    system_prompt=system_prompt,
    buffer_ratio=0.75
)

print(f"Contract split into {len(chunks)} chunk(s)")
# For 80K tokens: likely 1 chunk (Claude has 200K context)

# Create contract analyzer agent
agent = await create_pydantic_ai_agent(
    context=context,
    agent_schema_uri="contract-analyzer-v1"
)

# Extract terms from each chunk
results = []
for chunk in chunks:
    result = await agent.run(chunk)
    results.append(result.output.model_dump())

# Deep merge nested contract structure
merged = merge_results(results, strategy=MergeStrategy.MERGE_JSON)

print(f"Parties: {merged['parties']}")
print(f"Key obligations: {len(merged['key_obligations'])}")
print(f"Risk flags: {len(merged['risk_flags'])}")
```

### Example 3: Process User Session History

```python
from rem.utils.agentic_chunking import chunk_text, estimate_tokens, get_model_limits

# User's full session history (many conversations)
session_history = load_user_sessions(user_id="user-123")  # 200K tokens

# Get limits for Gemini (large context)
limits = get_model_limits("gemini-1.5-pro")  # 1.992M tokens

# Check if chunking needed
history_tokens = estimate_tokens(session_history, model="gemini-1.5-pro")

if history_tokens <= limits.max_input:
    # Fits in one shot!
    result = await agent.run(session_history)
else:
    # Need to chunk
    chunks = chunk_text(session_history, max_tokens=500000, model="gemini-1.5-pro")

    results = []
    for chunk in chunks:
        result = await agent.run(chunk)
        results.append(result.output.model_dump())

    # Merge user profile insights
    merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)
```

## Integration with REM

### Ontology Extraction on Large Files

```python
from rem.utils.agentic_chunking import chunk_text, merge_results
from rem.services.ontology_extractor import extract_from_file

async def extract_from_large_file(
    file: File,
    schema: Schema,
    tenant_id: str
) -> Ontology:
    """Extract ontology from large file using chunking."""

    # Get model from schema provider_configs
    provider = schema.provider_configs[0] if schema.provider_configs else {}
    model = provider.get("model_name", "gpt-4o")

    # Chunk file content if needed
    limits = get_model_limits(model)
    chunks = chunk_text(file.content, max_tokens=int(limits.max_input * 0.75), model=model)

    if len(chunks) == 1:
        # Single chunk - normal extraction
        return await extract_from_file(file, schema, tenant_id)

    # Multi-chunk extraction
    results = []
    for chunk in chunks:
        # Create temporary file for chunk
        chunk_file = File(
            name=f"{file.name} (chunk)",
            content=chunk,
            mime_type=file.mime_type,
            tenant_id=tenant_id
        )

        # Extract from chunk
        result = await extract_from_file(chunk_file, schema, tenant_id)
        results.append(result.extracted_data)

    # Merge extracted data
    merged_data = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)

    # Create final ontology
    return Ontology(
        name=file.name,
        file_id=file.id,
        agent_schema_id=schema.id,
        provider_name=provider.get("provider_name"),
        model_name=model,
        extracted_data=merged_data,
        tenant_id=tenant_id
    )
```

### Dreaming Worker with Chunking

```python
from rem.utils.agentic_chunking import chunk_text, merge_results

async def extract_ontologies_with_chunking(
    user_id: str,
    lookback_hours: int = 24,
    limit: int | None = None
):
    """Extract ontologies with automatic chunking for large files."""

    # Load user's files
    files = await query_files(user_id, lookback_hours, limit)

    for file in files:
        # Find matching configs
        configs = await get_matching_configs(file, user_id)

        for config in configs:
            # Load schema
            schema = await load_schema(config.agent_schema_id, user_id)

            # Extract with chunking
            ontology = await extract_from_large_file(file, schema, user_id)

            # Generate embeddings
            embedding_text = extract_fields_for_embedding(
                ontology.extracted_data,
                schema.embedding_fields
            )
            ontology.embedding_text = embedding_text

            # Save
            await ontology_repo.upsert(ontology)
```

## Best Practices

### 1. Always Leave Buffer for System Prompt

```python
# BAD: Use full context window
chunks = chunk_text(text, max_tokens=limits.max_input, model="gpt-4o")

# GOOD: Leave buffer for system prompt, tools, etc.
chunks = chunk_text(text, max_tokens=int(limits.max_input * 0.75), model="gpt-4o")
```

### 2. Serialize Pydantic Models Before Merging

```python
# BAD: Merge Pydantic model instances directly
results = [result1.output, result2.output]  # Pydantic models
merged = merge_results(results)  # May lose fields!

# GOOD: Serialize first
results = [result1.output.model_dump(), result2.output.model_dump()]
merged = merge_results(results)  # All fields preserved
```

### 3. Choose Right Merge Strategy

```python
# Extracting list of items → CONCATENATE_LIST
skills = merge_results(skill_results, MergeStrategy.CONCATENATE_LIST)

# Nested hierarchy → MERGE_JSON
contract = merge_results(contract_results, MergeStrategy.MERGE_JSON)

# Complex semantic merging → LLM_MERGE (future)
summary = merge_results(summary_results, MergeStrategy.LLM_MERGE)
```

### 4. Handle Single Chunk Case

```python
chunks = chunk_text(text, max_tokens=100000, model="gpt-4o")

if len(chunks) == 1:
    # No chunking needed, faster path
    result = await agent.run(chunks[0])
    return result.output.model_dump()
else:
    # Multi-chunk processing
    results = [await agent.run(c) for c in chunks]
    return merge_results([r.output.model_dump() for r in results])
```

### 5. Respect Rate Limits

```python
import asyncio

# Process chunks with rate limiting
results = []
for i, chunk in enumerate(chunks):
    result = await agent.run(chunk)
    results.append(result.output.model_dump())

    # Wait between chunks (e.g., 1 second)
    if i < len(chunks) - 1:
        await asyncio.sleep(1.0)

merged = merge_results(results)
```

## Performance Considerations

### Token Estimation

- **OpenAI (tiktoken)**: Exact count, ~50ms for 10K tokens
- **Heuristic**: Instant but ~5-10% error margin

### Chunking

- **Line-preserving**: O(n) where n = number of lines
- **Character-based**: O(n) where n = text length
- Both are fast (< 1ms for 100K chars)

### Merging

- **Concatenate**: O(n*m) where n = results, m = avg fields
- **Deep merge**: O(n*m*d) where d = nesting depth
- Both are fast for typical result sizes (< 10ms for 100 results)

## Troubleshooting

### Issue: Chunks Still Too Large

**Symptom**: Agent fails with context length error despite chunking

**Solution**: Reduce buffer ratio or account for multi-turn conversation

```python
# If agent uses multiple tool calls (grows context)
chunks = chunk_text(text, max_tokens=int(limits.max_input * 0.5), model="gpt-4o")
```

### Issue: Lost Fields After Merge

**Symptom**: Fields disappear from merged results

**Solution**: Always serialize Pydantic models with `.model_dump()`

```python
# Before merging
results = [r.output.model_dump() for r in agent_results]
merged = merge_results(results)
```

### Issue: Wrong Token Count

**Symptom**: Estimate significantly off from actual usage

**Solution**: Use tiktoken for OpenAI, increase buffer for others

```python
# For OpenAI: tiktoken is exact
chunks = chunk_text(text, max_tokens=100000, model="gpt-4o")

# For others: use larger buffer (60-70% instead of 75%)
chunks = chunk_text(text, max_tokens=int(limits.max_input * 0.6), model="claude-sonnet-4")
```

## Future Enhancements

- [ ] LLM merge strategy implementation
- [ ] Async parallel chunk processing
- [ ] Progress tracking and cancellation
- [ ] Chunk caching to avoid re-processing
- [ ] Smart section-based chunking for markdown/HTML
- [ ] Integration with semchunk for semantic boundaries

## Related Documentation

- [CLAUDE.md](../../../../CLAUDE.md) - Core design patterns (Pattern #11)
- [agentic_chunking.py](./agentic_chunking.py) - Implementation
- [dict_utils.py](./dict_utils.py) - Field extraction utilities
- [serialization.py](../agentic/serialization.py) - Pydantic serialization helpers
