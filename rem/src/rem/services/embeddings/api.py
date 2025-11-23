"""
Embedding API utilities for generating embeddings from text.

Provides synchronous and async wrappers for embedding generation using
raw HTTP requests (no OpenAI SDK dependency).
"""

import os
from typing import Optional, cast

import httpx
import requests
from loguru import logger


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
        api_key: API key (defaults to OPENAI_API_KEY env var)

    Returns:
        Embedding vector (1536 dimensions for text-embedding-3-small)
    """
    if provider == "openai":
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("No OpenAI API key - returning zero vector")
            return [0.0] * 1536

        try:
            logger.info(f"Generating OpenAI embedding for text using {model}")

            response = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"input": [text], "model": model},
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()
            embedding = data["data"][0]["embedding"]
            logger.info(f"Successfully generated embedding (dimension: {len(embedding)})")
            return cast(list[float], embedding)

        except Exception as e:
            logger.error(f"Failed to generate embedding from OpenAI: {e}", exc_info=True)
            return [0.0] * 1536

    else:
        logger.warning(f"Unsupported provider '{provider}' - returning zero vector")
        return [0.0] * 1536


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
        api_key: API key (defaults to OPENAI_API_KEY env var)

    Returns:
        Embedding vector (1536 dimensions for text-embedding-3-small)
    """
    if provider == "openai":
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            logger.warning("No OpenAI API key - returning zero vector")
            return [0.0] * 1536

        try:
            logger.info(f"Generating OpenAI embedding for text using {model}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"input": [text], "model": model},
                    timeout=30.0,
                )
                response.raise_for_status()

                data = response.json()
                embedding = data["data"][0]["embedding"]
                logger.info(
                    f"Successfully generated embedding (dimension: {len(embedding)})"
                )
                return cast(list[float], embedding)

        except Exception as e:
            logger.error(f"Failed to generate embedding from OpenAI: {e}", exc_info=True)
            return [0.0] * 1536

    else:
        logger.warning(f"Unsupported provider '{provider}' - returning zero vector")
        return [0.0] * 1536
