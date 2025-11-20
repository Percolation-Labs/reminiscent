"""
Vision utility for image analysis using multiple LLM providers.

Lightweight implementation supporting three providers:
- Anthropic Claude (claude-3-5-sonnet-20241022 or newer)
- Google Gemini (gemini-2.0-flash-exp or newer)
- OpenAI-compatible (gpt-4o, gpt-4-turbo, or compatible endpoints)

Handles image encoding and multimodal LLM requests for generating
markdown descriptions of images.
"""

import base64
import os
from enum import Enum
from pathlib import Path
from typing import Optional

import requests
from loguru import logger


class VisionProvider(str, Enum):
    """Supported vision providers."""

    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI = "openai"


class VisionResult:
    """Result from image vision analysis."""

    def __init__(
        self,
        description: str,
        provider: VisionProvider,
        model: str,
        confidence: float = 0.9,
    ):
        """
        Initialize vision result.

        Args:
            description: Markdown description of the image
            provider: Vision provider used
            model: Model name used
            confidence: Confidence score (0.0-1.0)
        """
        self.description = description
        self.provider = provider
        self.model = model
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"VisionResult(provider={self.provider.value}, model={self.model}, chars={len(self.description)})"


class ImageAnalyzer:
    """
    Analyze images using vision-enabled LLMs.

    Supports three providers with automatic provider selection based on API keys.
    """

    def __init__(
        self,
        provider: VisionProvider = VisionProvider.ANTHROPIC,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize image analyzer.

        Args:
            provider: Vision provider to use
            api_key: API key (from env if None)
            model: Model name (provider default if None)
            base_url: Custom base URL (for OpenAI-compatible endpoints)
        """
        self.provider = provider

        # Get API key from environment if not provided
        if api_key is None:
            if provider == VisionProvider.ANTHROPIC:
                api_key = os.getenv("ANTHROPIC_API_KEY")
            elif provider == VisionProvider.GEMINI:
                api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
            elif provider == VisionProvider.OPENAI:
                api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            logger.warning(f"No API key found for {provider.value} - vision analysis will fail")

        self.api_key = api_key

        # Set default models
        if model is None:
            if provider == VisionProvider.ANTHROPIC:
                model = "claude-3-5-sonnet-20241022"
            elif provider == VisionProvider.GEMINI:
                model = "gemini-2.0-flash-exp"
            elif provider == VisionProvider.OPENAI:
                model = "gpt-4o"

        self.model = model
        self.base_url = base_url

    def analyze_image(
        self,
        image_path: str | Path,
        prompt: str = "Describe this image in detail as markdown. Include key visual elements, text, diagrams, and context.",
    ) -> VisionResult:
        """
        Analyze image and generate markdown description.

        Args:
            image_path: Path to image file
            prompt: Analysis prompt for the LLM

        Returns:
            VisionResult with markdown description

        Raises:
            ValueError: If API key missing or file invalid
            RuntimeError: If API request fails
        """
        if not self.api_key:
            raise ValueError(f"API key required for {self.provider.value} vision analysis")

        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")

        # Read and encode image
        with open(image_path, "rb") as f:
            image_bytes = f.read()

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

        logger.info(f"Analyzing {image_path.name} with {self.provider.value} ({self.model})")

        # Route to provider-specific implementation
        if self.provider == VisionProvider.ANTHROPIC:
            description = self._analyze_anthropic(image_bytes, media_type, prompt)
        elif self.provider == VisionProvider.GEMINI:
            description = self._analyze_gemini(image_bytes, media_type, prompt)
        elif self.provider == VisionProvider.OPENAI:
            description = self._analyze_openai(image_bytes, media_type, prompt)
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")

        logger.info(f"✓ Vision analysis complete: {len(description)} characters")

        return VisionResult(
            description=description,
            provider=self.provider,
            model=self.model,
            confidence=0.9,
        )

    def _analyze_anthropic(
        self,
        image_bytes: bytes,
        media_type: str,
        prompt: str,
    ) -> str:
        """Analyze image using Anthropic Claude."""
        # Encode image to base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build request
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        body = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        }

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=60.0,
        )

        if response.status_code != 200:
            error_detail = response.text
            logger.error(f"Anthropic API error: {response.status_code} - {error_detail}")
            raise RuntimeError(f"Vision analysis failed: {response.status_code} - {error_detail}")

        result = response.json()
        return result["content"][0]["text"]

    def _analyze_gemini(
        self,
        image_bytes: bytes,
        media_type: str,
        prompt: str,
    ) -> str:
        """Analyze image using Google Gemini."""
        # Encode image to base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build request (Gemini REST API)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        params = {"key": self.api_key}

        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": image_b64,
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ]
        }

        response = requests.post(
            url,
            params=params,
            json=body,
            timeout=60.0,
        )

        if response.status_code != 200:
            error_detail = response.text
            logger.error(f"Gemini API error: {response.status_code} - {error_detail}")
            raise RuntimeError(f"Vision analysis failed: {response.status_code} - {error_detail}")

        result = response.json()
        return result["candidates"][0]["content"]["parts"][0]["text"]

    def _analyze_openai(
        self,
        image_bytes: bytes,
        media_type: str,
        prompt: str,
    ) -> str:
        """Analyze image using OpenAI or OpenAI-compatible endpoint."""
        # Encode image to base64
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        # Build request
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Use custom base URL if provided, otherwise use OpenAI
        base_url = self.base_url or "https://api.openai.com/v1"
        url = f"{base_url}/chat/completions"

        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_b64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "max_tokens": 2048,
        }

        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=60.0,
        )

        if response.status_code != 200:
            error_detail = response.text
            logger.error(f"OpenAI API error: {response.status_code} - {error_detail}")
            raise RuntimeError(f"Vision analysis failed: {response.status_code} - {error_detail}")

        result = response.json()
        return result["choices"][0]["message"]["content"]
