# Agent Schemas

This directory contains YAML-based agent schemas for REM agents. Schemas are organized into folders for better maintainability.

## Folder Structure

```
agents/
├── rem.yaml                 # Main REM agent (top-level)
├── core/                    # Core system agents
│   ├── moment-builder.yaml
│   ├── rem-query-agent.yaml
│   ├── resource-affinity-assessor.yaml
│   └── user-profile-builder.yaml
└── examples/                # Example and domain-specific agents
    ├── contract-analyzer.yaml
    ├── contract-extractor.yaml
    ├── cv-parser.yaml
    ├── hello-world.yaml
    ├── query.yaml
    ├── simple.yaml
    └── test.yaml
```

## Schema Organization

### Top-Level (`rem.yaml`)
The main REM agent that provides comprehensive memory querying capabilities.

### Core Agents (`core/`)
System agents used by the dreaming worker and core REM functionality:
- **moment-builder.yaml** - Constructs temporal narratives from resources
- **rem-query-agent.yaml** - Translates natural language to REM queries
- **resource-affinity-assessor.yaml** - Calculates semantic affinity between resources
- **user-profile-builder.yaml** - Builds user profiles from activity data

### Example Agents (`examples/`)
Domain-specific agents and examples for testing and demonstration:
- **contract-analyzer.yaml** - Legal contract analysis
- **contract-extractor.yaml** - Contract data extraction
- **cv-parser.yaml** - CV/resume parsing
- **hello-world.yaml** - Simple example agent
- **query.yaml** - Query example
- **simple.yaml** - Minimal example
- **test.yaml** - Testing agent

## Usage

The schema loader automatically searches all subdirectories. You can reference schemas by:

```bash
# Short name (searches all folders automatically)
rem ask moment-builder "Build moments for last week"
rem ask contract-analyzer -i contract.pdf

# With folder prefix (explicit)
rem ask core/moment-builder "Build moments"
rem ask examples/contract-analyzer -i contract.pdf

# Full path (absolute)
rem ask schemas/agents/core/moment-builder.yaml
```

## Creating New Agents

1. **For system agents**: Add to `core/` folder
2. **For domain-specific agents**: Add to `examples/` folder
3. **For new categories**: Create a new folder and update `schema_loader.py`

Schema structure:
```yaml
---
type: object
description: |
  System prompt with LLM instructions.

properties:
  # Output schema fields
  field_name:
    type: string
    description: Field description

required:
  - required_fields

json_schema_extra:
  fully_qualified_name: rem.agents.YourAgent
  version: "1.0.0"
  tags: [category, type]
```

See [CLAUDE.md](../../../../../../CLAUDE.md) for complete documentation on agent schemas and the REM architecture.
