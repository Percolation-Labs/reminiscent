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
from rem.services.postgres import Repository
from rem.settings import settings
from rem.utils.chunking import chunk_text
from rem.utils.markdown import to_markdown

from .providers import AudioProvider, ContentProvider, DocProvider, SchemaProvider, TextProvider


class ContentService:
    """
    Service for processing files: extract → markdown → chunk → save.

    Supports:
    - S3 URIs (s3://bucket/key)
    - Local file paths
    - Pluggable content providers
    """

    def __init__(
        self, file_repo: Repository | None = None, resource_repo: Repository | None = None
    ):
        self.s3_client = self._create_s3_client()
        self.providers: dict[str, ContentProvider] = {}
        self.file_repo = file_repo
        self.resource_repo = resource_repo

        # Register default providers from settings
        self._register_default_providers()

    def _register_default_providers(self):
        """Register default content providers from settings."""
        # Schema provider for agent/evaluator schemas (YAML/JSON)
        # Register first so it takes priority for .yaml/.json files
        schema_provider = SchemaProvider()
        self.providers[".yaml"] = schema_provider
        self.providers[".yml"] = schema_provider
        self.providers[".json"] = schema_provider

        # Text provider for plain text, code, data files
        text_provider = TextProvider()
        for ext in settings.content.supported_text_types:
            # Don't override schema provider for yaml/json
            if ext.lower() not in [".yaml", ".yml", ".json"]:
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
            f"schema (yaml/json), "
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
        """
        Process local file path.

        **PATH HANDLING FIX**: This method correctly handles both file:// URIs
        and plain paths. Previously, file:// URIs from tools.py were NOT stripped,
        causing FileNotFoundError because Path() treated "file:///Users/..." as a
        literal filename instead of a URI.

        The fix ensures consistent path handling:
        - MCP tool creates: file:///Users/.../file.pdf
        - This method strips: file:// → /Users/.../file.pdf
        - Path() works correctly with absolute path

        Related files:
        - tools.py line 636: Creates file:// URIs
        - FileSystemService line 58: Also strips file:// URIs
        """
        # Handle file:// URI scheme
        if path.startswith("file://"):
            path = path.replace("file://", "")

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

    async def ingest_file(
        self,
        file_uri: str,
        tenant_id: str,
        user_id: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        is_local_server: bool = False,
    ) -> dict[str, Any]:
        """
        Complete file ingestion pipeline: read → store → parse → chunk → embed.

        **CENTRALIZED INGESTION**: This is the single entry point for all file ingestion
        in REM. It handles:

        1. **File Reading**: From local/S3/HTTP sources via FileSystemService
        2. **Storage**: Writes to tenant-scoped internal storage (~/.rem/fs/ or S3)
        3. **Parsing**: Extracts content, metadata, tables, images (parsing state)
        4. **Chunking**: Splits content into semantic chunks for embedding
        5. **Database**: Creates File entity + Resource chunks with embeddings

        **PARSING STATE - The Innovation**:
        Files (PDF, WAV, DOCX, etc.) are converted to rich parsing state:
        - **Content**: Markdown-formatted text (preserves structure)
        - **Metadata**: File info, extraction details, timestamps
        - **Tables**: Structured data extracted from documents (CSV format)
        - **Images**: Extracted images saved to storage (for multimodal RAG)
        - **Provider Info**: Which parser was used, version, settings

        This parsing state enables agents to deeply understand documents:
        - Query tables directly (structured data)
        - Reference images (multimodal context)
        - Understand document structure (markdown hierarchy)
        - Track provenance (metadata lineage)

        **CLIENT ABSTRACTION**: Clients (MCP tools, CLI, workers) don't worry about:
        - Where files are stored (S3 vs local) - automatically selected
        - How files are parsed (PDF vs DOCX) - provider auto-selected
        - How chunks are created - semantic chunking with tiktoken
        - How embeddings work - async worker with batching

        Clients just call `ingest_file()` and get searchable resources.

        **PERMISSION CHECK**: Remote MCP servers cannot read local files (security).
        Only local/stdio MCP servers can access local filesystem paths.

        Args:
            file_uri: Source file location (local path, s3://, or https://)
            tenant_id: Tenant identifier for data isolation
            user_id: Optional user ownership
            category: Optional category tag (document, code, audio, etc.)
            tags: Optional list of tags
            is_local_server: True if running as local/stdio MCP server

        Returns:
            dict with:
                - file_id: UUID of created File entity
                - file_name: Original filename
                - storage_uri: Internal storage location
                - internal_key: S3 key or local path
                - size_bytes: File size
                - content_type: MIME type
                - processing_status: "completed" or "failed"
                - resources_created: Number of Resource chunks created
                - parsing_metadata: Rich parsing state (content, tables, images)

        Raises:
            PermissionError: If remote server tries to read local file
            FileNotFoundError: If source file doesn't exist
            RuntimeError: If storage or processing fails

        Example:
            >>> service = ContentService()
            >>> result = await service.ingest_file(
            ...     file_uri="s3://bucket/contract.pdf",
            ...     tenant_id="acme-corp",
            ...     category="legal"
            ... )
            >>> print(f"Created {result['resources_created']} searchable chunks")
        """
        from pathlib import Path
        from uuid import uuid4
        import mimetypes

        from ...models.entities import File
        from ...services.fs import FileSystemService
        from ...services.postgres import PostgresService

        # Step 1: Read file from source using FileSystemService
        fs_service = FileSystemService()
        file_content, file_name, source_type = await fs_service.read_uri(
            file_uri, is_local_server=is_local_server
        )
        file_size = len(file_content)
        logger.info(f"Read {file_size} bytes from {file_uri} (source: {source_type})")

        # Step 2: Write to internal storage (tenant-scoped)
        file_id = str(uuid4())
        storage_uri, internal_key, content_type, _ = await fs_service.write_to_internal_storage(
            content=file_content,
            tenant_id=tenant_id,
            file_name=file_name,
            file_id=file_id,
        )
        logger.info(f"Stored to internal storage: {storage_uri}")

        # Step 3: Create File entity
        file_entity = File(
            id=file_id,
            tenant_id=tenant_id,
            user_id=user_id,
            name=file_name,
            uri=storage_uri,
            s3_key=internal_key,
            s3_bucket=(
                storage_uri.split("/")[2] if storage_uri.startswith("s3://") else "local"
            ),
            content_type=content_type,
            size_bytes=file_size,
            metadata={
                "source_uri": file_uri,
                "source_type": source_type,
                "category": category,
                "storage_uri": storage_uri,
            },
            tags=tags or [],
        )

        # Step 4: Save File entity to database
        postgres_service = PostgresService()
        await postgres_service.connect()
        try:
            await postgres_service.batch_upsert(
                records=[file_entity],
                model=File,
                table_name="files",
                entity_key_field="name",
                generate_embeddings=False,
            )
        finally:
            await postgres_service.disconnect()

        # Step 5: Process file to create Resource chunks
        try:
            processing_result = await self.process_and_save(
                uri=storage_uri,
                user_id=user_id,
            )
            processing_status = processing_result.get("status", "completed")
            resources_created = processing_result.get("chunk_count", 0)
            parsing_metadata = {
                "content_extracted": bool(processing_result.get("content")),
                "markdown_generated": bool(processing_result.get("markdown")),
                "chunks_created": resources_created,
            }
        except Exception as e:
            logger.error(f"File processing failed: {e}", exc_info=True)
            processing_status = "failed"
            resources_created = 0
            parsing_metadata = {"error": str(e)}

        logger.info(
            f"File ingestion complete: {file_name} "
            f"(tenant: {tenant_id}, status: {processing_status}, "
            f"resources: {resources_created})"
        )

        return {
            "file_id": file_id,
            "file_name": file_name,
            "storage_uri": storage_uri,
            "internal_key": internal_key,
            "size_bytes": file_size,
            "content_type": content_type,
            "source_uri": file_uri,
            "source_type": source_type,
            "processing_status": processing_status,
            "resources_created": resources_created,
            "parsing_metadata": parsing_metadata,
            "message": f"File ingested and {processing_status}. Created {resources_created} resources.",
        }

    async def process_and_save(self, uri: str, user_id: str | None = None) -> dict[str, Any]:
        """
        Process file end-to-end: extract → markdown → chunk → save.

        **INTERNAL METHOD**: This is called by ingest_file() after storage.
        Clients should use ingest_file() instead for the full pipeline.

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
