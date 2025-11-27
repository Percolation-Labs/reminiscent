"""
Models endpoint - List available LLM models.

Provides an OpenAI-compatible /v1/models endpoint listing all supported
LLM providers and their models using the provider:model_id syntax.

Endpoint:
    GET /api/v1/models - List all available models

Response format matches OpenAI API for drop-in compatibility.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1", tags=["models"])


class ModelInfo(BaseModel):
    """Information about a single model."""

    id: str = Field(description="Model ID in provider:model format")
    object: Literal["model"] = "model"
    created: int = Field(description="Unix timestamp of model availability")
    owned_by: str = Field(description="Provider name")
    description: str | None = Field(default=None, description="Model description")
    context_window: int | None = Field(default=None, description="Max context tokens")
    max_output_tokens: int | None = Field(default=None, description="Max output tokens")


class ModelsResponse(BaseModel):
    """Response from /models endpoint."""

    object: Literal["list"] = "list"
    data: list[ModelInfo]


# Model definitions with 2025 releases
# Using Unix timestamps for created dates (approximate release dates)
AVAILABLE_MODELS: list[ModelInfo] = [
    # ==========================================================================
    # OpenAI Models (2025)
    # ==========================================================================
    # GPT-4.1 series (Released April 14, 2025)
    ModelInfo(
        id="openai:gpt-4.1",
        created=1744588800,  # April 14, 2025
        owned_by="openai",
        description="Latest GPT-4 iteration, excels at coding and instruction following. 1M context.",
        context_window=1047576,
        max_output_tokens=32768,
    ),
    ModelInfo(
        id="openai:gpt-4.1-mini",
        created=1744588800,
        owned_by="openai",
        description="Small model beating GPT-4o in many benchmarks. 83% cost reduction vs GPT-4o.",
        context_window=1047576,
        max_output_tokens=32768,
    ),
    ModelInfo(
        id="openai:gpt-4.1-nano",
        created=1744588800,
        owned_by="openai",
        description="Fastest and cheapest OpenAI model. Ideal for classification and autocompletion.",
        context_window=1047576,
        max_output_tokens=32768,
    ),
    # GPT-4o (legacy but still supported)
    ModelInfo(
        id="openai:gpt-4o",
        created=1715644800,  # May 13, 2024
        owned_by="openai",
        description="Previous flagship multimodal model. Being superseded by GPT-4.1.",
        context_window=128000,
        max_output_tokens=16384,
    ),
    ModelInfo(
        id="openai:gpt-4o-mini",
        created=1721347200,  # July 18, 2024
        owned_by="openai",
        description="Cost-efficient smaller GPT-4o variant.",
        context_window=128000,
        max_output_tokens=16384,
    ),
    # o1 reasoning models
    ModelInfo(
        id="openai:o1",
        created=1733961600,  # December 12, 2024
        owned_by="openai",
        description="Advanced reasoning model for complex problems. Extended thinking.",
        context_window=200000,
        max_output_tokens=100000,
    ),
    ModelInfo(
        id="openai:o1-mini",
        created=1726099200,  # September 12, 2024
        owned_by="openai",
        description="Smaller reasoning model, fast for coding and math.",
        context_window=128000,
        max_output_tokens=65536,
    ),
    ModelInfo(
        id="openai:o3-mini",
        created=1738195200,  # January 30, 2025
        owned_by="openai",
        description="Latest mini reasoning model with improved performance.",
        context_window=200000,
        max_output_tokens=100000,
    ),
    # ==========================================================================
    # Anthropic Models (2025)
    # ==========================================================================
    # Claude 4.5 series (Latest - November 2025)
    ModelInfo(
        id="anthropic:claude-opus-4-5-20251124",
        created=1732406400,  # November 24, 2025
        owned_by="anthropic",
        description="Most capable Claude model. World-class coding with 'effort' parameter control.",
        context_window=200000,
        max_output_tokens=128000,
    ),
    ModelInfo(
        id="anthropic:claude-sonnet-4-5-20250929",
        created=1727568000,  # September 29, 2025
        owned_by="anthropic",
        description="Best balance of intelligence and speed. Excellent for coding and agents.",
        context_window=200000,
        max_output_tokens=128000,
    ),
    ModelInfo(
        id="anthropic:claude-haiku-4-5-20251101",
        created=1730419200,  # November 1, 2025
        owned_by="anthropic",
        description="Fast and affordable. Sonnet 4 performance at 1/3 cost. Safest Claude model.",
        context_window=200000,
        max_output_tokens=128000,
    ),
    # Claude 4 series
    ModelInfo(
        id="anthropic:claude-opus-4-20250514",
        created=1715644800,  # May 14, 2025
        owned_by="anthropic",
        description="World's best coding model. Sustained performance on complex agent workflows.",
        context_window=200000,
        max_output_tokens=128000,
    ),
    ModelInfo(
        id="anthropic:claude-sonnet-4-20250514",
        created=1715644800,  # May 14, 2025
        owned_by="anthropic",
        description="Significant upgrade to Sonnet 3.7. Great for everyday tasks.",
        context_window=200000,
        max_output_tokens=128000,
    ),
    ModelInfo(
        id="anthropic:claude-opus-4-1-20250805",
        created=1722816000,  # August 5, 2025
        owned_by="anthropic",
        description="Opus 4 upgrade focused on agentic tasks and real-world coding.",
        context_window=200000,
        max_output_tokens=128000,
    ),
    # Aliases for convenience
    ModelInfo(
        id="anthropic:claude-opus-4-5",
        created=1732406400,
        owned_by="anthropic",
        description="Alias for latest Claude Opus 4.5",
        context_window=200000,
        max_output_tokens=128000,
    ),
    ModelInfo(
        id="anthropic:claude-sonnet-4-5",
        created=1727568000,
        owned_by="anthropic",
        description="Alias for latest Claude Sonnet 4.5",
        context_window=200000,
        max_output_tokens=128000,
    ),
    ModelInfo(
        id="anthropic:claude-haiku-4-5",
        created=1730419200,
        owned_by="anthropic",
        description="Alias for latest Claude Haiku 4.5",
        context_window=200000,
        max_output_tokens=128000,
    ),
    # ==========================================================================
    # Google Models (2025)
    # ==========================================================================
    # Gemini 3 (Latest)
    ModelInfo(
        id="google:gemini-3-pro",
        created=1730419200,  # November 2025
        owned_by="google",
        description="Most advanced Gemini. State-of-the-art reasoning, 35% better than 2.5 Pro.",
        context_window=2000000,
        max_output_tokens=65536,
    ),
    # Gemini 2.5 series
    ModelInfo(
        id="google:gemini-2.5-pro",
        created=1727568000,  # September 2025
        owned_by="google",
        description="High-capability model with adaptive thinking. 1M context window.",
        context_window=1000000,
        max_output_tokens=65536,
    ),
    ModelInfo(
        id="google:gemini-2.5-flash",
        created=1727568000,
        owned_by="google",
        description="Fast and capable. Best for large-scale processing and agentic tasks.",
        context_window=1000000,
        max_output_tokens=65536,
    ),
    ModelInfo(
        id="google:gemini-2.5-flash-lite",
        created=1727568000,
        owned_by="google",
        description="Optimized for massive scale. Balances cost and performance.",
        context_window=1000000,
        max_output_tokens=32768,
    ),
    # Gemini 2.0
    ModelInfo(
        id="google:gemini-2.0-flash",
        created=1733875200,  # December 2024
        owned_by="google",
        description="Fast multimodal model with native tool use.",
        context_window=1000000,
        max_output_tokens=8192,
    ),
    # Gemma open models
    ModelInfo(
        id="google:gemma-3",
        created=1727568000,
        owned_by="google",
        description="Open model with text/image input, 140+ languages, 128K context.",
        context_window=128000,
        max_output_tokens=8192,
    ),
    ModelInfo(
        id="google:gemma-3n",
        created=1730419200,
        owned_by="google",
        description="Efficient open model for low-resource devices. Multimodal input.",
        context_window=128000,
        max_output_tokens=8192,
    ),
]


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """
    List all available LLM models.

    Returns models from all supported providers (OpenAI, Anthropic, Google)
    with the provider:model_id naming convention.

    Response format is OpenAI-compatible for drop-in replacement.
    """
    return ModelsResponse(data=AVAILABLE_MODELS)


@router.get("/models/{model_id:path}", response_model=ModelInfo)
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
    from fastapi import HTTPException

    for model in AVAILABLE_MODELS:
        if model.id == model_id:
            return model

    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
