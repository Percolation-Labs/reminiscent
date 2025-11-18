"""
Agent query model for structured agent input.

Design pattern for standardized agent query structure with:
- Primary query (user question/task)
- Knowledge context (retrieved context, documentation)
- Scratchpad (working memory, session state)

Key Design Pattern 
- Separates query from retrieval (query is what user asks, knowledge is what we retrieve)
- Scratchpad enables multi-turn reasoning and state tracking
- Supports markdown + fenced JSON for structured data
- Converts to single prompt string for agent consumption
"""

from typing import Any

from pydantic import BaseModel, Field


class AgentQuery(BaseModel):
    """
    Standard query structure for agent execution.

    Provides consistent structure for queries, knowledge context, and
    working memory across all agent types.

    Design Pattern 
    - query: User's question/task (markdown + fenced JSON)
    - knowledge: Retrieved context from REM queries (markdown + fenced JSON)
    - scratchpad: Working memory for multi-turn reasoning (JSON or markdown)

    Example:
        query = AgentQuery(
            query="Find all documents Sarah authored",
            knowledge=\"\"\"
            # Entity Information
            Sarah Chen (person/employee)
            - Role: Senior Engineer
            - Projects: [Project Alpha, TiDB Migration]
            \"\"\",
            scratchpad={"current_case": "TAP-1234", "stage": "entity_lookup"}
        )

        prompt = query.to_prompt()
        result = await agent.run(prompt)
    """

    query: str = Field(
        ...,
        description="Primary user query or task (markdown format, may include fenced JSON)",
        examples=[
            "Find all documents Sarah authored",
            "What happened in Q4 retrospective?",
            "TRAVERSE manages WITH LOOKUP sarah-chen DEPTH 2",
        ],
    )

    knowledge: str = Field(
        default="",
        description="Background knowledge and context (markdown, may include fenced JSON/code)",
        examples=[
            "# Entity: sarah-chen\nType: person/employee\nRole: Senior Engineer",
            "Retrieved resources:\n```json\n[{...}]\n```",
        ],
    )

    scratchpad: str | dict[str, Any] = Field(
        default="",
        description="Working memory for session state (JSON object or markdown with fenced JSON)",
        examples=[
            {"stage": "lookup", "visited_entities": ["sarah-chen"]},
            "# Session State\n\nStage: TRAVERSE depth 1\n\n```json\n{\"nodes\": [...]}\n```",
        ],
    )

    def to_prompt(self) -> str:
        """
        Convert query components to single prompt string.

        Combines query, knowledge, and scratchpad into formatted prompt
        for agent consumption.

        Returns:
            Formatted prompt string with sections

        Example:
            # Query

            Find all documents Sarah authored

            # Knowledge

            Entity: sarah-chen
            Type: person/employee

            # Scratchpad

            ```json
            {"stage": "lookup"}
            ```
        """
        parts = [f"# Query\n\n{self.query}"]

        if self.knowledge:
            parts.append(f"\n# Knowledge\n\n{self.knowledge}")

        if self.scratchpad:
            if isinstance(self.scratchpad, dict):
                import json

                scratchpad_str = json.dumps(self.scratchpad, indent=2)
                parts.append(f"\n# Scratchpad\n\n```json\n{scratchpad_str}\n```")
            else:
                parts.append(f"\n# Scratchpad\n\n{self.scratchpad}")

        return "\n".join(parts)
