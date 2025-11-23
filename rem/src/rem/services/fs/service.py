"""
Filesystem Abstraction Layer for REM.

Provides a unified interface for reading files from different sources:
- Local filesystem paths
- S3 URIs (s3://bucket/key)
- HTTP/HTTPS URLs

**ARCHITECTURE NOTE - Service Usage**:

This service centralizes ALL file I/O operations for REM:

1. **read_uri()**: Reads files from any supported source (local/S3/HTTP)
   - Used by: Local file providers, S3 providers
   - Should be used by: MCP parse_and_ingest_file tool (currently duplicated)

2. **write_to_internal_storage()**: Writes to REM's internal storage
   - Tenant-scoped paths: {tenant_id}/files/{file_id}/{filename}
   - Auto-selects backend: S3 (production) or ~/.rem/fs/ (local dev)
   - Used by: SQS file processor worker
   - Should be used by: MCP parse_and_ingest_file tool (currently duplicated)

**CODE DUPLICATION WARNING**:
The MCP tool 'parse_and_ingest_file' (api/mcp_router/tools.py) duplicates
this service's logic (lines 561-636). This violates DRY and creates maintenance
burden. TODO: Refactor MCP tool to use this service.

**PATH CENTRALIZATION**:
All file paths use the SAME format:
- S3: s3://{bucket}/{tenant_id}/files/{file_id}/{filename}
- Local: file://{home}/.rem/fs/{tenant_id}/files/{file_id}/{filename}

This ensures consistent path handling across CLI, MCP, and workers.
"""
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
import aiohttp
import aioboto3
from botocore.exceptions import ClientError

from ...settings import settings


class FileSystemService:
    """
    A service for reading files from various sources.
    """

    async def read_uri(self, file_uri: str, is_local_server: bool = False) -> tuple[bytes, str, str]:
        """
        Read content from a given URI.

        Args:
            file_uri: The URI of the file to read.
            is_local_server: Whether the server is running locally.

        Returns:
            A tuple containing the file content, the filename, and the source type.
        """
        parsed = urlparse(file_uri)
        scheme = parsed.scheme

        if scheme in ("http", "https"):
            source_type = "url"
            file_name = Path(parsed.path).name or "downloaded_file"
            content = await self._read_from_url(file_uri)
        elif scheme == "s3":
            source_type = "s3"
            s3_bucket = parsed.netloc
            s3_key = parsed.path.lstrip("/")
            file_name = Path(s3_key).name
            content = await self._read_from_s3(s3_bucket, s3_key)
        elif scheme == "" or scheme == "file":
            if not is_local_server:
                raise PermissionError(
                    "Local file paths are only allowed for local MCP servers."
                )
            source_type = "local"
            file_path = Path(file_uri.replace("file://", ""))
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_uri}")
            file_name = file_path.name
            content = await self._read_from_local(file_path)
        else:
            raise ValueError(f"Unsupported URI scheme: {scheme}")

        return content, file_name, source_type

    async def _read_from_url(self, url: str) -> bytes:
        """Read content from a URL."""
        logger.debug(f"Reading from URL: {url}")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.read()

    async def _read_from_s3(self, bucket: str, key: str) -> bytes:
        """Read content from S3."""
        logger.debug(f"Reading from S3: s3://{bucket}/{key}")
        session = aioboto3.Session()
        async with session.client(
            "s3",
            endpoint_url=settings.s3.endpoint_url,
            aws_access_key_id=settings.s3.access_key_id,
            aws_secret_access_key=settings.s3.secret_access_key,
            region_name=settings.s3.region,
        ) as s3_client:
            try:
                response = await s3_client.get_object(Bucket=bucket, Key=key)
                return await response["Body"].read()
            except ClientError as e:
                logger.error(f"S3 download failed: {e}")
                raise RuntimeError(f"S3 download failed: {e}")

    async def _read_from_local(self, path: Path) -> bytes:
        """Read content from a local file."""
        logger.debug(f"Reading from local path: {path}")
        return path.read_bytes()

    async def write_to_internal_storage(
        self,
        content: bytes,
        tenant_id: str,
        file_name: str,
        file_id: str | None = None
    ) -> tuple[str, str, str, str]:
        """
        Write content to REM's internal storage (S3 or local).

        Args:
            content: File content bytes
            tenant_id: Tenant identifier
            file_name: Name of the file
            file_id: Optional file UUID string. If not provided, one will be generated.

        Returns:
            A tuple containing (storage_uri, internal_key, content_type, file_id).
        """
        from uuid import uuid4
        import mimetypes

        if not file_id:
            file_id = str(uuid4())

        internal_key = f"{tenant_id}/files/{file_id}/{file_name}"
        storage_uri = ""

        # Use storage.provider setting to determine storage backend
        if settings.storage.provider == "s3":
            # S3 storage
            if not settings.s3.bucket_name:
                raise ValueError(
                    "STORAGE__PROVIDER is set to 's3' but S3__BUCKET_NAME is not configured. "
                    "Either set S3__BUCKET_NAME or change STORAGE__PROVIDER to 'local'."
                )

            session = aioboto3.Session()
            async with session.client(
                "s3",
                endpoint_url=settings.s3.endpoint_url,
                aws_access_key_id=settings.s3.access_key_id,
                aws_secret_access_key=settings.s3.secret_access_key,
                region_name=settings.s3.region,
            ) as s3_client:
                await s3_client.put_object(
                    Bucket=settings.s3.bucket_name,
                    Key=internal_key,
                    Body=content,
                )
                storage_uri = f"s3://{settings.s3.bucket_name}/{internal_key}"
        else:
            # Local filesystem storage (default)
            # Expand ~ to home directory
            base_path = Path(settings.storage.base_path).expanduser()
            base_path.mkdir(parents=True, exist_ok=True)
            file_path = base_path / internal_key
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(content)
            storage_uri = f"file://{file_path}"

        content_type, _ = mimetypes.guess_type(file_name)
        content_type = content_type or "application/octet-stream"

        return storage_uri, internal_key, content_type, file_id
