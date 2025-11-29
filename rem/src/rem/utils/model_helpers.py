"""
Pydantic Model Helper Utilities.

Utilities for working with REM Pydantic models following our conventions:

Business Key (entity_key) Detection:
1. Field with json_schema_extra={"entity_key": True}
2. Common business key fields: name, uri, key, label
3. Fallback to "id" (unique by UUID only)

Embedding Field Detection:
1. Field with json_schema_extra={"embed": True}
2. Common content fields: content, description, summary, etc.
3. Explicit disable with json_schema_extra={"embed": False}

Table Name Inference:
1. model_config.json_schema_extra.table_name
2. CamelCase → snake_case + pluralization

Model Resolution:
- model_from_arbitrary_casing: Resolve model class from flexible input casing
"""

import re
from typing import Any, Type

from loguru import logger
from pydantic import BaseModel


def get_entity_key_field(model: Type[BaseModel]) -> str:
    """
    Get the business key field for KV store lookups.

    Follows REM conventions:
    1. Field with json_schema_extra={"entity_key": True}
    2. "name" field (most common for resources, moments, etc.)
    3. "uri" field (for files)
    4. "key" or "label" fields
    5. Fallback to "id" (UUID only)

    Args:
        model: Pydantic model class

    Returns:
        Field name to use as entity_key

    Example:
        >>> from rem.models.entities import Resource
        >>> get_entity_key_field(Resource)
        'name'
    """
    # Check for explicit entity_key marker
    for field_name, field_info in model.model_fields.items():
        json_extra = getattr(field_info, "json_schema_extra", None)
        if json_extra and isinstance(json_extra, dict):
            if json_extra.get("entity_key") is True:
                logger.debug(f"Using explicit entity_key field: {field_name}")
                return field_name

    # Check for common business key fields
    for candidate in ["name", "uri", "key", "label", "title"]:
        if candidate in model.model_fields:
            logger.debug(f"Using conventional entity_key field: {candidate}")
            return candidate

    # Fallback to id (unique by UUID only)
    logger.warning(
        f"No business key found for {model.__name__}, using 'id' (UUID only)"
    )
    return "id"


def get_table_name(model: Type[BaseModel]) -> str:
    """
    Get table name for a Pydantic model.

    Follows REM conventions:
    1. model_config.json_schema_extra.table_name (explicit)
    2. CamelCase → snake_case + pluralization

    Args:
        model: Pydantic model class

    Returns:
        Table name

    Example:
        >>> from rem.models.entities import Resource
        >>> get_table_name(Resource)
        'resources'
    """
    import re

    # Check for explicit table_name
    if hasattr(model, "model_config"):
        model_config = model.model_config
        if isinstance(model_config, dict):
            json_extra = model_config.get("json_schema_extra", {})
            if isinstance(json_extra, dict) and "table_name" in json_extra:
                table_name = json_extra["table_name"]
                if isinstance(table_name, str):
                    return table_name

    # Infer from class name
    name = model.__name__

    # Convert CamelCase to snake_case
    name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name).lower()

    # Pluralize
    if not name.endswith("s"):
        if name.endswith("y"):
            name = name[:-1] + "ies"  # category -> categories
        else:
            name = name + "s"  # resource -> resources

    return name


def get_embeddable_fields(model: Type[BaseModel]) -> list[str]:
    """
    Get list of fields that should have embeddings generated.

    Follows REM conventions:
    1. Field with json_schema_extra={"embed": True} → always embed
    2. Field with json_schema_extra={"embed": False} → never embed
    3. Common content fields → embed by default
    4. Otherwise → don't embed

    Args:
        model: Pydantic model class

    Returns:
        List of field names to generate embeddings for

    Example:
        >>> from rem.models.entities import Resource
        >>> fields = get_embeddable_fields(Resource)
        >>> "content" in fields
        True
    """
    # Common content fields that embed by default
    DEFAULT_EMBED_FIELDS = {
        "content",
        "description",
        "summary",
        "text",
        "body",
        "message",
        "notes",
    }

    embeddable = []

    for field_name, field_info in model.model_fields.items():
        # Check json_schema_extra for explicit embed configuration
        json_extra = getattr(field_info, "json_schema_extra", None)
        if json_extra and isinstance(json_extra, dict):
            embed = json_extra.get("embed")
            if embed is True:
                embeddable.append(field_name)
                continue
            elif embed is False:
                # Explicitly disabled
                continue

        # Check if field name matches common content fields
        if field_name.lower() in DEFAULT_EMBED_FIELDS:
            embeddable.append(field_name)

    return embeddable


def should_skip_field(field_name: str) -> bool:
    """
    Check if a field should be skipped during SQL generation.

    System fields that are added separately:
    - id (added as PRIMARY KEY)
    - tenant_id (added for multi-tenancy)
    - user_id (added for ownership)
    - created_at, updated_at, deleted_at (added as system timestamps)
    - graph_edges, metadata (added as JSONB system fields)
    - tags, column (CoreModel fields)

    Args:
        field_name: Name of the field

    Returns:
        True if field should be skipped

    Example:
        >>> should_skip_field("id")
        True
        >>> should_skip_field("name")
        False
    """
    SYSTEM_FIELDS = {
        "id",
        "tenant_id",
        "user_id",
        "created_at",
        "updated_at",
        "deleted_at",
        "graph_edges",
        "metadata",
        "tags",
        "column",
    }

    return field_name in SYSTEM_FIELDS


def get_model_metadata(model: Type[BaseModel]) -> dict[str, Any]:
    """
    Extract REM-specific metadata from a Pydantic model.

    Returns:
        Dict with:
        - table_name: Database table name
        - entity_key_field: Business key field name
        - embeddable_fields: List of fields to embed
        - model_name: Original model class name

    Example:
        >>> from rem.models.entities import Resource
        >>> meta = get_model_metadata(Resource)
        >>> meta["table_name"]
        'resources'
        >>> meta["entity_key_field"]
        'name'
        >>> "content" in meta["embeddable_fields"]
        True
    """
    return {
        "model_name": model.__name__,
        "table_name": get_table_name(model),
        "entity_key_field": get_entity_key_field(model),
        "embeddable_fields": get_embeddable_fields(model),
    }


def normalize_to_title_case(name: str) -> str:
    """
    Normalize arbitrary casing to TitleCase (PascalCase).

    Handles various input formats:
    - kebab-case: domain-resource → DomainResource
    - snake_case: domain_resource → DomainResource
    - lowercase: domainresource → Domainresource (single word)
    - TitleCase: DomainResource → DomainResource (passthrough)
    - Mixed: Domain-Resource, DOMAIN_RESOURCE → DomainResource

    Args:
        name: Input name in any casing format

    Returns:
        TitleCase (PascalCase) version of the name

    Example:
        >>> normalize_to_title_case("domain-resource")
        'DomainResource'
        >>> normalize_to_title_case("domain_resources")
        'DomainResources'
        >>> normalize_to_title_case("DomainResource")
        'DomainResource'
    """
    # If already TitleCase (starts with uppercase, has no delimiters, and has
    # at least one lowercase letter), return as-is
    if (
        name
        and name[0].isupper()
        and '-' not in name
        and '_' not in name
        and any(c.islower() for c in name)
    ):
        return name

    # Split on common delimiters (hyphen, underscore)
    parts = re.split(r'[-_]', name)

    # Capitalize first letter of each part, lowercase the rest
    normalized_parts = [part.capitalize() for part in parts if part]

    return "".join(normalized_parts)


def model_from_arbitrary_casing(
    name: str,
    registry: dict[str, Type[BaseModel]] | None = None,
) -> Type[BaseModel]:
    """
    Resolve a model class from arbitrary casing input.

    REM entity models use strict TitleCase (PascalCase) naming. This function
    allows flexible input formats while maintaining consistency:

    Input formats supported:
    - kebab-case: domain-resource, domain-resources
    - snake_case: domain_resource, domain_resources
    - lowercase: resource, domainresource
    - TitleCase: Resource, DomainResource

    Args:
        name: Model name in any supported casing format
        registry: Optional dict mapping TitleCase names to model classes.
                  If not provided, uses rem.models.entities module.

    Returns:
        The resolved Pydantic model class

    Raises:
        ValueError: If no model matches the normalized name

    Example:
        >>> model = model_from_arbitrary_casing("domain-resources")
        >>> model.__name__
        'DomainResource'
        >>> model = model_from_arbitrary_casing("Resource")
        >>> model.__name__
        'Resource'
    """
    # Build default registry from entities module if not provided
    if registry is None:
        from rem.models.entities import (
            DomainResource,
            Feedback,
            File,
            ImageResource,
            Message,
            Moment,
            Ontology,
            OntologyConfig,
            Resource,
            Schema,
            Session,
            User,
        )

        registry = {
            "Resource": Resource,
            "Resources": Resource,  # Plural alias
            "DomainResource": DomainResource,
            "DomainResources": DomainResource,  # Plural alias
            "ImageResource": ImageResource,
            "ImageResources": ImageResource,
            "File": File,
            "Files": File,
            "Message": Message,
            "Messages": Message,
            "Moment": Moment,
            "Moments": Moment,
            "Session": Session,
            "Sessions": Session,
            "Feedback": Feedback,
            "User": User,
            "Users": User,
            "Schema": Schema,
            "Schemas": Schema,
            "Ontology": Ontology,
            "Ontologies": Ontology,
            "OntologyConfig": OntologyConfig,
            "OntologyConfigs": OntologyConfig,
        }

    # Normalize input to TitleCase
    normalized = normalize_to_title_case(name)

    # Look up in registry
    if normalized in registry:
        logger.debug(f"Resolved model '{name}' → {registry[normalized].__name__}")
        return registry[normalized]

    # Try without trailing 's' (singular form)
    if normalized.endswith("s") and normalized[:-1] in registry:
        logger.debug(f"Resolved model '{name}' → {registry[normalized[:-1]].__name__} (singular)")
        return registry[normalized[:-1]]

    # Try with trailing 's' (plural form)
    plural = normalized + "s"
    if plural in registry:
        logger.debug(f"Resolved model '{name}' → {registry[plural].__name__} (plural)")
        return registry[plural]

    available = sorted(set(m.__name__ for m in registry.values()))
    raise ValueError(
        f"Unknown model: '{name}' (normalized: '{normalized}'). "
        f"Available models: {', '.join(available)}"
    )
