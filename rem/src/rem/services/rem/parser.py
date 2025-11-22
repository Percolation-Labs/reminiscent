import shlex
from typing import Any, Dict, List, Optional, Tuple, Union

from ...models.core import QueryType


class RemQueryParser:
    """
    Robust parser for REM query language using shlex for proper quoting support.
    """

    def parse(self, query_string: str) -> Tuple[QueryType, Dict[str, Any]]:
        """
        Parse a REM query string into a QueryType and a dictionary of parameters.

        Args:
            query_string: The raw query string (e.g., 'LOOKUP "Sarah Chen"').

        Returns:
            Tuple of (QueryType, parameters_dict).

        Raises:
            ValueError: If the query string is empty or has an invalid query type.
        """
        if not query_string or not query_string.strip():
            raise ValueError("Empty query string")

        try:
            # Use shlex to handle quoted strings correctly
            tokens = shlex.split(query_string)
        except ValueError as e:
            raise ValueError(f"Failed to parse query string: {e}")

        if not tokens:
            raise ValueError("Empty query string")

        query_type_str = tokens[0].upper()
        try:
            query_type = QueryType(query_type_str)
        except ValueError:
            raise ValueError(f"Invalid query type: {query_type_str}")

        params: Dict[str, Any] = {}
        positional_args: List[str] = []

        # Process remaining tokens
        for token in tokens[1:]:
            if "=" in token:
                # It's a keyword argument
                key, value = token.split("=", 1)
                # Handle parameter aliases
                mapped_key = self._map_parameter_alias(key)
                params[mapped_key] = self._convert_value(mapped_key, value)
            else:
                # It's a positional argument part
                positional_args.append(token)

        # Map positional arguments to specific fields based on QueryType
        self._map_positional_args(query_type, positional_args, params)

        return query_type, params

    def _map_parameter_alias(self, key: str) -> str:
        """
        Map common aliases to internal model field names.
        """
        aliases = {
            "table": "table_name",
            "field": "field_name",
            "where": "where_clause",
            "depth": "max_depth",
            "rel_type": "edge_types",
            "rel_types": "edge_types",
        }
        return aliases.get(key, key)

    def _convert_value(self, key: str, value: str) -> Union[str, int, float, List[str]]:
        """
        Convert string values to appropriate types based on the key name.
        """
        # Integer fields
        if key in ("limit", "max_depth", "depth", "limit"):
            try:
                return int(value)
            except ValueError:
                return value  # Return as string if conversion fails (validation will catch it)

        # Float fields
        if key in ("threshold", "min_similarity"):
            try:
                return float(value)
            except ValueError:
                return value

        # List fields (comma-separated)
        if key in ("edge_types", "tags"):
            return [v.strip() for v in value.split(",")]

        # Default to string
        return value

    def _map_positional_args(
        self, query_type: QueryType, positional_args: List[str], params: Dict[str, Any]
    ) -> None:
        """
        Map accumulated positional arguments to the primary field for the query type.
        """
        if not positional_args:
            return

        # Join positional args with space to reconstruct the text
        # This handles cases where the user didn't quote a multi-word string
        # e.g. FUZZY Sarah Chen -> "Sarah Chen"
        combined_value = " ".join(positional_args)

        if query_type == QueryType.LOOKUP:
            # LOOKUP supports list of keys, but as positional arg we treat as single key or comma-separated
            # If the user provided "key1 key2", it might be interpreted as one key "key1 key2"
            # or multiple keys. For now, let's assume it's a single key entity name unless it has commas.
            if "," in combined_value:
                 params["key"] = [k.strip() for k in combined_value.split(",")]
            else:
                 params["key"] = combined_value

        elif query_type == QueryType.FUZZY:
            params["query_text"] = combined_value

        elif query_type == QueryType.SEARCH:
            params["query_text"] = combined_value

        elif query_type == QueryType.TRAVERSE:
            params["initial_query"] = combined_value
        
        # SQL typically requires named arguments (table=...), but if we supported 
        # SQL SELECT * FROM ..., we might handle it differently. 
        # For now, RemService expects table=...
        # If there are positional args for SQL, we might ignore or raise, 
        # but current service doesn't use them.
