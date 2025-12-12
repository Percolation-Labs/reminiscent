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

            # Build result with standard fields
            result = {
                "uri": uri,
                "content": extracted_content["text"],
                "metadata": {**metadata, **extracted_content.get("metadata", {})},
                "provider": provider.name,
            }

            # Preserve schema-specific fields if present (from SchemaProvider)
            if "is_schema" in extracted_content:
                result["is_schema"] = extracted_content["is_schema"]
            if "schema_data" in extracted_content:
                result["schema_data"] = extracted_content["schema_data"]

            return result

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

        # Build result with standard fields
        result = {
            "uri": str(file_path.absolute()),
            "content": extracted_content["text"],
            "metadata": {**metadata, **extracted_content.get("metadata", {})},
            "provider": provider.name,
        }

        # Preserve schema-specific fields if present (from SchemaProvider)
        if "is_schema" in extracted_content:
            result["is_schema"] = extracted_content["is_schema"]
        if "schema_data" in extracted_content:
            result["schema_data"] = extracted_content["schema_data"]

        return result

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
        user_id: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        is_local_server: bool = False,
        resource_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Complete file ingestion pipeline: read → store → parse → chunk → embed.

        **IMPORTANT: Data is PUBLIC by default (user_id=None).**
        This is correct for shared knowledge bases (ontologies, procedures, reference data).
        Private user-scoped data is rarely needed - only set user_id for truly personal content.

        **CENTRALIZED INGESTION**: This is the single entry point for all file ingestion
        in REM. It handles:

        1. **File Reading**: From local/S3/HTTP sources via FileSystemService
        2. **Storage**: Writes to user-scoped internal storage (~/.rem/fs/ or S3)
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
            user_id: User identifier for PRIVATE data only. Default None = PUBLIC/shared.
                Leave as None for shared knowledge bases, ontologies, reference data.
                Only set for truly private user-specific content.
            category: Optional category tag (document, code, audio, etc.)
            tags: Optional list of tags
            is_local_server: True if running as local/stdio MCP server
            resource_type: Optional resource type (case-insensitive). Supports:
                - "resource", "resources", "Resource" → Resource (default)
                - "domain-resource", "domain_resource", "DomainResource" → DomainResource

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
                - content: Parsed file content (markdown format) if status is "completed"

        Raises:
            PermissionError: If remote server tries to read local file
            FileNotFoundError: If source file doesn't exist
            RuntimeError: If storage or processing fails

        Example:
            >>> service = ContentService()
            >>> # PUBLIC data (default) - visible to all users
            >>> result = await service.ingest_file(
            ...     file_uri="s3://bucket/procedure.pdf",
            ...     category="medical"
            ... )
            >>> print(f"Created {result['resources_created']} searchable chunks")
            >>>
            >>> # PRIVATE data (rare) - only for user-specific content
            >>> result = await service.ingest_file(
            ...     file_uri="s3://bucket/personal-notes.pdf",
            ...     user_id="user-123",  # Only this user can access
            ...     category="personal"
            ... )
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

        # Step 1.5: Early schema detection for YAML/JSON files
        # Skip File entity creation for schemas (agents/evaluators)
        file_suffix = Path(file_name).suffix.lower()
        if file_suffix in ['.yaml', '.yml', '.json']:
            import yaml
            import json
            try:
                content_text = file_content.decode('utf-8') if isinstance(file_content, bytes) else file_content
                data = yaml.safe_load(content_text) if file_suffix in ['.yaml', '.yml'] else json.loads(content_text)
                if isinstance(data, dict):
                    json_schema_extra = data.get('json_schema_extra', {})
                    kind = json_schema_extra.get('kind', '')
                    if kind in ['agent', 'evaluator']:
                        # Route directly to schema processing, skip File entity
                        logger.info(f"Detected {kind} schema: {file_name}, routing to _process_schema")
                        result = self.process_uri(file_uri)
                        return await self._process_schema(result, file_uri, user_id)
            except Exception as e:
                logger.debug(f"Early schema detection failed for {file_name}: {e}")
                # Fall through to standard file processing

        # Step 2: Write to internal storage (public or user-scoped)
        file_id = str(uuid4())
        storage_uri, internal_key, content_type, _ = await fs_service.write_to_internal_storage(
            content=file_content,
            tenant_id=user_id or "public",  # Storage path: public/ or user_id/
            file_name=file_name,
            file_id=file_id,
        )
        logger.info(f"Stored to internal storage: {storage_uri}")

        # Step 3: Create File entity
        file_entity = File(
            id=file_id,
            tenant_id=user_id,  # None = public/shared
            user_id=user_id,
            name=file_name,
            uri=storage_uri,
            mime_type=content_type,
            size_bytes=file_size,
            metadata={
                "source_uri": file_uri,
                "source_type": source_type,
                "category": category,
                "storage_uri": storage_uri,
                "s3_key": internal_key,
                "s3_bucket": (
                    storage_uri.split("/")[2] if storage_uri.startswith("s3://") else "local"
                ),
            },
            tags=tags or [],
        )

        # Step 4: Save File entity to database
        from rem.services.postgres import get_postgres_service
        from rem.services.postgres.repository import Repository

        postgres_service = get_postgres_service()
        if not postgres_service:
            raise RuntimeError("PostgreSQL is disabled. Cannot save File entity to database.")

        await postgres_service.connect()
        try:
            repo = Repository(File, "files", db=postgres_service)
            await repo.upsert(file_entity)
        finally:
            await postgres_service.disconnect()

        # Step 5: Process file to create Resource chunks
        try:
            processing_result = await self.process_and_save(
                uri=storage_uri,
                user_id=user_id,
                resource_type=resource_type,
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
            f"(user: {user_id}, status: {processing_status}, "
            f"resources: {resources_created})"
        )

        # Extract content if available
        content = None
        if processing_status == "completed" and processing_result:
            content = processing_result.get("content")

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
            "content": content,  # Include parsed content when available
            "message": f"File ingested and {processing_status}. Created {resources_created} resources.",
        }

    async def process_and_save(
        self,
        uri: str,
        user_id: str | None = None,
        resource_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Process file end-to-end: extract → markdown → chunk → save.

        **INTERNAL METHOD**: This is called by ingest_file() after storage.
        Clients should use ingest_file() instead for the full pipeline.

        **KIND-BASED ROUTING**: For YAML/JSON files, checks for 'kind' field and routes to:
        - kind=agent or kind=evaluator → Save to schemas table (not resources)
        - kind=engram → Process via EngramProcessor (creates resources + moments)
        - No kind → Standard resource processing (default)

        Args:
            uri: File URI (s3://bucket/key or local path)
            user_id: Optional user ID for multi-tenancy
            resource_type: Optional resource type (case-insensitive). Defaults to "Resource".
                Supports: resource, domain-resource, domain_resource, DomainResource, etc.

        Returns:
            dict with file metadata and chunk count
        """
        logger.info(f"Processing and saving: {uri}")

        # Extract content
        result = self.process_uri(uri)
        filename = Path(uri).name

        # Check for custom kind-based processing (YAML/JSON only)
        file_suffix = Path(uri).suffix.lower()
        if file_suffix in ['.yaml', '.yml', '.json']:
            # Check if schema provider detected a valid schema
            # is_schema flag is at top level of result (preserved from SchemaProvider)
            if result.get('is_schema'):
                logger.info(f"🔧 Custom provider flow initiated: kind={result.get('metadata', {}).get('kind')} for {filename}")
                return await self._process_schema(result, uri, user_id)

            # Check for engram kind in raw data
            import yaml
            import json
            try:
                # Parse the content to check for kind
                content_text = result.get('content', '')
                if file_suffix == '.json':
                    data = json.loads(content_text)
                else:
                    data = yaml.safe_load(content_text)

                if isinstance(data, dict) and data.get('kind') == 'engram':
                    logger.info(f"🔧 Custom provider flow initiated: kind=engram for {filename}")
                    return await self._process_engram(data, uri, user_id)
            except Exception as e:
                logger.debug(f"Could not parse {filename} for kind check: {e}")
                # Fall through to standard processing

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
            tenant_id=user_id,  # None = public/shared
            user_id=user_id,
        )

        if self.file_repo:
            await self.file_repo.upsert(file)
            logger.info(f"Saved File: {filename}")

        # Resolve resource model class from type parameter (case-insensitive)
        from typing import cast, Type
        from pydantic import BaseModel
        from rem.utils.model_helpers import model_from_arbitrary_casing, get_table_name

        resource_model: Type[BaseModel] = Resource  # Default
        if resource_type:
            try:
                resource_model = model_from_arbitrary_casing(resource_type)
                logger.info(f"Using resource model: {resource_model.__name__}")
            except ValueError as e:
                logger.warning(f"Invalid resource_type '{resource_type}', using default Resource: {e}")
                resource_model = Resource

        # Get table name for the resolved model
        table_name = get_table_name(resource_model)

        # Create resource entities for each chunk
        resources: list[BaseModel] = [
            resource_model(
                name=f"{filename}#chunk-{i}",
                uri=f"{uri}#chunk-{i}",
                ordinal=i,
                content=chunk,
                category="document",
                tenant_id=user_id,  # None = public/shared
                user_id=user_id,
            )
            for i, chunk in enumerate(chunks)
        ]

        # Save resources to the appropriate table
        if resources:
            from rem.services.postgres import get_postgres_service

            postgres = get_postgres_service()
            if postgres:
                await postgres.connect()
                try:
                    await postgres.batch_upsert(
                        records=cast(list[BaseModel | dict], resources),
                        model=resource_model,
                        table_name=table_name,
                        entity_key_field="name",
                        embeddable_fields=["content"],
                        generate_embeddings=True,
                    )
                    logger.info(f"Saved {len(resources)} {resource_model.__name__} chunks to {table_name}")
                    logger.info(f"Queued {len(resources)} embedding generation tasks for content field")
                finally:
                    await postgres.disconnect()
            elif self.resource_repo:
                # Fallback to injected repo (only works for default Resource)
                await self.resource_repo.upsert(
                    resources,
                    embeddable_fields=["content"],
                    generate_embeddings=True,
                )
                logger.info(f"Saved {len(resources)} Resource chunks")
                logger.info(f"Queued {len(resources)} embedding generation tasks for content field")

        return {
            "file": file.model_dump(),
            "chunk_count": len(chunks),
            "content": result["content"],
            "markdown": markdown,
            "status": "completed",
        }

    async def _process_schema(
        self, result: dict[str, Any], uri: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """
        Process agent/evaluator schema and save to schemas table.

        Args:
            result: Extraction result from SchemaProvider with schema_data
            uri: File URI
            user_id: Optional user ID for multi-tenancy

        Returns:
            dict with schema save result
        """
        from rem.models.entities import Schema
        from rem.services.postgres import PostgresService

        metadata = result.get("metadata", {})
        schema_data = result.get("schema_data", {})

        kind = metadata.get("kind")
        name = metadata.get("name")
        version = metadata.get("version", "1.0.0")

        logger.info(f"Saving schema to schemas table: kind={kind}, name={name}, version={version}")

        # Create Schema entity
        # IMPORTANT: category field distinguishes agents from evaluators
        # - kind=agent → category="agent" (AI agents with tools/resources)
        # - kind=evaluator → category="evaluator" (LLM-as-a-Judge evaluators)
        # User-scoped schemas: if user_id provided, scope to user's tenant
        # System schemas: if no user_id, use "system" tenant for shared access
        schema_entity = Schema(
            tenant_id=user_id or "system",
            user_id=user_id,
            name=name,
            spec=schema_data,
            category=kind,  # Maps kind → category for database filtering
            provider_configs=metadata.get("provider_configs", []),
            embedding_fields=metadata.get("embedding_fields", []),
            metadata={
                "uri": uri,
                "version": version,
                "tags": metadata.get("tags", []),
            },
        )

        # Save to schemas table
        from rem.services.postgres import get_postgres_service
        postgres = get_postgres_service()
        if not postgres:
            raise RuntimeError("PostgreSQL is disabled. Cannot save Schema entity to database.")

        await postgres.connect()
        try:
            from rem.models.entities import Schema as SchemaModel
            await postgres.batch_upsert(
                records=[schema_entity],
                model=SchemaModel,
                table_name="schemas",
                entity_key_field="name",
                generate_embeddings=False,
            )
            logger.info(f"✅ Schema saved: {name} (kind={kind})")
        finally:
            await postgres.disconnect()

        return {
            "schema_name": name,
            "kind": kind,
            "version": version,
            "status": "completed",
            "message": f"Schema '{name}' saved to schemas table",
        }

    async def _process_engram(
        self, data: dict[str, Any], uri: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """
        Process engram and save to resources + moments tables.

        Args:
            data: Parsed engram data with kind=engram
            uri: File URI
            user_id: Optional user ID for multi-tenancy

        Returns:
            dict with engram processing result
        """
        from rem.workers.engram_processor import EngramProcessor
        from rem.services.postgres import PostgresService

        logger.info(f"Processing engram: {data.get('name')}")

        from rem.services.postgres import get_postgres_service
        postgres = get_postgres_service()
        if not postgres:
            raise RuntimeError("PostgreSQL is disabled. Cannot process engram.")

        await postgres.connect()
        try:
            processor = EngramProcessor(postgres)
            result = await processor.process_engram(
                data=data,
                tenant_id=user_id,  # None = public/shared
                user_id=user_id,
            )
            logger.info(f"✅ Engram processed: {result.get('resource_id')} with {len(result.get('moment_ids', []))} moments")
            return result
        finally:
            await postgres.disconnect()
