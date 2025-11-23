"""Dictionary utilities for nested access and field extraction.

Utilities for working with nested dictionaries and extracting values
for embeddings, serialization, etc.
"""

import json
from typing import Any


def get_nested_value(data: dict[str, Any], path: str) -> Any:
    """Get value from nested dict using dot notation.

    Args:
        data: Dictionary to traverse
        path: Dot-separated path (e.g., "candidate.name", "skills.0.proficiency")

    Returns:
        Value at the path, or None if not found

    Examples:
        >>> data = {"candidate": {"name": "John", "skills": [{"name": "Python"}]}}
        >>> get_nested_value(data, "candidate.name")
        'John'
        >>> get_nested_value(data, "candidate.skills.0.name")
        'Python'
        >>> get_nested_value(data, "candidate.missing")
        None
    """
    keys = path.split(".")
    value: Any = data

    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        elif isinstance(value, list):
            # Handle array index (e.g., "skills.0.name")
            try:
                index = int(key)
                value = value[index] if 0 <= index < len(value) else None
            except (ValueError, TypeError):
                return None
        else:
            return None

        if value is None:
            return None

    return value


def extract_fields_for_embedding(
    data: dict[str, Any],
    fields: list[str],
) -> str:
    """Extract and concatenate fields from dict for embedding generation.

    Supports nested field access via dot notation.
    Handles lists and dicts by JSON-serializing them.
    Returns newline-separated concatenation of all field values.

    Args:
        data: Dictionary containing data to extract
        fields: List of field paths (supports dot notation)

    Returns:
        Concatenated text suitable for embedding

    Examples:
        >>> data = {
        ...     "name": "John Doe",
        ...     "skills": ["Python", "PostgreSQL"],
        ...     "experience": {"years": 5, "level": "senior"}
        ... }
        >>> extract_fields_for_embedding(data, ["name", "skills"])
        'John Doe\\n["Python", "PostgreSQL"]'

        >>> extract_fields_for_embedding(data, ["name", "experience.level"])
        'John Doe\\nsenior'

        >>> extract_fields_for_embedding(data, [])
        '{"name": "John Doe", ...}'  # Full JSON if no fields specified
    """
    if not fields:
        # If no fields specified, embed entire JSON
        return json.dumps(data, indent=2)

    parts = []
    for field in fields:
        value = get_nested_value(data, field)
        if value is not None:
            # Convert to string
            if isinstance(value, (list, dict)):
                parts.append(json.dumps(value))
            else:
                parts.append(str(value))

    return "\n".join(parts)
