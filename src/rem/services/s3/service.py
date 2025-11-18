"""
S3Service - S3 storage operations for files and artifacts.

Provides S3 operations for:
- File uploads (PDFs, images, audio, etc.)
- Artifact storage (embeddings, processed content)
- Backup storage (CloudNativePG via Barman)
- Presigned URLs for direct access

Key Features:
- Tenant-scoped storage (prefix: {tenant_id}/)
- Multipart upload support for large files
- Streaming downloads
- Lifecycle policies for cost optimization
- Server-side encryption

Integration:
- IRSA (IAM Roles for Service Accounts) for AWS permissions
- CloudNativePG Barman for PostgreSQL backups
- File metadata stored in PostgreSQL
- S3 URIs referenced in File entities
"""

from typing import BinaryIO, Optional


class S3Service:
    """
    S3 storage service for REM.

    Manages file uploads, downloads, and lifecycle for tenant-scoped storage.
    """

    def __init__(
        self,
        bucket_name: str,
        region: str = "us-east-1",
        endpoint_url: Optional[str] = None,
    ):
        """
        Initialize S3 service.

        Args:
            bucket_name: S3 bucket name
            region: AWS region
            endpoint_url: Optional custom endpoint (for MinIO, LocalStack)
        """
        self.bucket_name = bucket_name
        self.region = region
        self.endpoint_url = endpoint_url
        # TODO: Initialize boto3 S3 client with IRSA

    async def upload_file(
        self,
        file_obj: BinaryIO,
        key: str,
        tenant_id: str,
        content_type: Optional[str] = None,
        metadata: Optional[dict[str, str]] = None,
    ) -> str:
        """
        Upload file to S3 with tenant scoping.

        Args:
            file_obj: File object to upload
            key: File key (will be prefixed with tenant_id)
            tenant_id: Tenant identifier
            content_type: Optional content type
            metadata: Optional file metadata

        Returns:
            S3 URI (s3://{bucket}/{tenant_id}/{key})
        """
        # TODO: Construct tenant-scoped key
        # TODO: Upload to S3 with metadata
        # TODO: Return S3 URI
        pass

    async def download_file(
        self, key: str, tenant_id: str
    ) -> BinaryIO:
        """
        Download file from S3.

        Args:
            key: File key
            tenant_id: Tenant identifier

        Returns:
            File object
        """
        # TODO: Construct tenant-scoped key
        # TODO: Download from S3
        # TODO: Return file object
        pass

    async def generate_presigned_url(
        self,
        key: str,
        tenant_id: str,
        expiration: int = 3600,
        operation: str = "get_object",
    ) -> str:
        """
        Generate presigned URL for direct S3 access.

        Args:
            key: File key
            tenant_id: Tenant identifier
            expiration: URL expiration in seconds
            operation: S3 operation (get_object, put_object)

        Returns:
            Presigned URL
        """
        # TODO: Construct tenant-scoped key
        # TODO: Generate presigned URL
        # TODO: Return URL
        pass

    async def delete_file(
        self, key: str, tenant_id: str
    ) -> None:
        """
        Delete file from S3.

        Args:
            key: File key
            tenant_id: Tenant identifier
        """
        # TODO: Construct tenant-scoped key
        # TODO: Delete from S3
        pass

    async def list_files(
        self, tenant_id: str, prefix: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, str]]:
        """
        List files for tenant.

        Args:
            tenant_id: Tenant identifier
            prefix: Optional key prefix filter
            limit: Maximum results

        Returns:
            List of file metadata dicts
        """
        # TODO: Construct tenant-scoped prefix
        # TODO: List objects from S3
        # TODO: Return file metadata
        pass

    async def multipart_upload_init(
        self, key: str, tenant_id: str, content_type: Optional[str] = None
    ) -> str:
        """
        Initialize multipart upload for large files.

        Args:
            key: File key
            tenant_id: Tenant identifier
            content_type: Optional content type

        Returns:
            Upload ID
        """
        # TODO: Construct tenant-scoped key
        # TODO: Initialize multipart upload
        # TODO: Return upload ID
        pass

    async def multipart_upload_part(
        self,
        upload_id: str,
        key: str,
        tenant_id: str,
        part_number: int,
        data: BinaryIO,
    ) -> dict[str, str]:
        """
        Upload part for multipart upload.

        Args:
            upload_id: Upload ID from init
            key: File key
            tenant_id: Tenant identifier
            part_number: Part number (1-indexed)
            data: Part data

        Returns:
            Part metadata (ETag, PartNumber)
        """
        # TODO: Upload part to S3
        # TODO: Return part metadata
        pass

    async def multipart_upload_complete(
        self,
        upload_id: str,
        key: str,
        tenant_id: str,
        parts: list[dict[str, str]],
    ) -> str:
        """
        Complete multipart upload.

        Args:
            upload_id: Upload ID
            key: File key
            tenant_id: Tenant identifier
            parts: List of part metadata

        Returns:
            S3 URI
        """
        # TODO: Complete multipart upload
        # TODO: Return S3 URI
        pass
