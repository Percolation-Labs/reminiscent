"""
MCP Prompts for REM operations.

Prompts are interactive templates that help users perform complex tasks.
"""

from fastmcp import FastMCP


CREATEAGENT_PROMPT = """
Create a custom REM agent schema.

I'll help you create an agent schema that can be uploaded to REM and automatically processed.

## What I need from you:

1. **Agent purpose**: What should this agent do? What domain knowledge does it need?
2. **Short name**: Lowercase with hyphens (e.g., "cv-parser", "contract-analyzer")
3. **Version**: Semantic version (e.g., "1.0.0")
4. **Structured output fields**: What data should the agent extract?

## Agent Schema Format

REM agents use JSON Schema format with these sections:

```yaml
---
type: object
description: |
  System prompt with LLM instructions.

  Provide clear, detailed guidance on what the agent should do.

properties:
  field_name:
    type: string
    description: Field description

required:
  - required_field

json_schema_extra:
  kind: agent
  name: your-agent
  version: "1.0.0"
  tags: [domain, category]

  # Optional: Fields to embed for semantic search
  embedding_fields:
    - field1
    - field2
```

## Example: CV Parser

```yaml
---
type: object
description: |
  Parse CV/resume documents to extract candidate information.

  Extract:
  - Candidate details (name, contact, summary)
  - Work experience with dates
  - Education history
  - Skills and competencies
  - Seniority level assessment

properties:
  candidate_name:
    type: string
    description: Full name of the candidate

  skills:
    type: array
    items:
      type: string
    description: Technical and professional skills

  experience:
    type: array
    items:
      type: object
      properties:
        company: {type: string}
        title: {type: string}
        start_date: {type: string}
        end_date: {type: string}
    description: Work experience history

  seniority_level:
    type: string
    enum: ["junior", "mid-level", "senior", "lead", "executive"]
    description: Assessed seniority level

required:
  - candidate_name
  - skills

json_schema_extra:
  kind: agent
  name: cv-parser
  version: "1.0.0"

  tags: [recruitment, ontology-extractor]

  embedding_fields:
    - candidate_name
    - skills

  category: ontology-extractor
```

## Upload Process

After creating your schema:

1. **Save to local file system**: `~/.rem/fs/my-agent.yaml` or request an upload path for remote servers.

2. **Upload via ingest_file**:
   ```python
   ingest_file(
       file_uri="LOCAL PATH for local servers or remote S3 path for remote servers",
       category="agent"
   )
   ```

3. **Automatic processing**:
   - File detected by worker
   - Schema validated and stored in schemas table
   - Available for immediate use

## Ready?

Tell me:
1. What should your agent do?
2. What data should it extract?
3. What should we name it?

I'll generate the complete schema for you!
"""


def register_prompts(mcp: FastMCP):
    """
    Register MCP prompts.

    Args:
        mcp: FastMCP server instance
    """

    @mcp.prompt()
    def create_agent(
        purpose: str = "",
        short_name: str = "",
        version: str = "1.0.0",
    ) -> str:
        """
        Interactive prompt for creating custom REM agent schemas.

        Guides users through creating agent schemas with domain knowledge,
        structured output definitions, and upload instructions.

        Args:
            purpose: Agent purpose and domain (optional, will prompt if empty)
            short_name: Agent short name in kebab-case (optional, will suggest)
            version: Semantic version (default: "1.0.0")

        Returns:
            Interactive prompt with examples and upload instructions
        """
        prompt = CREATEAGENT_PROMPT

        # Add context if parameters provided
        if purpose:
            prompt += f"\n\nYou mentioned: \"{purpose}\"\n"
        if short_name:
            prompt += f"Short name: {short_name}\n"
        if version != "1.0.0":
            prompt += f"Version: {version}\n"

        return prompt
