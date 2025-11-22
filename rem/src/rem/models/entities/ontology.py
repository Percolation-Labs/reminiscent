"""Ontology entity for tenant-specific knowledge extensions.

**What is Ontology Extraction?**

Ontologies are **domain-specific structured knowledge** extracted from files using custom
agent schemas. They extend REM's normal file processing pipeline with tenant-specific
parsers that extract structured data the standard chunking pipeline would miss.

**Normal File Processing:**
File → extract text → chunk → embed → resources (semantic search ready)

**Ontology Processing (Tenant Knowledge Extensions):**
File → custom agent → structured JSON → ontology (domain knowledge)

**Why Ontologies?**
- Standard chunking gives you semantic search over raw content
- Ontologies give you **structured queryable fields** from domain logic
- Example: A contract PDF becomes both searchable chunks AND a structured record with
  parties, dates, payment terms, obligations as queryable fields

**Architecture:**
- Runs as part of dreaming worker (background knowledge extraction)
- OntologyConfig defines which files trigger which extractors (MIME type, URI pattern, tags)
- Multiple ontologies per file (apply different domain lenses)
- Tenant-scoped: Each tenant can define their own extractors

**Use Cases:**

1. **Recruitment (CV Parsing)**
   - Standard pipeline: Chunks for "find me candidates with Python experience"
   - Ontology: Structured fields for filtering/sorting (years_experience, seniority_level, skills[])

2. **Legal (Contract Analysis)**
   - Standard pipeline: Semantic search over contract text
   - Ontology: Queryable fields (parties, effective_date, payment_amount, key_obligations[])

3. **Medical (Health Records)**
   - Standard pipeline: Find mentions of conditions
   - Ontology: Structured diagnoses, medications, dosages, treatment plans

4. **Finance (Report Analysis)**
   - Standard pipeline: Search for financial terms
   - Ontology: Extracted metrics, risk_flags, trends, forecasts

**Example Flow:**
1. Tenant creates OntologyConfig: "Run cv-parser-v1 on files with mime_type='application/pdf' and tags=['resume']"
2. File uploaded with tags=["resume"]
3. Normal processing: File → chunks → resources
4. Dreaming worker detects matching OntologyConfig
5. Loads cv-parser-v1 agent schema from database
6. Runs agent on file content → extracts structured data
7. Stores Ontology with extracted_data = {candidate_name, skills, experience, education, ...}
8. Ontology is now queryable via LOOKUP, SEARCH, or direct SQL

**Design:**
- Each ontology links to a File via file_id
- Agent schema tracked via agent_schema_id (human-readable label, not UUID)
- Structured data in `extracted_data` (arbitrary JSON, schema defined by agent)
- Embeddings generated for semantic search (configurable fields via agent schema)
- Multiple ontologies per file using different schemas
- Tenant-isolated: OntologyConfigs are tenant-scoped
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import ConfigDict

from ..core.core_model import CoreModel


class Ontology(CoreModel):
    """Domain-specific knowledge extracted from files using custom agents.

    Attributes:
        name: Human-readable label for this ontology instance
        file_id: Foreign key to File entity that was processed
        agent_schema_id: Foreign key to Schema entity that performed extraction
        provider_name: LLM provider used for extraction (e.g., "anthropic", "openai")
        model_name: Specific model used (e.g., "claude-sonnet-4-5")
        extracted_data: Structured data extracted by agent (arbitrary JSON)
        confidence_score: Optional confidence score from extraction (0.0-1.0)
        extraction_timestamp: When extraction was performed
        embedding_text: Text used for generating embedding (derived from extracted_data)

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
        column: Database schema metadata

    Example Usage:
        # CV extraction
        cv_ontology = Ontology(
            name="john-doe-cv-2024",
            file_id="file-uuid-123",
            agent_schema_id="cv-parser-v1",
            provider_name="anthropic",
            model_name="claude-sonnet-4-5-20250929",
            extracted_data={
                "candidate_name": "John Doe",
                "email": "john@example.com",
                "skills": ["Python", "PostgreSQL", "Kubernetes"],
                "experience": [
                    {
                        "company": "TechCorp",
                        "role": "Senior Engineer",
                        "years": 3,
                        "achievements": ["Led migration to k8s", "Reduced costs 40%"]
                    }
                ],
                "education": [
                    {"degree": "BS Computer Science", "institution": "MIT", "year": 2018}
                ]
            },
            confidence_score=0.95,
            tags=["cv", "engineering", "senior-level"]
        )

        # Contract extraction
        contract_ontology = Ontology(
            name="acme-supplier-agreement-2024",
            file_id="file-uuid-456",
            agent_schema_id="contract-parser-v2",
            provider_name="openai",
            model_name="gpt-4o",
            extracted_data={
                "contract_type": "supplier_agreement",
                "parties": [
                    {"name": "ACME Corp", "role": "buyer"},
                    {"name": "SupplyChain Inc", "role": "supplier"}
                ],
                "effective_date": "2024-01-01",
                "termination_date": "2026-12-31",
                "payment_terms": {
                    "amount": 500000,
                    "currency": "USD",
                    "frequency": "quarterly"
                },
                "key_obligations": [
                    "Supplier must deliver within 30 days",
                    "Buyer must pay within 60 days of invoice"
                ]
            },
            confidence_score=0.92,
            tags=["contract", "supplier", "procurement"]
        )
    """

    # Core fields
    name: str
    file_id: UUID | str
    agent_schema_id: str  # Natural language label of Schema entity

    # Extraction metadata
    provider_name: str  # LLM provider (anthropic, openai, etc.)
    model_name: str  # Specific model used
    extracted_data: dict[str, Any]  # Arbitrary structured data from agent
    confidence_score: Optional[float] = None  # 0.0-1.0 if provided by agent
    extraction_timestamp: Optional[str] = None  # ISO8601 timestamp

    # Semantic search support
    embedding_text: Optional[str] = None  # Text for embedding generation

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Domain-specific knowledge extracted from files using custom agents",
            "examples": [
                {
                    "name": "john-doe-cv-2024",
                    "file_id": "550e8400-e29b-41d4-a716-446655440000",
                    "agent_schema_id": "cv-parser-v1",
                    "provider_name": "anthropic",
                    "model_name": "claude-sonnet-4-5-20250929",
                    "extracted_data": {
                        "candidate_name": "John Doe",
                        "skills": ["Python", "PostgreSQL"],
                        "experience": []
                    },
                    "confidence_score": 0.95,
                    "tags": ["cv", "engineering"]
                }
            ]
        }
    )
