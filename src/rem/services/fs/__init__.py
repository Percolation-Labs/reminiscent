"""
File system abstraction layer for REM.

Provides unified interface for:
- S3 operations (via S3Provider)
- Local file operations (via LocalProvider)
- Columnar data with Polars
- Multiple file formats (yaml, json, csv, text, pdf, images, etc.)

Usage:
    from rem.services.fs import FS, generate_presigned_url

    fs = FS()

    # Read from S3 or local
    data = fs.read("s3://bucket/file.csv")
    data = fs.read("/local/path/file.parquet")

    # Write to S3 or local
    fs.write("s3://bucket/output.json", {"key": "value"})

    # Generate presigned URLs for S3
    url = generate_presigned_url("s3://bucket/file.pdf", expiry=3600)
"""

from rem.services.fs.provider import FS
from rem.services.fs.s3_provider import S3Provider, generate_presigned_url
from rem.services.fs.local_provider import LocalProvider

__all__ = [
    "FS",
    "S3Provider",
    "LocalProvider",
    "generate_presigned_url",
]
