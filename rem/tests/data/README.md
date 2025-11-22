# Test Data

This directory contains test data for REM system integration tests.

## Structure

```
tests/data/
├── schemas/
│   └── agents/           # Agent schema test samples
│       └── test-cv-parser.yaml
└── engrams/              # Engram test samples
    ├── test-diary-entry.yaml
    ├── test-meeting-notes.yaml
    ├── test-observation.yaml
    ├── test-project-note.yaml
    └── test-conversation.yaml
```

## Agent Schemas

Agent schemas are JSON Schema documents with REM-specific metadata for defining
structured extraction agents.

### Structure

```yaml
---
type: object
description: |
  System prompt with LLM instructions.

properties:
  field_name:
    type: string
    description: Field description

required:
  - required_fields

json_schema_extra:
  fully_qualified_name: rem.agents.AgentName
  version: "1.0.0"
  tags: [domain, ontology-extractor]
  embedding_fields: [field1, field2]
  provider_configs:
    - provider_name: anthropic
      model_name: claude-sonnet-4-5-20250929
```

### Detection

SchemaProvider detects agent schemas by checking for:
- `type: object`
- `json_schema_extra.fully_qualified_name` starting with `rem.agents.*`

### Examples

- **test-cv-parser.yaml**: CV/resume parsing agent
  - Extracts candidate information, experience, skills, seniority
  - Multi-provider support (Anthropic, OpenAI)
  - Embedding fields for semantic search

## Engrams

Engrams are structured memory documents with optional temporal moments and
graph connections.

### Structure

```yaml
---
kind: engram
name: unique-identifier
category: diary|meeting|note|observation|conversation
summary: Brief summary
content: |
  Full content

uri: optional-source-uri
timestamp: 2025-01-15T10:00:00Z

metadata:
  key: value

tags:
  - tag1
  - tag2

graph_edges:
  - dst: entity-label
    rel: relationship-type
    weight: 0.0-1.0
    properties:
      key: value

moments:
  - start_time: 2025-01-15T10:00:00Z
    end_time: 2025-01-15T10:10:00Z
    summary: Moment summary
    speakers: [person1]
    topics: [topic1]
    emotion_tags: [emotion1]
```

### Examples

- **test-diary-entry.yaml**: Simple diary engram without moments
  - Personal reflection
  - Graph edges to mentioned entities
  - No temporal segmentation

- **test-meeting-notes.yaml**: Meeting engram with temporal moments
  - 3 temporal segments (moments)
  - Multiple speakers
  - Topic and emotion tagging
  - Attendance graph edges

- **test-observation.yaml**: Technical observation with rich graph
  - Performance issue documentation
  - Multiple graph edges (observes, relates_to, proposes, assigned_to, blocks)
  - Metadata for severity, reproducibility

- **test-project-note.yaml**: Project planning document
  - Structured markdown content
  - Resource and entity references
  - Migration plan with phases

- **test-conversation.yaml**: Multi-turn conversation
  - Temporal moments for conversation turns
  - Participant tracking
  - Topic and emotion tags per turn

## Usage in Tests

### Agent Schema Ingestion

```python
from rem.services.content.service import ContentService

service = ContentService()
result = service.process_uri("tests/data/schemas/agents/test-cv-parser.yaml")

# SchemaProvider detects it as agent schema
assert result["provider"] == "schema"
assert result["metadata"]["is_schema"] is True
assert result["metadata"]["schema_type"] == "agent"
```

### Engram Ingestion

```python
import yaml
from rem.models.core.engram import Engram

with open("tests/data/engrams/test-diary-entry.yaml") as f:
    data = yaml.safe_load(f)

engram = Engram(**data)
assert engram.kind == "engram"
assert engram.category == "diary"
assert len(engram.graph_edges) > 0
```

## Adding New Test Data

When adding new test data:

1. Follow the schema structure above
2. Use realistic content and metadata
3. Include graph edges to demonstrate relationships
4. Add moments for temporal documents (meetings, conversations)
5. Document in this README
