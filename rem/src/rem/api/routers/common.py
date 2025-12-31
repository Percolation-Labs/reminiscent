"""
Common models shared across API routers.
"""

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response format for HTTPException errors.

    This is different from FastAPI's HTTPValidationError which is used
    for Pydantic validation failures (422 errors with loc/msg/type array).

    HTTPException errors return this simpler format:
        {"detail": "Error message here"}
    """

    detail: str = Field(description="Error message describing what went wrong")
