"""
ImageResource - Image-specific resource with CLIP embeddings.

ImageResources are a specialized subclass of Resource for images,
with support for CLIP embeddings and vision LLM descriptions.

Key differences from base Resource:
- **Separate table**: Stored in `image_resources` table, not `resources`
- **Different embeddings**: Uses CLIP embeddings (multimodal) instead of text embeddings
- **Embedding provider override**: Must use CLIP-compatible provider (Jina AI, self-hosted)
- **Vision descriptions**: Optional vision LLM descriptions (tier/sampling gated)
- **Image metadata**: Dimensions, format, and other image-specific fields

Why separate table?
1. Different embedding dimensionality (512/768 vs 1536)
2. Different embedding model (CLIP vs text-embedding-3-small)
3. Multimodal search capabilities (text-to-image, image-to-image)
4. Image-specific indexes and queries
5. Cost tracking (CLIP tokens vs text tokens)

Usage:
- ImageProvider saves to ImageResource table with CLIP embeddings
- Regular text Resources use standard text embeddings
- Cross-modal search: text queries can search ImageResources via CLIP
"""

from typing import Optional

from pydantic import Field

from .resource import Resource


class ImageResource(Resource):
    """
    Image-specific resource with CLIP embeddings.

    Stored in separate `image_resources` table with CLIP embeddings
    instead of text embeddings. This enables:
    - Multimodal search (text-to-image, image-to-image)
    - Proper dimensionality (512/768 for CLIP vs 1536 for text)
    - Cost tracking (CLIP tokens separate from text tokens)

    Embedding Strategy:
    - Default (when JINA_API_KEY set): Jina CLIP API (jina-clip-v2)
    - Future: Self-hosted OpenCLIP models via KEDA-scaled pods
    - Fallback: No embeddings (images searchable by metadata only)

    Vision LLM Strategy (tier/sampling gated):
    - Gold tier: Always get vision descriptions
    - Silver/Free: Probabilistic sampling (IMAGE_VLLM_SAMPLE_RATE)
    - Fallback: Basic metadata only

    Tenant isolation provided via CoreModel.tenant_id field.
    """

    image_width: Optional[int] = Field(
        default=None,
        description="Image width in pixels",
    )
    image_height: Optional[int] = Field(
        default=None,
        description="Image height in pixels",
    )
    image_format: Optional[str] = Field(
        default=None,
        description="Image format (PNG, JPEG, GIF, WebP)",
    )
    vision_description: Optional[str] = Field(
        default=None,
        description="Vision LLM generated description (markdown, only for gold tier or sampled images)",
    )
    vision_provider: Optional[str] = Field(
        default=None,
        description="Vision provider used (anthropic, gemini, openai)",
    )
    vision_model: Optional[str] = Field(
        default=None,
        description="Vision model used for description",
    )
    clip_embedding: Optional[list[float]] = Field(
        default=None,
        description="CLIP embedding vector (512 or 768 dimensions, from Jina AI or self-hosted)",
    )
    clip_dimensions: Optional[int] = Field(
        default=None,
        description="CLIP embedding dimensionality (512 for jina-clip-v2, 768 for jina-clip-v1)",
    )
