"""
CLIP embeddings utility using Jina AI API.

Provides image and text embeddings using Jina CLIP models via API.
Falls back gracefully when API key is not available.

Future: Can be extended to support self-hosted CLIP models or other providers.
"""

import base64
import os
from pathlib import Path
from typing import Optional

import requests
from loguru import logger


class CLIPEmbeddingResult:
    """Result from CLIP embedding generation."""

    def __init__(
        self,
        embedding: list[float],
        model: str,
        input_type: str,
        tokens_used: int = 0,
    ):
        """
        Initialize CLIP embedding result.

        Args:
            embedding: Vector embedding (512 or 768 dimensions)
            model: Model name used
            input_type: Type of input (image or text)
            tokens_used: Number of tokens consumed (for cost tracking)
        """
        self.embedding = embedding
        self.model = model
        self.input_type = input_type
        self.tokens_used = tokens_used

    @property
    def dimensions(self) -> int:
        """Get embedding dimensionality."""
        return len(self.embedding)

    def __repr__(self) -> str:
        return f"CLIPEmbeddingResult(model={self.model}, dims={self.dimensions}, tokens={self.tokens_used})"


class JinaCLIPEmbedder:
    """
    CLIP embeddings using Jina AI API.

    Supports:
    - jina-clip-v1: 768-dimensional embeddings
    - jina-clip-v2: 512-dimensional embeddings (default)

    Pricing:
    - ~$0.02 per million tokens
    - Images: 4000 tokens per 512x512 tile (v2)
    - Images: 1000 tokens per 224x224 tile (v1)
    - Free tier: 10M tokens for new users

    Future extensions:
    - Self-hosted CLIP models
    - OpenCLIP support
    - Batch embedding support
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "jina-clip-v2",
    ):
        """
        Initialize Jina CLIP embedder.

        Args:
            api_key: Jina AI API key (from env if None)
            model: CLIP model name (jina-clip-v1 or jina-clip-v2)
        """
        # Get API key from environment if not provided
        # Check both CONTENT__JINA_API_KEY (preferred) and legacy JINA_API_KEY
        if api_key is None:
            api_key = os.getenv("CONTENT__JINA_API_KEY") or os.getenv("JINA_API_KEY")

        self.api_key = api_key
        self.model = model
        self.api_url = "https://api.jina.ai/v1/embeddings"

        # Warn if no API key
        if not self.api_key:
            logger.warning(
                "No Jina API key found - CLIP embeddings will be disabled. "
                "Set CONTENT__JINA_API_KEY or get a free key at https://jina.ai/embeddings/"
            )

    def is_available(self) -> bool:
        """Check if Jina CLIP embeddings are available."""
        return self.api_key is not None

    def embed_image(
        self,
        image_path: str | Path,
    ) -> Optional[CLIPEmbeddingResult]:
        """
        Generate CLIP embedding for an image.

        Args:
            image_path: Path to image file

        Returns:
            CLIPEmbeddingResult with embedding vector, or None if unavailable

        Raises:
            RuntimeError: If API request fails (when API key is available)
        """
        if not self.is_available():
            logger.debug("Jina API key not available - skipping CLIP embedding")
            return None

        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Read and encode image to base64
        with open(image_path, "rb") as f:
            image_bytes = f.read()

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Detect media type
        suffix = image_path.suffix.lower()
        media_type_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_type_map.get(suffix, "image/png")

        logger.debug(f"Generating CLIP embedding for {image_path.name} with {self.model}")

        try:
            # Build request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            # Jina API expects data URL format
            data_url = f"data:{media_type};base64,{image_b64}"

            body = {
                "model": self.model,
                "input": [data_url],
                "input_type": "image",
            }

            response = requests.post(
                self.api_url,
                headers=headers,
                json=body,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_detail = response.text
                logger.error(f"Jina API error: {response.status_code} - {error_detail}")
                raise RuntimeError(f"CLIP embedding failed: {response.status_code} - {error_detail}")

            result = response.json()

            # Extract embedding and usage
            embedding = result["data"][0]["embedding"]
            tokens_used = result.get("usage", {}).get("total_tokens", 0)

            logger.info(
                f"✓ CLIP embedding generated: {len(embedding)} dims, {tokens_used} tokens"
            )

            return CLIPEmbeddingResult(
                embedding=embedding,
                model=self.model,
                input_type="image",
                tokens_used=tokens_used,
            )

        except requests.exceptions.Timeout:
            logger.error("Jina API request timed out")
            raise RuntimeError("CLIP embedding timed out after 30 seconds")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise RuntimeError(f"CLIP embedding request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during CLIP embedding: {e}")
            raise

    def embed_text(
        self,
        text: str,
    ) -> Optional[CLIPEmbeddingResult]:
        """
        Generate CLIP embedding for text.

        Useful for text-to-image search in shared embedding space.

        Args:
            text: Text to embed

        Returns:
            CLIPEmbeddingResult with embedding vector, or None if unavailable

        Raises:
            RuntimeError: If API request fails (when API key is available)
        """
        if not self.is_available():
            logger.debug("Jina API key not available - skipping CLIP embedding")
            return None

        logger.debug(f"Generating CLIP text embedding with {self.model}")

        try:
            # Build request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            body = {
                "model": self.model,
                "input": [text],
                "input_type": "text",
            }

            response = requests.post(
                self.api_url,
                headers=headers,
                json=body,
                timeout=30.0,
            )

            if response.status_code != 200:
                error_detail = response.text
                logger.error(f"Jina API error: {response.status_code} - {error_detail}")
                raise RuntimeError(f"CLIP embedding failed: {response.status_code} - {error_detail}")

            result = response.json()

            # Extract embedding and usage
            embedding = result["data"][0]["embedding"]
            tokens_used = result.get("usage", {}).get("total_tokens", 0)

            logger.info(
                f"✓ CLIP text embedding generated: {len(embedding)} dims, {tokens_used} tokens"
            )

            return CLIPEmbeddingResult(
                embedding=embedding,
                model=self.model,
                input_type="text",
                tokens_used=tokens_used,
            )

        except requests.exceptions.Timeout:
            logger.error("Jina API request timed out")
            raise RuntimeError("CLIP embedding timed out after 30 seconds")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise RuntimeError(f"CLIP embedding request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during CLIP embedding: {e}")
            raise
