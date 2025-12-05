"""OntologyConfig entity for user-defined ontology extraction rules.

OntologyConfig allows users to define which agent schemas should be applied to
which files during the dreaming/processing workflow. This enables domain-specific
knowledge extraction tailored to user needs.

Examples:
- "Apply cv-parser-v1 to all PDF files in /resumes/"
- "Apply contract-analyzer-v2 to files tagged with 'legal'"
- "Apply medical-records-extractor to files with mime_type application/pdf AND tags ['medical']"

Design:
- Each config is tenant-scoped for isolation
- File matching via mime_type patterns, tag filters, and URI patterns
- Multiple configs can match a single file (all will be applied)
- Priority field for execution order when multiple configs match
- Enabled/disabled toggle for temporary deactivation
"""

from typing import Optional

from pydantic import ConfigDict

from ..core.core_model import CoreModel


class OntologyConfig(CoreModel):
    """User configuration for automatic ontology extraction.

    Attributes:
        name: Human-readable config name
        agent_schema_id: Foreign key to Schema entity to use for extraction
        description: Purpose and scope of this config

        # File matching rules (ANY matching rule triggers extraction)
        mime_type_pattern: Regex pattern for file MIME types (e.g., "application/pdf")
        uri_pattern: Regex pattern for file URIs (e.g., "s3://bucket/resumes/.*")
        tag_filter: List of tags (file must have ALL tags to match)

        # Execution control
        priority: Execution order (higher = earlier, default 100)
        enabled: Whether this config is active (default True)

        # LLM provider configuration
        provider_name: Optional LLM provider override (defaults to settings)
        model_name: Optional model override (defaults to settings)

    Inherited from CoreModel:
        id, created_at, updated_at, deleted_at, tenant_id, user_id,
        graph_edges, metadata, tags, column

    Example Usage:
        # CV extraction for recruitment
        cv_config = OntologyConfig(
            name="recruitment-cv-parser",
            agent_schema_id="cv-parser-v1",
            description="Extract candidate information from resumes",
            mime_type_pattern="application/pdf",
            uri_pattern=".*/resumes/.*",
            tag_filter=["cv", "candidate"],
            priority=100,
            enabled=True,
            tenant_id="acme-corp",
            tags=["recruitment", "hr"]
        )

        # Contract analysis for legal team
        contract_config = OntologyConfig(
            name="legal-contract-analyzer",
            agent_schema_id="contract-parser-v2",
            description="Extract key terms from supplier contracts",
            mime_type_pattern="application/(pdf|msword|vnd.openxmlformats.*)",
            tag_filter=["legal", "contract"],
            priority=200,  # Higher priority = runs first
            enabled=True,
            provider_name="openai",  # Override default provider
            model_name="gpt-4.1",
            tenant_id="acme-corp",
            tags=["legal", "procurement"]
        )

        # Medical records for healthcare
        medical_config = OntologyConfig(
            name="medical-records-extractor",
            agent_schema_id="medical-parser-v1",
            description="Extract diagnoses and treatments from medical records",
            mime_type_pattern="application/pdf",
            tag_filter=["medical", "patient-record"],
            priority=50,
            enabled=True,
            tenant_id="healthsystem",
            tags=["medical", "hipaa-compliant"]
        )
    """

    # Core fields
    name: str
    agent_schema_id: str  # Foreign key to Schema entity
    description: Optional[str] = None

    # File matching rules (ANY rule can trigger match)
    mime_type_pattern: Optional[str] = None  # Regex for MIME type
    uri_pattern: Optional[str] = None  # Regex for file URI
    tag_filter: list[str] = []  # File must have ALL tags

    # Execution control
    priority: int = 100  # Higher = runs first
    enabled: bool = True  # Toggle to disable without deleting

    # Optional provider overrides
    provider_name: Optional[str] = None  # Override default provider
    model_name: Optional[str] = None  # Override default model

    model_config = ConfigDict(
        json_schema_extra={
            "description": "Configuration for automatic ontology extraction from files",
            "examples": [
                {
                    "name": "recruitment-cv-parser",
                    "agent_schema_id": "cv-parser-v1",
                    "description": "Extract candidate information from resumes",
                    "mime_type_pattern": "application/pdf",
                    "uri_pattern": ".*/resumes/.*",
                    "tag_filter": ["cv", "candidate"],
                    "priority": 100,
                    "enabled": True,
                    "tenant_id": "acme-corp"
                }
            ]
        }
    )
