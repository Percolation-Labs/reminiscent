"""
Models endpoint - List available LLM models.

Provides an OpenAI-compatible /v1/models endpoint listing all supported
LLM providers and their models using the provider:model_id syntax.

Endpoint:
    GET /api/v1/models - List all available models

Response format matches OpenAI API for drop-in compatibility.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .common import ErrorResponse

from rem.agentic.llm_provider_models import (
    ModelInfo,
    AVAILABLE_MODELS,
    ALLOWED_MODEL_IDS,
    is_valid_model,
    get_valid_model_or_default,
    get_model_by_id,
)

router = APIRouter(prefix="/api/v1", tags=["models"])

# Re-export for backwards compatibility
__all__ = [
    "ModelInfo",
    "AVAILABLE_MODELS",
    "ALLOWED_MODEL_IDS",
    "is_valid_model",
    "get_valid_model_or_default",
    "get_model_by_id",
]


class ModelsResponse(BaseModel):
    """Response from /models endpoint."""

    object: Literal["list"] = "list"
    data: list[ModelInfo]


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """
    List all available LLM models.

    Returns models from all supported providers (OpenAI, Anthropic, Google, Cerebras)
    with the provider:model_id naming convention.

    Response format is OpenAI-compatible for drop-in replacement.
    """
    return ModelsResponse(data=AVAILABLE_MODELS)


@router.get(
    "/models/{model_id:path}",
    response_model=ModelInfo,
    responses={
        404: {"model": ErrorResponse, "description": "Model not found"},
    },
)
async def get_model(model_id: str) -> ModelInfo:
    """
    Get information about a specific model.

    Args:
        model_id: Model identifier in provider:model format (e.g., "openai:gpt-4.1")

    Returns:
        Model information if found

    Raises:
        HTTPException: 404 if model not found
    """
    model = get_model_by_id(model_id)
    if model:
        return model

    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
