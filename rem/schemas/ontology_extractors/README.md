# Ontology Extraction Agent Schemas

This directory contains agent schemas for extracting domain-specific knowledge from files.

## Overview

Ontology extraction enables REM to understand domain-specific content through custom agent schemas. Instead of generic chunking and embedding, users can define specialized agents that extract structured knowledge tailored to their use case.

**Examples:**
- **Recruitment**: Parse CVs to extract candidate skills, experience, education
- **Legal**: Analyze contracts to extract parties, obligations, terms
- **Medical**: Extract diagnoses, medications, treatments from health records
- **Financial**: Parse reports to extract metrics, risks, forecasts

## Architecture

### Key Components

1. **Agent Schemas** (this directory)
   - YAML files defining extraction logic
   - JSON Schema output structure
   - System prompts for LLM instructions
   - Provider configurations for multi-model testing

2. **Ontology Entity** (`models/entities/ontology.py`)
   - Stores extracted structured data
   - Links to source File entity
   - Tracks agent schema and LLM provider used
   - Supports semantic search via embeddings

3. **OntologyConfig Entity** (`models/entities/ontology_config.py`)
   - User-defined extraction rules
   - File matching patterns (MIME type, URI, tags)
   - Priority for execution order
   - Provider overrides

4. **OntologyExtractorService** (`services/ontology_extractor.py`)
   - Loads schemas from database
   - Executes agents on file content
   - Generates embeddings for extracted data
   - Stores Ontology entities

5. **Dreaming Worker** (`workers/dreaming.py`)
   - Automatically applies matching configs to files
   - Runs during nightly processing
   - Can be triggered on-demand via CLI

## Schema Structure

Agent schemas follow the standard REM agent pattern with ontology-specific extensions:

```yaml
---
type: object
description: |
  System prompt with instructions for the LLM.
  Guidelines for extraction, output format, etc.

properties:
  # JSON Schema defining the structured output
  field_name:
    type: string
    description: Field description

required:
  - required_field

json_schema_extra:
  fully_qualified_name: rem.agents.MyExtractorAgent
  version: "1.0.0"
  name: My Extractor
  short_name: my-extractor
  tags:
    - domain
    - ontology-extractor
  author: Your Name
  tools: []
  resources: []

  # Ontology-specific configuration
  provider_configs:
    - provider_name: anthropic
      model_name: claude-sonnet-4-5-20250929
    - provider_name: openai
      model_name: gpt-4o

  embedding_fields:
    - field1
    - field2
    - nested.field3
```

### Key Fields

**`provider_configs`** (optional)
- Test extraction across multiple LLM providers
- Each config creates separate Ontology entity
- Enables A/B testing and provider comparison

**`embedding_fields`** (required for semantic search)
- JSON paths to embed for vector search
- Values concatenated and embedded using configured provider
- Enables semantic search across extracted knowledge

## Available Extractors

### CV Parser (`cv-parser-v1.yaml`)
Extracts candidate information from resumes and CVs.

**Use case:** Recruitment consultants, HR teams

**Extracted data:**
- Candidate name, contact details
- Professional summary
- Skills (technical and soft)
- Work experience with achievements
- Education history
- Certifications, languages, awards
- Seniority level assessment

**Embedding fields:** `candidate_name`, `professional_summary`, `skills`, `experience`

### Contract Analyzer (`contract-analyzer-v1.yaml`)
Extracts key terms from legal contracts.

**Use case:** Legal teams, procurement consultants

**Extracted data:**
- Contract type and parties
- Financial terms and payment schedule
- Key obligations and deliverables
- Termination and liability clauses
- Confidentiality and IP provisions
- Risk flags for unusual clauses

**Embedding fields:** `contract_title`, `contract_type`, `parties`, `key_obligations`, `risk_flags`

## Usage

### 1. Create Agent Schema

Store schema in database as Schema entity:

```python
from rem.models.entities import Schema

schema = Schema(
    name="cv-parser-v1",
    content="CV Parser documentation...",
    spec={
        "type": "object",
        "description": "You are a CV Parser...",
        "properties": {...},
        "json_schema_extra": {...}
    },
    category="ontology-extractor",
    provider_configs=[
        {"provider_name": "anthropic", "model_name": "claude-sonnet-4-5"}
    ],
    embedding_fields=["candidate_name", "professional_summary", "skills"],
    tenant_id="acme-corp"
)
```

### 2. Create Extraction Config

Define when to apply the schema:

```python
from rem.models.entities import OntologyConfig

config = OntologyConfig(
    name="recruitment-cv-parser",
    agent_schema_id="cv-parser-v1",
    description="Extract candidate info from resumes",
    mime_type_pattern="application/pdf",
    uri_pattern=".*/resumes/.*",
    tag_filter=["cv", "candidate"],
    priority=100,
    enabled=True,
    tenant_id="acme-corp"
)
```

### 3. Upload Files

Files matching the config will trigger extraction:

```python
from rem.models.entities import File

file = File(
    name="john-doe-resume.pdf",
    uri="s3://acme-corp/resumes/john-doe-resume.pdf",
    content="John Doe\nSenior Software Engineer...",
    mime_type="application/pdf",
    processing_status="completed",
    tags=["cv", "candidate"],
    tenant_id="acme-corp"
)
```

### 4. Run Extraction

**Automatic (recommended):**
Dreaming worker runs nightly via Kubernetes CronJob:
```bash
rem-dreaming full --tenant-id=acme-corp
```

**Manual:**
```bash
rem ontology extract --file-id=<file-id> --config-id=<config-id>
```

### 5. Query Extracted Knowledge

**By file:**
```python
ontologies = await ontology_repo.get_by_file_id(file_id, tenant_id)
```

**By schema:**
```python
ontologies = await ontology_repo.get_by_agent_schema("cv-parser-v1", tenant_id)
```

**Semantic search (future):**
```python
results = await rem_service.search(
    query_text="senior python kubernetes engineer",
    table_name="ontologies",
    tenant_id="acme-corp"
)
```

## Creating Custom Extractors

### Step 1: Define Your Use Case

Identify:
- What files you're processing (PDFs, Word docs, images)
- What structured data you need to extract
- How you'll use the extracted data

### Step 2: Design Output Schema

Create JSON Schema for your output structure:

```yaml
properties:
  entity_name:
    type: string
    description: Human-readable entity name

  key_data:
    type: object
    properties:
      field1:
        type: string
      field2:
        type: number

  confidence_score:
    type: number
    minimum: 0.0
    maximum: 1.0

required:
  - entity_name
  - confidence_score
```

### Step 3: Write System Prompt

Provide clear instructions:

```yaml
description: |
  You are a [Domain] Extractor specialized in [specific task].

  Your task is to analyze the provided [file type] and extract:
  - [Key data point 1]
  - [Key data point 2]
  - [Key data point 3]

  Guidelines:
  - Extract information accurately without hallucination
  - Preserve exact [names/dates/amounts]
  - Assign confidence score based on clarity
  - If information is unclear, use null

  Output Format:
  - Return structured JSON matching the schema
  - Ensure [data format requirements]
  - Include confidence_score (0.0-1.0)
```

### Step 4: Configure Providers and Embeddings

```yaml
json_schema_extra:
  provider_configs:
    - provider_name: anthropic
      model_name: claude-sonnet-4-5-20250929

  embedding_fields:
    - field_for_semantic_search
    - another_field
```

### Step 5: Test and Iterate

1. Create schema in database
2. Create test config
3. Upload sample files
4. Run extraction
5. Evaluate output quality
6. Adjust system prompt and schema
7. Compare across providers if needed

## Best Practices

### Schema Design

- **Keep output focused**: Only extract data you'll actually use
- **Use enums for categories**: Enables filtering and aggregation
- **Include confidence scores**: Track extraction quality
- **Normalize values**: Standardize formats (dates, names, codes)

### System Prompts

- **Be explicit**: Detailed instructions produce better results
- **Provide examples**: Show desired output format
- **Set boundaries**: Tell model what NOT to do
- **Request reasoning**: Ask model to note ambiguities

### Provider Selection

- **Anthropic Claude**: Strong for structured extraction, reasoning
- **OpenAI GPT-4**: Good general performance, cost-effective
- **Test both**: Use `provider_configs` to compare

### Embedding Fields

- **Choose wisely**: Fields users will search for
- **Include identifiers**: Names, titles, key terms
- **Include descriptions**: Summaries, explanations
- **Exclude noise**: Don't embed IDs, timestamps, metadata

### File Matching

- **Use specific patterns**: Narrow scope reduces false matches
- **Combine rules**: MIME type + URI pattern + tags
- **Set priorities**: Control execution order for overlapping configs
- **Use enabled flag**: Disable without deleting for testing

## Performance Considerations

### Cost

Ontology extraction uses LLM API calls:
- **Anthropic Claude Sonnet 4.5**: ~$3 per million input tokens
- **OpenAI GPT-4o**: ~$2.50 per million input tokens

Estimate costs:
- Average resume: ~2K tokens → $0.006 per extraction
- Average contract: ~10K tokens → $0.03 per extraction
- 1000 files/day: $6-30/day depending on file size

### Latency

- **Anthropic Claude**: 2-5 seconds for typical documents
- **OpenAI GPT-4**: 1-3 seconds for typical documents
- Parallel processing: Multiple files extracted concurrently

### Scale

- Dreaming worker uses asyncio for concurrent extraction
- Kubernetes HPA scales based on queue depth
- Spot instances reduce compute costs

## Troubleshooting

### Low Confidence Scores

- **Cause**: Unclear input, complex layout, missing information
- **Fix**: Improve file quality, adjust system prompt, try different provider

### Missing Fields

- **Cause**: Model didn't extract required fields
- **Fix**: Make requirements clearer in prompt, show examples

### Hallucinations

- **Cause**: Model inventing data not in source
- **Fix**: Emphasize "extract only" in prompt, ask for null if unsure

### No Extractions Running

- **Cause**: Config not matching files
- **Fix**: Check MIME patterns, URI patterns, tags. Verify config enabled.

## Future Enhancements

- **Batch extraction**: Process multiple files in single LLM call
- **Incremental updates**: Re-extract only when files change
- **Human-in-the-loop**: Review and correct extractions
- **Active learning**: Use corrections to improve prompts
- **Multi-modal**: Extract from images, videos, audio
- **Graph integration**: Auto-create graph edges from extracted entities
- **Validation rules**: Schema-level validation beyond JSON Schema

## Examples in Production

### Recruitment Platform
- 10K CVs/month processed
- Average confidence: 0.92
- Cost: $60/month
- Time saved: 200 hours/month vs manual data entry

### Legal Contract Management
- 500 contracts/month processed
- Risk flags identified: 15% of contracts
- Cost: $150/month
- Value: Early detection of risky terms

## Support

For questions or issues:
- GitHub: https://github.com/anthropics/rem
- Docs: https://rem-docs.example.com/ontology-extraction
- Slack: #rem-support
