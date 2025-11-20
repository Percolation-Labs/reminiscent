"""
ContentService for file processing.

Pipeline:
1. Extract content via provider plugins
2. Convert to markdown
3. Chunk markdown
4. Save File + Resources to database via repositories
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from rem.models.entities import File, Resource
from rem.services.repositories import FileRepository, ResourceRepository
from rem.settings import settings
from rem.utils.chunking import chunk_text
from rem.utils.markdown import to_markdown

from .providers import AudioProvider, ContentProvider, DocProvider, TextProvider


class ContentService:
    """
    Service for processing files: extract → markdown → chunk → save.

    Supports:
    - S3 URIs (s3://bucket/key)
    - Local file paths
    - Pluggable content providers
    """

    def __init__(
        self, file_repo: FileRepository | None = None, resource_repo: ResourceRepository | None = None
    ):
        self.s3_client = self._create_s3_client()
        self.providers: dict[str, ContentProvider] = {}
        self.file_repo = file_repo
        self.resource_repo = resource_repo

        # Register default providers from settings
        self._register_default_providers()

    def _register_default_providers(self):
        """Register default content providers from settings."""
        # Text provider for plain text, code, data files
        text_provider = TextProvider()
        for ext in settings.content.supported_text_types:
            self.providers[ext.lower()] = text_provider

        # Doc provider for PDFs, Office docs, images (via Kreuzberg)
        doc_provider = DocProvider()
        for ext in settings.content.supported_doc_types:
            self.providers[ext.lower()] = doc_provider

        # Audio provider for audio files (via Whisper API)
        audio_provider = AudioProvider()
        for ext in settings.content.supported_audio_types:
            self.providers[ext.lower()] = audio_provider

        logger.debug(
            f"Registered {len(self.providers)} file extensions across "
            f"{len(settings.content.supported_text_types)} text, "
            f"{len(settings.content.supported_doc_types)} doc, "
            f"{len(settings.content.supported_audio_types)} audio types"
        )

    def _create_s3_client(self):
        """Create S3 client with IRSA or configured credentials."""
        s3_config: dict[str, Any] = {
            "region_name": settings.s3.region,
        }

        # Custom endpoint for MinIO/LocalStack
        if settings.s3.endpoint_url:
            s3_config["endpoint_url"] = settings.s3.endpoint_url

        # Access keys (not needed with IRSA in EKS)
        if settings.s3.access_key_id and settings.s3.secret_access_key:
            s3_config["aws_access_key_id"] = settings.s3.access_key_id
            s3_config["aws_secret_access_key"] = settings.s3.secret_access_key

        # SSL configuration
        s3_config["use_ssl"] = settings.s3.use_ssl

        return boto3.client("s3", **s3_config)

    def process_uri(self, uri: str) -> dict[str, Any]:
        """
        Process a file URI and extract content.

        Args:
            uri: File URI (s3://bucket/key or local path)

        Returns:
            dict with:
                - uri: Original URI
                - content: Extracted text content
                - metadata: File metadata (size, type, etc.)
                - provider: Provider used for extraction

        Raises:
            ValueError: If URI format is invalid
            FileNotFoundError: If file doesn't exist
            RuntimeError: If no provider available for file type
        """
        logger.info(f"Processing URI: {uri}")

        # Determine if S3 or local file
        if uri.startswith("s3://"):
            return self._process_s3_uri(uri)
        else:
            return self._process_local_file(uri)

    def _process_s3_uri(self, uri: str) -> dict[str, Any]:
        """Process S3 URI."""
        parsed = urlparse(uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")

        if not bucket or not key:
            raise ValueError(f"Invalid S3 URI: {uri}")

        logger.debug(f"Downloading s3://{bucket}/{key}")

        try:
            # Download file from S3
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content_bytes = response["Body"].read()

            # Get metadata
            metadata = {
                "size": response["ContentLength"],
                "content_type": response.get("ContentType", ""),
                "last_modified": response["LastModified"].isoformat(),
                "etag": response.get("ETag", "").strip('"'),
            }

            # Extract content using provider
            file_path = Path(key)
            provider = self._get_provider(file_path.suffix)

            extracted_content = provider.extract(content_bytes, metadata)

            return {
                "uri": uri,
                "content": extracted_content["text"],
                "metadata": {**metadata, **extracted_content.get("metadata", {})},
                "provider": provider.name,
            }

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "NoSuchKey":
                raise FileNotFoundError(f"S3 object not found: {uri}") from e
            elif error_code == "NoSuchBucket":
                raise FileNotFoundError(f"S3 bucket not found: {bucket}") from e
            else:
                raise RuntimeError(f"S3 error: {e}") from e

    def _process_local_file(self, path: str) -> dict[str, Any]:
        """Process local file path."""
        file_path = Path(path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not file_path.is_file():
            raise ValueError(f"Not a file: {path}")

        logger.debug(f"Reading local file: {file_path}")

        # Read file content
        content_bytes = file_path.read_bytes()

        # Get metadata
        stat = file_path.stat()
        metadata = {
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }

        # Extract content using provider
        provider = self._get_provider(file_path.suffix)
        extracted_content = provider.extract(content_bytes, metadata)

        return {
            "uri": str(file_path.absolute()),
            "content": extracted_content["text"],
            "metadata": {**metadata, **extracted_content.get("metadata", {})},
            "provider": provider.name,
        }

    def _get_provider(self, suffix: str) -> ContentProvider:
        """Get content provider for file extension."""
        suffix_lower = suffix.lower()

        if suffix_lower not in self.providers:
            raise RuntimeError(
                f"No provider available for file type: {suffix}. "
                f"Supported: {', '.join(self.providers.keys())}"
            )

        return self.providers[suffix_lower]

    def register_provider(self, extensions: list[str], provider: ContentProvider):
        """
        Register a custom content provider.

        Args:
            extensions: List of file extensions (e.g., ['.pdf', '.docx'])
            provider: ContentProvider instance
        """
        for ext in extensions:
            ext_lower = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            self.providers[ext_lower] = provider
            logger.debug(f"Registered provider '{provider.name}' for {ext_lower}")

    async def process_and_save(self, uri: str, user_id: str | None = None) -> dict[str, Any]:
        """
        Process file end-to-end: extract → markdown → chunk → save.

        Args:
            uri: File URI (s3://bucket/key or local path)
            user_id: Optional user ID for multi-tenancy

        Returns:
            dict with file metadata and chunk count
        """
        logger.info(f"Processing and saving: {uri}")

        # Extract content
        result = self.process_uri(uri)
        filename = Path(uri).name

        # Convert to markdown
        markdown = to_markdown(result["content"], filename)

        # Chunk markdown
        chunks = chunk_text(markdown)
        logger.info(f"Created {len(chunks)} chunks from {filename}")

        # Save File entity
        file = File(
            name=filename,
            uri=uri,
            content=result["content"],
            size_bytes=result["metadata"].get("size"),
            mime_type=result["metadata"].get("content_type"),
            processing_status="completed",
            tenant_id=user_id or "default",  # Required field
            user_id=user_id,
        )

        if self.file_repo:
            await self.file_repo.upsert(file)
            logger.info(f"Saved File: {filename}")

        # Create Resource entities for each chunk
        resources = [
            Resource(
                name=f"{filename}#chunk-{i}",
                uri=f"{uri}#chunk-{i}",
                ordinal=i,
                content=chunk,
                category="document",
                tenant_id=user_id or "default",  # Required field
                user_id=user_id,
            )
            for i, chunk in enumerate(chunks)
        ]

        if self.resource_repo:
            await self.resource_repo.batch_upsert(resources)
            logger.info(f"Saved {len(resources)} Resource chunks")

        return {
            "file": file.model_dump(),
            "chunk_count": len(chunks),
            "status": "completed",
        }
