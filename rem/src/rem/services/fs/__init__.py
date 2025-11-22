"""
File system abstraction layer for REM.

Provides unified interface for:
- S3 operations (via S3Provider)
- Local file operations (via LocalProvider)
- Columnar data with Polars
- Multiple file formats (yaml, json, csv, text, pdf, images, etc.)
- Standardized path naming conventions

Usage:
    from rem.services.fs import FS, generate_presigned_url, get_uploads_path

    fs = FS()

    # Read from S3 or local
    data = fs.read("s3://bucket/file.csv")
    data = fs.read("/local/path/file.parquet")

    # Write to S3 or local
    fs.write("s3://bucket/output.json", {"key": "value"})

    # Generate presigned URLs for S3
    url = generate_presigned_url("s3://bucket/file.pdf", expiry=3600)

    # Use standardized paths
    upload_dir = get_uploads_path(user_id="user-123")
    fs.write(f"{upload_dir}/data.json", {"key": "value"})
"""

from rem.services.fs.provider import FS
from rem.services.fs.service import FileSystemService
from rem.services.fs.s3_provider import S3Provider, generate_presigned_url
from rem.services.fs.local_provider import LocalProvider
from rem.services.fs.paths import (
    get_rem_home,
    get_base_uri,
    get_uploads_path,
    get_versioned_path,
    get_user_path,
    get_temp_path,
    ensure_dir_exists,
    join_path,
)

__all__ = [
    # Core providers
    "FS",
    "FileSystemService",
    "S3Provider",
    "LocalProvider",
    "generate_presigned_url",
    # Path conventions
    "get_rem_home",
    "get_base_uri",
    "get_uploads_path",
    "get_versioned_path",
    "get_user_path",
    "get_temp_path",
    "ensure_dir_exists",
    "join_path",
]
