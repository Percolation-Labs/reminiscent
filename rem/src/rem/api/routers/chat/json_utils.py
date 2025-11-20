"""
JSON extraction utilities for response_format='json_object' mode.

Design Pattern:
- Best-effort JSON extraction from agent output
- Handles fenced code blocks (```json ... ```)
- Handles raw JSON objects
- Graceful fallback to string if extraction fails
"""

import json
import re


def extract_json_resilient(output: str | dict | list) -> str:
    """
    Extract JSON from agent output with multiple fallback strategies.

    Strategies (in order):
    1. If already dict/list, serialize directly
    2. Extract from fenced JSON code blocks (```json ... ```)
    3. Find JSON object/array in text ({...} or [...])
    4. Return as-is if all strategies fail

    Args:
        output: Agent output (str, dict, or list)

    Returns:
        JSON string (best-effort)

    Examples:
        >>> extract_json_resilient({"answer": "test"})
        '{"answer": "test"}'

        >>> extract_json_resilient('Here is the result:\\n```json\\n{"answer": "test"}\\n```')
        '{"answer": "test"}'

        >>> extract_json_resilient('The answer is {"answer": "test"} as shown above.')
        '{"answer": "test"}'
    """
    # Strategy 1: Already structured
    if isinstance(output, (dict, list)):
        return json.dumps(output)

    text = str(output)

    # Strategy 2: Extract from fenced code blocks
    fenced_match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if fenced_match:
        try:
            json_str = fenced_match.group(1).strip()
            # Validate it's valid JSON
            json.loads(json_str)
            return json_str
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find JSON object or array
    # Look for {...} or [...]
    for pattern in [
        r"\{[^{}]*\}",  # Simple object
        r"\{.*\}",  # Nested object
        r"\[.*\]",  # Array
    ]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                json_str = match.group(0)
                # Validate it's valid JSON
                json.loads(json_str)
                return json_str
            except json.JSONDecodeError:
                continue

    # Strategy 4: Fallback to string
    return text
