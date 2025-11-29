"""
Embedding API utilities for generating embeddings from text.

Provides synchronous and async wrappers for embedding generation using
raw HTTP requests (no OpenAI SDK dependency).
"""

from typing import Optional, cast

import httpx
import requests
from loguru import logger

from rem.utils.constants import DEFAULT_EMBEDDING_DIMS, HTTP_TIMEOUT_DEFAULT


def _get_openai_api_key() -> Optional[str]:
    """Get OpenAI API key from settings."""
    from rem.settings import settings
    return settings.llm.openai_api_key


def generate_embedding(
    text: str,
    model: str = "text-embedding-3-small",
    provider: str = "openai",
    api_key: Optional[str] = None,
) -> list[float]:
    """
    Generate embedding for a single text string using requests.

    Args:
        text: Text to embed
        model: Model name (default: text-embedding-3-small)
        provider: Provider name (default: openai)
        api_key: API key (defaults to settings.llm.openai_api_key)

    Returns:
        Embedding vector (1536 dimensions for text-embedding-3-small)
    """
    if provider == "openai":
        api_key = api_key or _get_openai_api_key()
        if not api_key:
            logger.warning("No OpenAI API key - returning zero vector")
            return [0.0] * DEFAULT_EMBEDDING_DIMS

        try:
            logger.debug(f"Generating OpenAI embedding for text using {model}")

            response = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": [text], "model": model},
                timeout=HTTP_TIMEOUT_DEFAULT,
            )
            response.raise_for_status()

            data = response.json()
            embedding = data["data"][0]["embedding"]
            logger.debug(f"Successfully generated embedding (dimension: {len(embedding)})")
            return cast(list[float], embedding)

        except Exception as e:
            logger.error(f"Failed to generate embedding from OpenAI: {e}", exc_info=True)
            return [0.0] * DEFAULT_EMBEDDING_DIMS

    else:
        logger.warning(f"Unsupported provider '{provider}' - returning zero vector")
        return [0.0] * DEFAULT_EMBEDDING_DIMS


async def generate_embedding_async(
    text: str,
    model: str = "text-embedding-3-small",
    provider: str = "openai",
    api_key: Optional[str] = None,
) -> list[float]:
    """
    Generate embedding for a single text string (async version) using httpx.

    Args:
        text: Text to embed
        model: Model name (default: text-embedding-3-small)
        provider: Provider name (default: openai)
        api_key: API key (defaults to settings.llm.openai_api_key)

    Returns:
        Embedding vector (1536 dimensions for text-embedding-3-small)
    """
    if provider == "openai":
        api_key = api_key or _get_openai_api_key()
        if not api_key:
            logger.warning("No OpenAI API key - returning zero vector")
            return [0.0] * DEFAULT_EMBEDDING_DIMS

        try:
            logger.debug(f"Generating OpenAI embedding for text using {model}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"input": [text], "model": model},
                    timeout=HTTP_TIMEOUT_DEFAULT,
                )
                response.raise_for_status()

                data = response.json()
                embedding = data["data"][0]["embedding"]
                logger.debug(
                    f"Successfully generated embedding (dimension: {len(embedding)})"
                )
                return cast(list[float], embedding)

        except Exception as e:
            logger.error(f"Failed to generate embedding from OpenAI: {e}", exc_info=True)
            return [0.0] * DEFAULT_EMBEDDING_DIMS

    else:
        logger.warning(f"Unsupported provider '{provider}' - returning zero vector")
        return [0.0] * DEFAULT_EMBEDDING_DIMS
