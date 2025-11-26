"""
Embeddings utility for generating vector embeddings using various providers.

Uses requests library for HTTP calls (no provider SDKs required).
Supports batch processing to optimize API usage and respect rate limits.
Uses tenacity for automatic retry with exponential backoff.

Supported Providers:
- OpenAI: text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002
- Anthropic: voyage-2 (via Voyage AI)

Usage:
    from rem.utils.embeddings import generate_embeddings

    # Single text
    embedding = generate_embeddings("openai:text-embedding-3-small", "Hello world")

    # Batch processing
    texts = ["Hello world", "How are you?", "Good morning"]
    embeddings = generate_embeddings("openai:text-embedding-3-small", texts)
"""

from typing import Any, cast

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from rem.utils.constants import (
    HTTP_TIMEOUT_LONG,
    OPENAI_EMBEDDING_DIMS_SMALL,
    OPENAI_EMBEDDING_DIMS_LARGE,
    VOYAGE_EMBEDDING_DIMS,
    RETRY_BACKOFF_MULTIPLIER,
    RETRY_BACKOFF_MIN,
    RETRY_BACKOFF_MAX,
)


class EmbeddingError(Exception):
    """Base exception for embedding generation errors."""

    pass


class RateLimitError(EmbeddingError):
    """Raised when rate limit is exceeded."""

    pass


def generate_embeddings(
    embedding_provider: str,
    texts: str | list[str],
    api_key: str | None = None,
    max_retries: int = 1,
) -> list[float] | list[list[float]]:
    """
    Generate embeddings for text(s) using specified provider.

    Uses tenacity for automatic retry with exponential backoff on rate limits.

    Args:
        embedding_provider: Provider and model in format "provider:model_name"
                          (e.g., "openai:text-embedding-3-small")
        texts: Single text string or list of texts to embed
        api_key: API key for the provider. If None, reads from environment variables:
                - OpenAI: OPENAI_API_KEY or LLM__OPENAI_API_KEY
                - Anthropic: ANTHROPIC_API_KEY or LLM__ANTHROPIC_API_KEY
        max_retries: Maximum number of retry attempts for rate limits (default: 1)

    Returns:
        - If single text: list[float] (single embedding vector)
        - If list of texts: list[list[float]] (list of embedding vectors)

    Raises:
        EmbeddingError: If embedding generation fails
        RateLimitError: If rate limit exceeded after retries
        ValueError: If provider format is invalid

    Examples:
        >>> embedding = generate_embeddings("openai:text-embedding-3-small", "Hello")
        >>> len(embedding)
        1536

        >>> embeddings = generate_embeddings(
        ...     "openai:text-embedding-3-small",
        ...     ["Hello", "World"]
        ... )
        >>> len(embeddings)
        2
    """
    # Parse provider format
    if ":" not in embedding_provider:
        raise ValueError(
            f"Invalid embedding_provider format: {embedding_provider}. "
            f"Expected format: 'provider:model_name'"
        )

    provider, model_name = embedding_provider.split(":", 1)
    provider = provider.lower()

    # Normalize input to list
    if isinstance(texts, str):
        text_list: list[str] = [texts]
        is_single = True
    else:
        text_list = texts
        is_single = False

    # Validate input
    if not text_list:
        raise ValueError("texts cannot be empty")

    # Get API key from environment if not provided
    if api_key is None:
        api_key = _get_api_key(provider)

    # Generate embeddings (tenacity handles retries)
    if provider == "openai":
        embeddings = _generate_openai_embeddings_with_retry(
            model_name, text_list, api_key, max_retries
        )
    elif provider == "anthropic":
        # Anthropic uses Voyage AI for embeddings
        embeddings = _generate_voyage_embeddings_with_retry(
            model_name, text_list, api_key, max_retries
        )
    else:
        raise ValueError(f"Unsupported embedding provider: {provider}")

    # Return single embedding or list based on input
    return embeddings[0] if is_single else embeddings


def _get_api_key(provider: str) -> str:
    """
    Get API key from environment variables.

    Args:
        provider: Provider name (openai, anthropic)

    Returns:
        API key string

    Raises:
        ValueError: If API key not found in environment
    """
    from ..settings import settings

    if provider == "openai":
        api_key = settings.llm.openai_api_key
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Set LLM__OPENAI_API_KEY environment variable."
            )
        return api_key
    elif provider == "anthropic":
        api_key = settings.llm.anthropic_api_key
        if not api_key:
            raise ValueError(
                "Anthropic API key not found. Set LLM__ANTHROPIC_API_KEY environment variable."
            )
        return api_key
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _create_retry_decorator(max_retries: int):
    """Create a retry decorator with exponential backoff."""
    return retry(
        retry=retry_if_exception_type(RateLimitError),
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(
            multiplier=RETRY_BACKOFF_MULTIPLIER,
            min=RETRY_BACKOFF_MIN,
            max=RETRY_BACKOFF_MAX,
        ),
        reraise=True,
    )


def _generate_openai_embeddings_with_retry(
    model: str, texts: list[str], api_key: str, max_retries: int
) -> list[list[float]]:
    """
    Generate embeddings using OpenAI API with automatic retry.

    Uses tenacity for exponential backoff on rate limits.

    Args:
        model: OpenAI model name (e.g., "text-embedding-3-small")
        texts: List of texts to embed
        api_key: OpenAI API key
        max_retries: Maximum number of retry attempts

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingError: If API request fails
        RateLimitError: If rate limit exceeded after retries
    """
    # Create retry decorator dynamically based on max_retries
    retry_decorator = _create_retry_decorator(max_retries)

    @retry_decorator
    def _call_api():
        return _generate_openai_embeddings(model, texts, api_key)

    return cast(list[list[float]], _call_api())


def _generate_openai_embeddings(
    model: str, texts: list[str], api_key: str
) -> list[list[float]]:
    """
    Generate embeddings using OpenAI API (internal, no retry).

    API Docs: https://platform.openai.com/docs/api-reference/embeddings

    Args:
        model: OpenAI model name (e.g., "text-embedding-3-small")
        texts: List of texts to embed
        api_key: OpenAI API key

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingError: If API request fails
        RateLimitError: If rate limit exceeded
    """
    url = "https://api.openai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "input": texts,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT_LONG)

        # Handle rate limits
        if response.status_code == 429:
            raise RateLimitError(
                f"OpenAI rate limit exceeded: {response.json().get('error', {}).get('message', 'Unknown error')}"
            )

        # Handle other errors
        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", "Unknown error")
            raise EmbeddingError(
                f"OpenAI API error (status {response.status_code}): {error_msg}"
            )

        # Extract embeddings from response
        data = response.json()
        embeddings_data = data.get("data", [])

        # Sort by index to maintain order (API may return out of order)
        embeddings_data.sort(key=lambda x: x.get("index", 0))

        embeddings = [item["embedding"] for item in embeddings_data]

        if len(embeddings) != len(texts):
            raise EmbeddingError(
                f"Expected {len(texts)} embeddings, got {len(embeddings)}"
            )

        return embeddings

    except requests.exceptions.Timeout:
        raise EmbeddingError("OpenAI API request timed out")
    except requests.exceptions.RequestException as e:
        raise EmbeddingError(f"OpenAI API request failed: {str(e)}")


def _generate_voyage_embeddings_with_retry(
    model: str, texts: list[str], api_key: str, max_retries: int
) -> list[list[float]]:
    """
    Generate embeddings using Voyage AI API with automatic retry.

    Uses tenacity for exponential backoff on rate limits.

    Args:
        model: Voyage model name (e.g., "voyage-2")
        texts: List of texts to embed
        api_key: Voyage AI API key
        max_retries: Maximum number of retry attempts

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingError: If API request fails
        RateLimitError: If rate limit exceeded after retries
    """
    # Create retry decorator dynamically based on max_retries
    retry_decorator = _create_retry_decorator(max_retries)

    @retry_decorator
    def _call_api():
        return _generate_voyage_embeddings(model, texts, api_key)

    return cast(list[list[float]], _call_api())


def _generate_voyage_embeddings(
    model: str, texts: list[str], api_key: str
) -> list[list[float]]:
    """
    Generate embeddings using Voyage AI API (internal, no retry).

    API Docs: https://docs.voyageai.com/docs/embeddings

    Args:
        model: Voyage model name (e.g., "voyage-2")
        texts: List of texts to embed
        api_key: Voyage AI API key

    Returns:
        List of embedding vectors

    Raises:
        EmbeddingError: If API request fails
        RateLimitError: If rate limit exceeded
    """
    url = "https://api.voyageai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "input": texts,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=HTTP_TIMEOUT_LONG)

        # Handle rate limits
        if response.status_code == 429:
            raise RateLimitError(
                f"Voyage AI rate limit exceeded: {response.json().get('error', {}).get('message', 'Unknown error')}"
            )

        # Handle other errors
        if response.status_code != 200:
            error_msg = response.json().get("error", {}).get("message", "Unknown error")
            raise EmbeddingError(
                f"Voyage AI API error (status {response.status_code}): {error_msg}"
            )

        # Extract embeddings from response
        data = response.json()
        embeddings_data = data.get("data", [])

        embeddings = [item["embedding"] for item in embeddings_data]

        if len(embeddings) != len(texts):
            raise EmbeddingError(
                f"Expected {len(texts)} embeddings, got {len(embeddings)}"
            )

        return embeddings

    except requests.exceptions.Timeout:
        raise EmbeddingError("Voyage AI API request timed out")
    except requests.exceptions.RequestException as e:
        raise EmbeddingError(f"Voyage AI API request failed: {str(e)}")


def get_embedding_dimension(embedding_provider: str) -> int:
    """
    Get embedding dimension for a given provider and model.

    Args:
        embedding_provider: Provider and model in format "provider:model_name"

    Returns:
        Embedding dimension (vector length)

    Raises:
        ValueError: If provider/model is unknown

    Examples:
        >>> get_embedding_dimension("openai:text-embedding-3-small")
        1536
        >>> get_embedding_dimension("openai:text-embedding-3-large")
        3072
    """
    if ":" not in embedding_provider:
        raise ValueError(
            f"Invalid embedding_provider format: {embedding_provider}. "
            f"Expected format: 'provider:model_name'"
        )

    provider, model_name = embedding_provider.split(":", 1)
    provider = provider.lower()

    # OpenAI dimensions
    openai_dimensions = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    # Voyage AI dimensions
    voyage_dimensions = {
        "voyage-2": 1024,
        "voyage-large-2": 1536,
        "voyage-code-2": 1536,
    }

    if provider == "openai":
        if model_name in openai_dimensions:
            return openai_dimensions[model_name]
        raise ValueError(f"Unknown OpenAI model: {model_name}")
    elif provider == "anthropic":
        # Anthropic uses Voyage AI
        if model_name in voyage_dimensions:
            return voyage_dimensions[model_name]
        raise ValueError(f"Unknown Voyage AI model: {model_name}")
    else:
        raise ValueError(f"Unknown provider: {provider}")
