"""
REM service exceptions.

Custom exceptions for REM query execution errors.
"""


class REMException(Exception):
    """Base exception for REM service errors."""

    pass


class FieldNotFoundError(REMException):
    """Raised when a field does not exist in the model."""

    def __init__(self, model_name: str, field_name: str, available_fields: list[str]):
        self.model_name = model_name
        self.field_name = field_name
        self.available_fields = available_fields
        super().__init__(
            f"Field '{field_name}' not found in model '{model_name}'. "
            f"Available fields: {', '.join(available_fields)}"
        )


class EmbeddingFieldNotFoundError(REMException):
    """Raised when trying to search on a field that has no embeddings."""

    def __init__(self, model_name: str, field_name: str, embeddable_fields: list[str]):
        self.model_name = model_name
        self.field_name = field_name
        self.embeddable_fields = embeddable_fields
        msg = (
            f"Field '{field_name}' in model '{model_name}' does not have embeddings. "
        )
        if embeddable_fields:
            msg += f"Embeddable fields: {', '.join(embeddable_fields)}"
        else:
            msg += "No embeddable fields configured for this model."
        super().__init__(msg)


class ContentFieldNotFoundError(REMException):
    """Raised when model has no 'content' field for default embedding search."""

    def __init__(self, model_name: str, available_fields: list[str]):
        self.model_name = model_name
        self.available_fields = available_fields
        super().__init__(
            f"Model '{model_name}' has no 'content' field. "
            f"Available fields: {', '.join(available_fields)}. "
            f"Specify field_name explicitly in SearchParameters."
        )


class QueryExecutionError(REMException):
    """Raised when REM query execution fails."""

    def __init__(self, query_type: str, message: str, original_error: Exception | None = None):
        self.query_type = query_type
        self.original_error = original_error
        super().__init__(f"{query_type} query failed: {message}")


class InvalidParametersError(REMException):
    """Raised when query parameters are invalid."""

    def __init__(self, query_type: str, message: str):
        self.query_type = query_type
        super().__init__(f"Invalid {query_type} parameters: {message}")
