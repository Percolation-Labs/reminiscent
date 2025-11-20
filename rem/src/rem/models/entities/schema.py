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

Key Fields:
- name: Human-readable schema identifier
- content: Markdown documentation and instructions
- spec: JsonSchema specification (Pydantic model definition)
- category: Schema classification (agent-type, workflow, etc.)
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
        description="Schema category (agent-type, workflow, evaluator, etc.)",
    )
