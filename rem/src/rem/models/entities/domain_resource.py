"""
DomainResource - Curated internal knowledge in REM.

DomainResources are a specialized subclass of Resource for storing curated,
domain-specific internal knowledge that is not part of general knowledge.
This includes proprietary information, internal documentation, institutional
knowledge, and other content that requires more careful curation.

Key Differences from Resource:
- Intended for curated, internal knowledge (not raw ingested content)
- Higher quality bar - content is reviewed/vetted before ingestion
- May contain proprietary or sensitive information
- Subject to different retention/governance policies

Use Cases:
- Internal documentation and procedures
- Proprietary research and analysis
- Institutional knowledge bases
- Domain-specific ontologies and taxonomies
- Curated best practices and guidelines
"""

from .resource import Resource


class DomainResource(Resource):
    """
    Curated domain-specific knowledge resource.

    Inherits all fields from Resource but stored in a separate table
    (domain_resources) to distinguish curated internal knowledge from
    general ingested content.

    The schema is identical to Resource, allowing seamless migration
    of content between tables as curation status changes.
    """

    pass
