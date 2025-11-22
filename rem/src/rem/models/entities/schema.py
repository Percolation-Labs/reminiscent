"""
Schema - Agent schema definitions in REM.

Schemas represent agent definitions that can be loaded into Pydantic AI.
They store JsonSchema specifications that define agent capabilities, tools,
and output structures.

Schemas are used for:
- Agent definition storage and versioning
- Dynamic agent loading via X-Agent-Schema header
- Agent registry and discovery
- Schema validation and documentation
- Ontology extraction configuration

Key Fields:
- name: Human-readable schema identifier
- content: Markdown documentation and instructions
- spec: JsonSchema specification (Pydantic model definition)
- category: Schema classification (agent-type, workflow, ontology-extractor, etc.)
- provider_configs: Optional LLM provider configurations (for multi-provider support)
- embedding_fields: Fields in extracted_data that should be embedded for semantic search
"""

from typing import Optional

from pydantic import Field

from ..core import CoreModel


class Schema(CoreModel):
    """
    Agent schema definition.

    Schemas define agents that can be dynamically loaded into Pydantic AI.
    They store JsonSchema specifications with embedded metadata for tools,
    resources, and system prompts.

    For ontology extraction agents:
    - `provider_configs` enables multi-provider support (test across Anthropic, OpenAI, etc.)
    - `embedding_fields` specifies which output fields should be embedded for semantic search

    Tenant isolation is provided via CoreModel.tenant_id field.
    """

    name: str = Field(
        ...,
        description="Human-readable schema name (used as identifier)",
    )

    content: str = Field(
        default="",
        description="Markdown documentation and instructions for the schema",
    )

    spec: dict = Field(
        ...,
        description="JsonSchema specification defining the agent structure and capabilities",
    )

    category: Optional[str] = Field(
        default=None,
        description=(
            "Schema category distinguishing schema types. "
            "Values: 'agent' (AI agents), 'evaluator' (LLM-as-a-Judge evaluators). "
            "Maps directly from json_schema_extra.kind field during ingestion."
        ),
    )

    # Ontology extraction support
    provider_configs: list[dict] = Field(
        default_factory=list,
        description=(
            "Optional provider configurations for multi-provider testing. "
            "Each dict has 'provider_name' and 'model_name'. "
            "Example: [{'provider_name': 'anthropic', 'model_name': 'claude-sonnet-4-5'}]"
        ),
    )

    embedding_fields: list[str] = Field(
        default_factory=list,
        description=(
            "JSON paths in extracted_data to embed for semantic search. "
            "Example: ['summary', 'candidate_name', 'skills'] for CV extraction. "
            "Values will be concatenated and embedded using configured embedding provider."
        ),
    )
