"""Ontology entity for domain-specific knowledge.

**What are Ontologies?**

Ontologies are **domain-specific structured knowledge** that can be:
1. **Extracted** from files using custom agent schemas (agent-extracted)
2. **Loaded directly** from external sources like git repos or S3 (direct-loaded)

**Use Case 1: Agent-Extracted Ontologies**

File → custom agent → structured JSON → ontology (domain knowledge)

Example: A contract PDF becomes a structured record with parties, dates, payment terms.

**Use Case 2: Direct-Loaded Ontologies (Knowledge Bases)**

External source (git/S3) → load → ontology (reference knowledge)

Example: A psychiatric ontology of disorders, symptoms, and drugs loaded from markdown
files in a git repository. Each markdown file becomes an ontology node with:
- `uri`: git path (e.g., `git://org/repo/ontology/disorders/anxiety/panic-disorder.md`)
- `content`: markdown content for embedding/search
- `extracted_data`: parsed frontmatter or structure

**Architecture:**
- Runs as part of dreaming worker (background knowledge extraction) OR
- Loaded directly via `rem db load` for external knowledge bases
- OntologyConfig defines which files trigger which extractors
- Multiple ontologies per file (apply different domain lenses)
- Tenant-scoped: Each tenant can define their own extractors and knowledge bases

**Use Cases:**

1. **Recruitment (CV Parsing)** - Agent-extracted
   - Ontology: Structured fields for filtering/sorting (years_experience, skills[])

2. **Legal (Contract Analysis)** - Agent-extracted
   - Ontology: Queryable fields (parties, effective_date, payment_amount)

3. **Medical Knowledge Base** - Direct-loaded
   - Ontology: Disorders, symptoms, medications from curated markdown files
   - Enables semantic search over psychiatric/medical domain knowledge

4. **Documentation/Procedures** - Direct-loaded
   - Ontology: Clinical procedures (e.g., SCID-5 assessment steps)
   - Reference material accessible via RAG

**Design:**
- `file_id` and `agent_schema_id` are optional (only needed for agent-extracted)
- `uri` field for external source references (git://, s3://, https://)
- Structured data in `extracted_data` (arbitrary JSON)
- Embeddings generated for semantic search via `content` field
- Tenant-isolated: OntologyConfigs are tenant-scoped
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import ConfigDict

from ..core.core_model import CoreModel


class Ontology(CoreModel):
    """Domain-specific knowledge - either agent-extracted or direct-loaded.

    Attributes:
        name: Human-readable label for this ontology instance
        uri: External source reference (git://, s3://, https://) for direct-loaded ontologies
        file_id: Foreign key to File entity (optional - only for agent-extracted)
        agent_schema_id: Schema that performed extraction (optional - only for agent-extracted)
        provider_name: LLM provider used for extraction (optional)
        model_name: Specific model used (optional)
        extracted_data: Structured data - either extracted by agent or parsed from source
        confidence_score: Optional confidence score from extraction (0.0-1.0)
        extraction_timestamp: When extraction was performed
        content: Text used for generating embedding

    Inherited from CoreModel:
        id: UUID or string identifier
        created_at: Entity creation timestamp
        updated_at: Last update timestamp
        deleted_at: Soft deletion timestamp
        tenant_id: Multi-tenancy isolation
        user_id: Ownership
        graph_edges: Relationships to other entities
        metadata: Flexible metadata storage
        tags: Classification tags

    Example Usage:
        # Agent-extracted: CV parsing
        cv_ontology = Ontology(
            name="john-doe-cv-2024",
            file_id="file-uuid-123",
            agent_schema_id="cv-parser-v1",
            provider_name="anthropic",
            model_name="claude-sonnet-4-5-20250929",
            extracted_data={
                "candidate_name": "John Doe",
                "skills": ["Python", "PostgreSQL", "Kubernetes"],
            },
            confidence_score=0.95,
            tags=["cv", "engineering"]
        )

        # Direct-loaded: Knowledge base from git
        api_docs = Ontology(
            name="rest-api-guide",
            uri="git://example-org/docs/api/rest-api-guide.md",
            content="# REST API Guide\\n\\nThis guide covers RESTful API design...",
            extracted_data={
                "type": "documentation",
                "category": "api",
                "version": "2.0",
            },
            tags=["api", "rest", "documentation"]
        )

        # Direct-loaded: Technical spec from git
        config_spec = Ontology(
            name="config-schema",
            uri="git://example-org/docs/specs/config-schema.md",
            content="# Configuration Schema\\n\\nThis document defines...",
            extracted_data={
                "type": "specification",
                "format": "yaml",
                "version": "1.0",
            },
            tags=["config", "schema", "specification"]
        )
    """

    # Core fields
    name: str
    uri: Optional[str] = None  # External source: git://, s3://, https://

    # Agent extraction fields (optional - only for agent-extracted ontologies)
    file_id: Optional[UUID | str] = None  # FK to File entity
    agent_schema_id: Optional[str] = None  # Schema that performed extraction
    provider_name: Optional[str] = None  # LLM provider (anthropic, openai, etc.)
    model_name: Optional[str] = None  # Specific model used

    # Data fields
    extracted_data: Optional[dict[str, Any]] = None  # Structured data
    confidence_score: Optional[float] = None  # 0.0-1.0 if provided by agent
    extraction_timestamp: Optional[str] = None  # ISO8601 timestamp

    # Semantic search support - 'content' is a default embeddable field name
    content: Optional[str] = None  # Text for embedding generation

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Domain-specific knowledge - agent-extracted or direct-loaded from external sources",
            "examples": [
                {
                    "name": "panic-disorder",
                    "uri": "git://org/repo/ontology/disorders/anxiety/panic-disorder.md",
                    "content": "# Panic Disorder\n\nPanic disorder is characterized by...",
                    "extracted_data": {
                        "type": "disorder",
                        "category": "anxiety",
                        "icd10": "F41.0"
                    },
                    "tags": ["disorder", "anxiety"]
                },
                {
                    "name": "john-doe-cv-2024",
                    "file_id": "550e8400-e29b-41d4-a716-446655440000",
                    "agent_schema_id": "cv-parser-v1",
                    "provider_name": "anthropic",
                    "model_name": "claude-sonnet-4-5-20250929",
                    "extracted_data": {
                        "candidate_name": "John Doe",
                        "skills": ["Python", "PostgreSQL"]
                    },
                    "confidence_score": 0.95,
                    "tags": ["cv", "engineering"]
                }
            ]
        }
    )
