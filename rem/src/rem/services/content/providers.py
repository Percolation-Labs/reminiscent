"""Content provider plugins for different file types."""

import json
import multiprocessing
import random
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from rem.utils.constants import (
    AUDIO_CHUNK_TARGET_SECONDS,
    AUDIO_CHUNK_WINDOW_SECONDS,
    MIN_SILENCE_MS,
    SILENCE_THRESHOLD_DB,
    SUBPROCESS_TIMEOUT_SECONDS,
    WAV_HEADER_MIN_BYTES,
    WHISPER_COST_PER_MINUTE,
)
from rem.utils.files import temp_file_from_bytes
from rem.utils.mime_types import get_extension


class ContentProvider(ABC):
    """Base class for content extraction providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/debugging."""
        pass

    @abstractmethod
    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract text content from file bytes.

        Args:
            content: Raw file bytes
            metadata: File metadata (size, type, etc.)

        Returns:
            dict with:
                - text: Extracted text content
                - metadata: Additional metadata from extraction (optional)
        """
        pass


class TextProvider(ContentProvider):
    """
    Text content provider for plain text formats.

    Supports:
    - Markdown (.md, .markdown) - With heading detection
    - JSON (.json) - Pretty-printed text extraction
    - YAML (.yaml, .yml) - Text extraction
    - Plain text (.txt) - Direct UTF-8 extraction
    - Code files (.py, .js, .ts, etc.) - Source code as text

    Simple UTF-8 text extraction with basic metadata.
    Future: Could add frontmatter parsing, JSON schema validation, etc.
    """

    @property
    def name(self) -> str:
        return "text"

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract text content from plain text files.

        Args:
            content: Text file bytes
            metadata: File metadata

        Returns:
            dict with text and optional metadata (line count, headings for markdown, etc.)
        """
        # Decode UTF-8 (with fallback to latin-1)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            logger.debug("UTF-8 decode failed, falling back to latin-1")
            text = content.decode("latin-1")

        # Basic text analysis
        lines = text.split("\n")

        # Detect headings (for markdown files)
        headings = [line for line in lines if line.strip().startswith("#")]

        extraction_metadata = {
            "line_count": len(lines),
            "heading_count": len(headings) if headings else None,
            "char_count": len(text),
            "encoding": "utf-8",
        }

        return {
            "text": text,
            "metadata": extraction_metadata,
        }


class DocProvider(ContentProvider):
    """
    Document content provider using Kreuzberg.

    Supports multiple document formats via Kreuzberg:
    - PDF (.pdf) - Text extraction with OCR fallback
    - Word (.docx) - Native format support
    - PowerPoint (.pptx) - Slide content extraction
    - Excel (.xlsx) - Spreadsheet data extraction
    - Images (.png, .jpg) - OCR text extraction

    Handles:
    - Text extraction with OCR fallback
    - Table detection and extraction
    - Daemon process workaround for multiprocessing restrictions
    """

    @property
    def name(self) -> str:
        return "doc"

    def _is_daemon_process(self) -> bool:
        """Check if running in a daemon process."""
        try:
            return multiprocessing.current_process().daemon
        except Exception:
            return False

    def _parse_in_subprocess(self, file_path: Path) -> dict:
        """Run kreuzberg in a separate subprocess to bypass daemon restrictions."""
        script = """
import json
import sys
from pathlib import Path
from kreuzberg import ExtractionConfig, extract_file_sync

# Parse document with kreuzberg 3.x
config = ExtractionConfig(
    extract_tables=True,
    chunk_content=False,
    extract_keywords=False,
)

result = extract_file_sync(Path(sys.argv[1]), config=config)

# Serialize result to JSON
output = {
    'content': result.content,
    'tables': [t.model_dump() for t in result.tables] if result.tables else [],
    'metadata': result.metadata
}
print(json.dumps(output))
"""

        # Run in subprocess
        result = subprocess.run(
            [sys.executable, "-c", script, str(file_path)],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Subprocess parsing failed: {result.stderr}")

        return json.loads(result.stdout)

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract document content using Kreuzberg.

        Args:
            content: Document file bytes
            metadata: File metadata (should include content_type or extension)

        Returns:
            dict with text and extraction metadata
        """
        # Write bytes to temp file for kreuzberg
        # Detect extension from metadata
        content_type = metadata.get("content_type", "")
        suffix = get_extension(content_type, default=".pdf")

        with temp_file_from_bytes(content, suffix=suffix) as tmp_path:
            # Check if running in daemon process
            if self._is_daemon_process():
                logger.info("Daemon process detected - using subprocess workaround for document parsing")
                try:
                    result_dict = self._parse_in_subprocess(tmp_path)
                    text = result_dict["content"]
                    extraction_metadata = {
                        "table_count": len(result_dict["tables"]),
                        "parser": "kreuzberg_subprocess",
                        "file_extension": tmp_path.suffix,
                    }
                except Exception as e:
                    logger.error(f"Subprocess parsing failed: {e}. Falling back to text-only.")
                    # Fallback to simple text extraction (kreuzberg 3.x API)
                    from kreuzberg import ExtractionConfig, extract_file_sync
                    config = ExtractionConfig(extract_tables=False)
                    result = extract_file_sync(tmp_path, config=config)
                    text = result.content
                    extraction_metadata = {
                        "parser": "kreuzberg_fallback",
                        "file_extension": tmp_path.suffix,
                    }
            else:
                # Normal execution (not in daemon) - kreuzberg 4.x with native ONNX/Rust
                from kreuzberg import ExtractionConfig, extract_file_sync
                config = ExtractionConfig(
                    enable_quality_processing=True,  # Enables table extraction with native ONNX
                    chunk_content=False,  # We handle chunking ourselves
                    extract_tables=False,  # Disable table extraction to avoid PyTorch dependency
                )
                result = extract_file_sync(tmp_path, config=config)
                text = result.content
                extraction_metadata = {
                    "table_count": len(result.tables) if result.tables else 0,
                    "parser": "kreuzberg",
                    "file_extension": tmp_path.suffix,
                }

            return {
                "text": text,
                "metadata": extraction_metadata,
            }


class AudioProvider(ContentProvider):
    """
    Audio content provider using AudioChunker + OpenAI Whisper.

    Handles:
    - Audio chunking by silence near minute boundaries
    - Transcription via OpenAI Whisper API
    - Converts chunks to markdown format
    - Supports WAV, M4A, MP3, FLAC, OGG (via pydub + ffmpeg)

    Process:
    1. Write audio bytes to temp file
    2. Chunk audio by silence (AudioChunker)
    3. Transcribe chunks (AudioTranscriber)
    4. Combine into markdown format with timestamps
    5. Clean up temp files

    Returns markdown-formatted transcription that integrates
    seamlessly with ContentService's markdown → chunk → embed pipeline.
    """

    @property
    def name(self) -> str:
        return "audio"

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract audio content via transcription.

        Args:
            content: Audio file bytes
            metadata: File metadata (size, type, etc.)

        Returns:
            dict with:
                - text: Markdown-formatted transcription with timestamps
                - metadata: Extraction metadata (chunk_count, duration, cost)

        Raises:
            RuntimeError: If transcription fails or pydub not available
            ValueError: If OpenAI API key missing
        """
        # Handle empty or invalid content
        if not content or len(content) < WAV_HEADER_MIN_BYTES:
            logger.warning("Audio content too small to be valid WAV file")
            return {
                "text": "[Invalid or empty audio file]",
                "metadata": {"error": "invalid_content", "size": len(content)},
            }

        # Check for OpenAI API key (use settings)
        from rem.settings import settings
        api_key = settings.llm.openai_api_key
        if not api_key:
            logger.warning("No OpenAI API key found - audio transcription disabled")
            return {
                "text": "[Audio transcription requires LLM__OPENAI_API_KEY to be set]",
                "metadata": {"error": "missing_api_key"},
            }

        # Import audio services (lazy import)
        try:
            from rem.services.audio import AudioChunker, AudioTranscriber
        except ImportError as e:
            logger.error(f"Audio services not available: {e}")
            return {
                "text": "[Audio processing requires: pip install rem[audio]]",
                "metadata": {"error": "missing_dependencies"},
            }

        # Write bytes to temp file
        # Detect extension from metadata or use .wav as fallback
        content_type = metadata.get("content_type", "audio/wav")
        extension = get_extension(content_type, default=".wav")

        chunker = None
        chunks = None

        with temp_file_from_bytes(content, suffix=extension) as tmp_path:
            try:
                logger.info(f"Processing audio file: {tmp_path.name} ({len(content) / 1024 / 1024:.1f} MB)")

                # Step 1: Chunk audio by silence
                chunker = AudioChunker(
                    target_chunk_seconds=AUDIO_CHUNK_TARGET_SECONDS,
                    chunk_window_seconds=AUDIO_CHUNK_WINDOW_SECONDS,
                    silence_threshold_db=SILENCE_THRESHOLD_DB,
                    min_silence_ms=MIN_SILENCE_MS,
                )

                chunks = chunker.chunk_audio(tmp_path)
                logger.info(f"Created {len(chunks)} audio chunks")

                # Step 2: Transcribe chunks
                transcriber = AudioTranscriber(api_key=api_key)
                results = transcriber.transcribe_chunks(chunks)
                logger.info(f"Transcribed {len(results)} chunks")

                # Step 3: Combine into markdown format
                # Format: Each chunk becomes a section with timestamp
                markdown_parts = []
                for result in results:
                    timestamp = f"{result.start_seconds:.1f}s - {result.end_seconds:.1f}s"
                    markdown_parts.append(f"## [{timestamp}]\n\n{result.text}\n")

                markdown_text = "\n".join(markdown_parts)

                # Calculate metadata
                total_duration = sum(r.duration_seconds for r in results)
                estimated_cost = (total_duration / 60) * WHISPER_COST_PER_MINUTE
                successful_chunks = sum(1 for r in results if r.confidence > 0)

                extraction_metadata = {
                    "chunk_count": len(chunks),
                    "transcribed_chunks": successful_chunks,
                    "duration_seconds": total_duration,
                    "estimated_cost": estimated_cost,
                    "parser": "whisper_api",
                }

                logger.info(
                    f"Transcription complete: {successful_chunks}/{len(chunks)} chunks, "
                    f"${estimated_cost:.3f} cost"
                )

                return {
                    "text": markdown_text,
                    "metadata": extraction_metadata,
                }

            except Exception as e:
                logger.error(f"Audio extraction failed: {e}")
                raise RuntimeError(f"Audio transcription failed: {e}") from e

            finally:
                # Clean up audio chunks (temp file cleanup handled by context manager)
                if chunker is not None and chunks is not None:
                    try:
                        chunker.cleanup_chunks(chunks)
                    except Exception as e:
                        logger.warning(f"Chunk cleanup failed: {e}")


class SchemaProvider(ContentProvider):
    """
    Schema content provider for agent/evaluator schemas.

    Detects and processes YAML/JSON files containing:
    - Agent schemas (type: object with json_schema_extra.kind: agent and json_schema_extra.name: <name>)
    - Evaluator schemas (type: object with json_schema_extra.kind: evaluator and json_schema_extra.name: <name>)

    Stores schemas in the schemas table with deterministic IDs for upsert by name.

    Pattern:
    - Checks for schema markers (type: object + kind + name)
    - Generates deterministic ID for upsert (tenant+schema_name)
    - Stores full schema JSON in schemas table
    - Extracts metadata (version, tags, provider_configs, embedding_fields)
    """

    @property
    def name(self) -> str:
        return "schema"

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract and validate agent/evaluator schema.

        Args:
            content: YAML or JSON file bytes
            metadata: File metadata

        Returns:
            dict with:
                - text: Human-readable schema summary
                - metadata: Schema metadata
                - schema_data: Full schema dict for storage
                - is_schema: True if valid schema detected

        Raises:
            ValueError: If schema is invalid
        """
        import json
        import yaml
        from uuid import uuid5, NAMESPACE_DNS

        # Decode content
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        # Try to parse as YAML/JSON
        if metadata.get("content_type") == "application/json":
            schema_data = json.loads(text)  # Raises JSONDecodeError on invalid JSON
        else:
            # Try YAML first (supports both YAML and JSON)
            schema_data = yaml.safe_load(text)  # Raises yaml.YAMLError on invalid YAML

        # Check if it's a schema (type: object + json_schema_extra.kind + json_schema_extra.name)
        if not isinstance(schema_data, dict):
            return {
                "text": text,
                "metadata": {"parser": "schema_fallback"},
                "is_schema": False,
            }

        # Check for schema markers
        is_object_type = schema_data.get("type") == "object"
        json_schema_extra = schema_data.get("json_schema_extra", {})
        kind = json_schema_extra.get("kind", "")
        schema_name = json_schema_extra.get("name", "")

        # Must have type: object, kind (agent or evaluator), and name
        is_agent_schema = is_object_type and kind == "agent" and schema_name
        is_evaluator_schema = is_object_type and kind == "evaluator" and schema_name

        if not (is_agent_schema or is_evaluator_schema):
            return {
                "text": text,
                "metadata": {"parser": "schema_fallback"},
                "is_schema": False,
            }

        # Extract schema metadata
        schema_type = kind  # "agent" or "evaluator"
        version = json_schema_extra.get("version", "1.0.0")
        tags = json_schema_extra.get("tags", [])

        # Use name directly (already in kebab-case format)
        short_name = schema_name

        # Build human-readable summary
        description = schema_data.get("description", "No description provided")
        description_preview = description[:200] + "..." if len(description) > 200 else description

        properties = schema_data.get("properties", {})
        required_fields = schema_data.get("required", [])

        summary_parts = [
            f"# {schema_type.title()} Schema: {short_name}",
            f"**Version:** {version}",
            f"**Name:** {schema_name}",
            f"**Kind:** {kind}",
            "",
            "## Description",
            description_preview,
            "",
            "## Output Fields",
        ]

        for field_name, field_spec in list(properties.items())[:10]:  # Limit to 10 fields
            field_type = field_spec.get("type", "unknown")
            field_desc = field_spec.get("description", "")
            required = " (required)" if field_name in required_fields else ""
            summary_parts.append(f"- **{field_name}**: {field_type}{required} - {field_desc[:50]}")

        if len(properties) > 10:
            summary_parts.append(f"- ... and {len(properties) - 10} more fields")

        text_summary = "\n".join(summary_parts)

        # Extract additional metadata
        extraction_metadata = {
            "parser": "schema",
            "schema_type": schema_type,
            "short_name": short_name,
            "version": version,
            "kind": kind,
            "name": schema_name,
            "tags": tags,
            "field_count": len(properties),
            "required_field_count": len(required_fields),
            "provider_configs": json_schema_extra.get("provider_configs", []),
            "embedding_fields": json_schema_extra.get("embedding_fields", []),
            "category": json_schema_extra.get("category"),
        }

        return {
            "text": text_summary,
            "metadata": extraction_metadata,
            "schema_data": schema_data,
            "is_schema": True,
        }


class ImageProvider(ContentProvider):
    """
    Image content provider with vision LLM analysis and CLIP embeddings.

    Features:
    - Tier-based vision analysis (gold tier always gets analysis)
    - Sampling-based vision analysis for non-gold users
    - Vision LLM description generation (Anthropic, Gemini, OpenAI)
    - Future: CLIP embeddings for semantic image search

    Process:
    1. Check user tier and sampling rate
    2. If eligible, run vision LLM analysis
    3. Extract image metadata (dimensions, format)
    4. Return markdown description or basic metadata
    5. Save to ImageResource table (not Resource)

    Vision analysis is expensive, so it's gated by:
    - User tier (gold = always, silver/free = sampled)
    - Sample rate setting (0.0 = never, 1.0 = always)
    """

    def __init__(self, user_tier: Optional[str] = None):
        """
        Initialize image provider.

        Args:
            user_tier: User tier (free, silver, gold) for vision gating
        """
        self.user_tier = user_tier

    @property
    def name(self) -> str:
        return "image"

    def _should_analyze_with_vision(self, sample_rate: float) -> bool:
        """
        Determine if image should get vision LLM analysis.

        Args:
            sample_rate: Sampling rate from settings (0.0-1.0)

        Returns:
            True if should analyze, False otherwise
        """
        # Import here to avoid circular dependency
        from rem.models.entities import UserTier

        # Gold tier always gets vision analysis
        if self.user_tier == UserTier.GOLD.value:
            logger.info("Gold tier user - vision analysis enabled")
            return True

        # For non-gold users, use sampling
        if sample_rate > 0.0:
            should_analyze = random.random() < sample_rate
            if should_analyze:
                logger.info(f"Vision analysis sampled (rate={sample_rate})")
            return should_analyze

        return False

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract image content with optional vision LLM analysis.

        Args:
            content: Image file bytes
            metadata: File metadata (size, type, etc.)

        Returns:
            dict with:
                - text: Markdown description (if vision enabled) or basic metadata
                - metadata: Extraction metadata (dimensions, format, vision info)
                - image_specific: Additional image metadata for ImageResource

        Raises:
            RuntimeError: If vision analysis fails
        """
        # Import settings here to avoid circular dependency
        from rem.settings import settings

        # Extract basic image metadata using PIL
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(content))
            image_width = img.width
            image_height = img.height
            image_format = img.format or "UNKNOWN"
        except ImportError:
            logger.warning("PIL not available - image metadata extraction disabled")
            image_width = None
            image_height = None
            image_format = None
        except Exception as e:
            logger.warning(f"Failed to extract image metadata: {e}")
            image_width = None
            image_height = None
            image_format = None

        # Check if vision analysis should be performed
        sample_rate = settings.content.image_vllm_sample_rate
        should_analyze = self._should_analyze_with_vision(sample_rate)

        vision_description = None
        vision_provider = None
        vision_model = None

        if should_analyze:
            # Perform vision LLM analysis
            try:
                from rem.utils.vision import ImageAnalyzer, VisionProvider

                # Get provider from settings
                provider_str = settings.content.image_vllm_provider.lower()
                provider_map = {
                    "anthropic": VisionProvider.ANTHROPIC,
                    "gemini": VisionProvider.GEMINI,
                    "openai": VisionProvider.OPENAI,
                }
                provider = provider_map.get(provider_str, VisionProvider.ANTHROPIC)

                # Create analyzer
                analyzer = ImageAnalyzer(
                    provider=provider,
                    model=settings.content.image_vllm_model,
                )

                # Write bytes to temp file for analysis
                content_type = metadata.get("content_type", "image/png")
                extension = get_extension(content_type, default=".png")

                with temp_file_from_bytes(content, suffix=extension) as tmp_path:
                    # Analyze image
                    result = analyzer.analyze_image(tmp_path)
                    vision_description = result.description
                    vision_provider = result.provider.value
                    vision_model = result.model

                    logger.info(f"Vision analysis complete: {len(vision_description)} chars")

            except ImportError as e:
                logger.warning(f"Vision analysis not available: {e}")
            except Exception as e:
                logger.error(f"Vision analysis failed: {e}")

        # Build text content
        if vision_description:
            # Use vision description as primary content
            text = f"# Image Analysis\n\n{vision_description}"
            if image_width and image_height:
                text += f"\n\n**Image Details:** {image_width}x{image_height} {image_format}"
        else:
            # Fallback to basic metadata
            if image_width and image_height:
                text = f"**Image:** {image_width}x{image_height} {image_format}"
            else:
                text = "**Image:** Metadata extraction unavailable"

        # Generate CLIP embedding (if Jina API key available)
        clip_embedding = None
        clip_dimensions = None
        clip_tokens = None

        try:
            from rem.utils.clip_embeddings import JinaCLIPEmbedder

            # Only attempt CLIP embeddings if using Jina provider
            if settings.content.clip_provider != "jina":
                logger.debug(
                    f"CLIP provider set to '{settings.content.clip_provider}' - "
                    "skipping Jina embeddings (self-hosted not yet implemented)"
                )
            else:
                embedder = JinaCLIPEmbedder(
                    api_key=settings.content.jina_api_key,
                    model=settings.content.clip_model,
                )

                if embedder.is_available():
                    # Write bytes to temp file for CLIP embedding
                    content_type = metadata.get("content_type", "image/png")
                    extension = get_extension(content_type, default=".png")

                    with temp_file_from_bytes(content, suffix=extension) as tmp_path:
                        # Generate CLIP embedding
                        result = embedder.embed_image(tmp_path)
                        if result:
                            clip_embedding = result.embedding  # type: ignore[attr-defined]
                            clip_dimensions = result.dimensions  # type: ignore[attr-defined]
                            clip_tokens = result.tokens_used  # type: ignore[attr-defined]
                            logger.info(
                                f"CLIP embedding generated: {clip_dimensions} dims, {clip_tokens} tokens"
                            )
                else:
                    logger.debug(
                        "CLIP embeddings disabled - set CONTENT__JINA_API_KEY to enable. "
                        "Get free API key at https://jina.ai/embeddings/"
                    )

        except ImportError:
            logger.debug("CLIP embedding module not available")
        except Exception as e:
            logger.warning(f"CLIP embedding generation failed (non-fatal): {e}")

        # Build extraction metadata
        extraction_metadata = {
            "parser": "image_provider",
            "vision_enabled": vision_description is not None,
            "vision_provider": vision_provider,
            "vision_model": vision_model,
            "image_width": image_width,
            "image_height": image_height,
            "image_format": image_format,
            "clip_enabled": clip_embedding is not None,
            "clip_dimensions": clip_dimensions,
            "clip_tokens": clip_tokens,
        }

        # Add image-specific metadata for ImageResource
        image_specific = {
            "image_width": image_width,
            "image_height": image_height,
            "image_format": image_format,
            "vision_description": vision_description,
            "vision_provider": vision_provider,
            "vision_model": vision_model,
            "clip_embedding": clip_embedding,
            "clip_dimensions": clip_dimensions,
        }

        return {
            "text": text,
            "metadata": extraction_metadata,
            "image_specific": image_specific,
        }
