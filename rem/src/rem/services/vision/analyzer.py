"""
Pydantic AI-based vision analyzer with full OpenTelemetry tracing.

Provides vision analysis capabilities using multimodal LLMs (Claude, GPT-4, Gemini).
All API calls go through Pydantic AI for proper tracing and cost tracking.
"""

import os
from enum import Enum
from pathlib import Path
from typing import Optional

from loguru import logger
from pydantic_ai import Agent, BinaryContent


class VisionProvider(str, Enum):
    """Supported vision providers."""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"


# Available models for each provider
AVAILABLE_MODELS = {
    VisionProvider.ANTHROPIC: {
        "claude-sonnet-4": "anthropic:claude-sonnet-4-20250514",
        "claude-sonnet-4.5": "anthropic:claude-sonnet-4-5-20250929",
    },
    VisionProvider.OPENAI: {
        "gpt-4.1": "openai:gpt-4.1",
        "gpt-4o": "openai:gpt-4o",
    },
    VisionProvider.GEMINI: {
        "gemini-2.0-flash": "google-gla:gemini-2.0-flash",
    },
}

# Default model for each provider (can be overridden by VISION_MODEL env var)
DEFAULT_MODELS = {
    VisionProvider.ANTHROPIC: "claude-sonnet-4",
    VisionProvider.OPENAI: "gpt-4.1",
    VisionProvider.GEMINI: "gemini-2.0-flash",
}

# MIME types for common image formats
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def get_model_id(provider: VisionProvider, model_override: Optional[str] = None) -> str:
    """
    Get the Pydantic AI model identifier for a provider.

    Args:
        provider: The vision provider
        model_override: Optional model name override (e.g., "claude-sonnet-4.5")

    Returns:
        Pydantic AI model identifier (e.g., "anthropic:claude-sonnet-4-5-20250929")
    """
    # Check for environment variable override
    env_model = os.environ.get("VISION_MODEL")

    # Priority: function param > env var > default
    model_name = model_override or env_model or DEFAULT_MODELS.get(provider)

    # Look up the full model identifier
    provider_models = AVAILABLE_MODELS.get(provider, {})

    if model_name in provider_models:
        return provider_models[model_name]

    # If exact match not found, check if it's already a full model ID
    if model_name and ":" in model_name:
        return model_name

    # Fall back to default
    default_name = DEFAULT_MODELS.get(provider)
    return provider_models.get(default_name, f"{provider.value}:{default_name}")


class VisionResult:
    """Result from image vision analysis."""

    def __init__(
        self,
        description: str,
        provider: VisionProvider,
        model: str,
        usage: Optional[dict] = None,
    ):
        self.description = description
        self.provider = provider
        self.model = model
        self.usage = usage or {}

    def __repr__(self) -> str:
        tokens = self.usage.get("total_tokens", "?")
        return f"VisionResult(provider={self.provider.value}, model={self.model}, tokens={tokens})"


async def analyze_image_async(
    image_data: bytes,
    prompt: str,
    provider: VisionProvider = VisionProvider.ANTHROPIC,
    media_type: str = "image/png",
    model: Optional[str] = None,
) -> VisionResult:
    """
    Analyze single image using Pydantic AI (async version).

    All API calls go through Pydantic AI, enabling:
    - OpenTelemetry tracing
    - Token counting
    - Cost calculation via genai-prices

    Args:
        image_data: Raw image bytes
        prompt: Analysis prompt
        provider: Vision provider to use
        media_type: MIME type of image
        model: Optional model override

    Returns:
        VisionResult with description and usage stats
    """
    model_id = get_model_id(provider, model)

    logger.info(f"Vision analysis with {provider.value} ({model_id})")

    # Create agent for this request
    agent = Agent(model=model_id)

    # Run with image content
    result = await agent.run([
        prompt,
        BinaryContent(data=image_data, media_type=media_type),
    ])

    # Extract usage information
    usage = _extract_usage(result)

    logger.info(f"Vision analysis complete: {len(result.output)} chars, {usage.get('total_tokens', '?')} tokens")

    return VisionResult(
        description=result.output,
        provider=provider,
        model=model_id,
        usage=usage,
    )


async def analyze_images_async(
    images: list[tuple[bytes, str]],
    prompt: str,
    provider: VisionProvider = VisionProvider.ANTHROPIC,
    model: Optional[str] = None,
) -> VisionResult:
    """
    Analyze multiple images in a single API call using Pydantic AI (async version).

    This is more efficient than multiple single-image calls as it batches
    images together, reducing API overhead and enabling cross-page context.

    Args:
        images: List of (image_bytes, media_type) tuples
        prompt: Analysis prompt (applied to all images)
        provider: Vision provider to use
        model: Optional model override (e.g., "claude-sonnet-4.5", "gpt-4.1")

    Returns:
        VisionResult with combined description and usage stats
    """
    model_id = get_model_id(provider, model)

    logger.info(f"Multi-image vision analysis with {provider.value} ({model_id}), {len(images)} images")

    # Create agent for this request
    agent = Agent(model=model_id)

    # Build message content with prompt followed by all images
    content: list = [prompt]
    for image_data, media_type in images:
        content.append(BinaryContent(data=image_data, media_type=media_type))

    # Run with all images
    result = await agent.run(content)

    # Extract usage information
    usage = _extract_usage(result)

    logger.info(f"Multi-image analysis complete: {len(result.output)} chars, {usage.get('total_tokens', '?')} tokens")

    return VisionResult(
        description=result.output,
        provider=provider,
        model=model_id,
        usage=usage,
    )


def analyze_image_file(
    image_path: str | Path,
    prompt: str,
    provider: VisionProvider = VisionProvider.ANTHROPIC,
    model: Optional[str] = None,
) -> VisionResult:
    """
    Analyze image file using Pydantic AI (sync version).

    Convenience wrapper that reads file and detects MIME type.

    Args:
        image_path: Path to image file
        prompt: Analysis prompt
        provider: Vision provider to use
        model: Optional model override

    Returns:
        VisionResult with description and usage stats
    """
    import asyncio

    path = Path(image_path)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")

    # Detect MIME type
    suffix = path.suffix.lower()
    media_type = MIME_TYPES.get(suffix, "image/png")

    # Read image data
    image_data = path.read_bytes()

    # Run async function
    return asyncio.run(
        analyze_image_async(
            image_data=image_data,
            prompt=prompt,
            provider=provider,
            media_type=media_type,
            model=model,
        )
    )


def _extract_usage(result) -> dict:
    """Extract usage information from Pydantic AI result."""
    usage = {}
    if hasattr(result, 'usage') and callable(result.usage):
        run_usage = result.usage()
        usage = {
            "input_tokens": getattr(run_usage, 'input_tokens', 0),
            "output_tokens": getattr(run_usage, 'output_tokens', 0),
            "total_tokens": getattr(run_usage, 'total_tokens', 0),
            "requests": getattr(run_usage, 'requests', 0),
        }
    return usage
