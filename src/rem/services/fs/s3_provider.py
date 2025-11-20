"""
S3 storage provider for REM file system.

Features:
- Read/write multiple formats (JSON, YAML, CSV, Parquet, images, etc.)
- Presigned URLs for direct access
- Multipart uploads for large files
- Polars integration for columnar data
- Versioning support
- Directory operations (ls, ls_dirs, delete)

Integration:
- Uses rem.settings for S3 configuration
- ContentService for special format parsing (PDF, DOCX, etc.)
- IRSA (IAM Roles for Service Accounts) in EKS
"""

from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator
from io import BytesIO
from urllib.parse import urlparse
from datetime import datetime
import json
import tempfile
import io

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, model_validator
from loguru import logger

from rem.settings import settings

# Optional imports for specific formats
try:
    import polars as pl
except ImportError:
    pl = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import yaml
except ImportError:
    yaml = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import pyarrow as pa
    import pyarrow.dataset as ds
except ImportError:
    pa = None
    ds = None


class S3ObjectListing(BaseModel):
    """S3 object metadata with convenience properties."""

    Key: str
    LastModified: datetime
    Size: int
    bucket: str
    uri: str | None = None

    def __repr__(self):
        return self.uri or f"s3://{self.bucket}/{self.Key}"

    @model_validator(mode="before")
    @classmethod
    def fixup(cls, data: Any) -> Any:
        """Construct full URI from bucket and key."""
        data["uri"] = f"s3://{data['bucket']}/{data['Key']}"
        return data


class FileLikeWritable:
    """
    Wrapper around S3 put_object to provide file-like write interface.

    Used for writing data that doesn't fit in memory or needs streaming.
    """

    def __init__(self, s3_client, bucket: str, key: str):
        self._client = s3_client
        self.bucket = bucket
        self.key = key

    def write(self, data: bytes, **options):
        """Write bytes to S3 object."""
        if isinstance(data, BytesIO):
            data = data.getvalue()
        self._client.put_object(Bucket=self.bucket, Key=self.key, Body=data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        return None


def generate_presigned_url(url: str, expiry: int = 3600, for_upload: bool = False) -> str:
    """
    Generate presigned URL for S3 object access.

    Args:
        url: S3 URI (s3://bucket/key)
        expiry: URL expiration in seconds (default: 3600)
        for_upload: Generate PUT URL instead of GET (default: False)

    Returns:
        Presigned URL for direct S3 access

    Example:
        # Download URL
        url = generate_presigned_url("s3://bucket/file.pdf")

        # Upload URL
        url = generate_presigned_url("s3://bucket/file.pdf", for_upload=True)
    """
    s3 = S3Provider()

    if not s3.is_s3_uri(url):
        return url

    bucket_name, object_key = s3._split_bucket_and_blob_from_path(url)

    try:
        if for_upload:
            return s3._client.generate_presigned_url(
                "put_object",
                Params={"Bucket": bucket_name, "Key": object_key},
                ExpiresIn=expiry,
                HttpMethod="PUT",
            )

        return s3._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket_name, "Key": object_key},
            ExpiresIn=expiry,
        )

    except Exception as ex:
        logger.error(f"Failed to generate presigned URL for {url}: {ex}")
        raise


class S3Provider:
    """
    S3 storage provider with REM settings integration.

    Supports IRSA (IAM Roles for Service Accounts) in EKS for secure access.
    Falls back to access keys for local development or MinIO.
    """

    def __init__(self):
        """Initialize S3 client from REM settings."""
        self._client = self._create_s3_client()

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

    @staticmethod
    def is_s3_uri(uri: str) -> bool:
        """Check if URI is S3 format."""
        return uri.startswith("s3://")

    def _check_uri(self, uri: str):
        """Validate S3 URI format."""
        url = urlparse(uri)
        if url.scheme != "s3":
            raise ValueError(
                f"URI must be of the form s3://BUCKET/path/to/file "
                f"but got {uri} with scheme {url.scheme}"
            )

    def _split_bucket_and_blob_from_path(self, uri: str) -> tuple[str, str]:
        """
        Split S3 URI into bucket and key.

        Args:
            uri: S3 URI (s3://bucket/path/to/file)

        Returns:
            Tuple of (bucket, key)
        """
        self._check_uri(uri)
        url = urlparse(uri)
        return url.netloc, url.path.lstrip("/")

    def exists(self, uri: str) -> bool:
        """
        Check if S3 object or prefix exists.

        Args:
            uri: S3 URI

        Returns:
            True if exists, False otherwise
        """
        bucket, prefix = self._split_bucket_and_blob_from_path(uri)

        # For files (has extension), use head_object
        if "." in Path(prefix).name:
            try:
                self._client.head_object(Bucket=bucket, Key=prefix)
                return True
            except ClientError:
                return False

        # For directories/prefixes, use list_objects_v2
        try:
            response = self._client.list_objects_v2(
                Prefix=prefix, Bucket=bucket, MaxKeys=1
            )
            return response.get("KeyCount", 0) > 0
        except ClientError:
            return False

    def open(self, uri: str, mode: str = "rb", version_id: str | None = None) -> BinaryIO:
        """
        Open S3 object as file-like object.

        Args:
            uri: S3 URI
            mode: File mode (r, rb, w, wb)
            version_id: Optional S3 version ID for versioned buckets

        Returns:
            File-like object (BytesIO for read, FileLikeWritable for write)
        """
        if mode[0] == "r":
            return BytesIO(self.get_streaming_body(uri, version_id=version_id).read())

        bucket, key = self._split_bucket_and_blob_from_path(uri)
        return FileLikeWritable(self._client, bucket, key)

    def get_streaming_body(
        self,
        uri: str,
        version_id: str | None = None,
        **kwargs,
    ):
        """
        Get streaming body for S3 object.

        Args:
            uri: S3 URI
            version_id: Optional version ID

        Returns:
            S3 streaming body
        """
        bucket, prefix = self._split_bucket_and_blob_from_path(uri)

        try:
            params = {"Bucket": bucket, "Key": prefix}
            if version_id:
                params["VersionId"] = version_id

            response = self._client.get_object(**params)
            return response["Body"]
        except ClientError as ex:
            logger.error(f"Failed to get S3 object {uri}: {ex}")
            raise

    def read(self, uri: str, use_polars: bool = True, version_id: str | None = None, **options) -> Any:
        """
        Read S3 object with format detection.

        Supports:
            - JSON (.json)
            - YAML (.yml, .yaml)
            - CSV (.csv)
            - Parquet (.parquet)
            - Feather (.feather)
            - Excel (.xlsx, .xls)
            - Text (.txt, .log, .md)
            - Images (.png, .jpg, .jpeg, .tiff, .svg)
            - PDF (.pdf) - TODO: integrate ContentService
            - DOCX (.docx) - TODO: integrate ContentService
            - WAV (.wav) - TODO: add audio provider

        Args:
            uri: S3 URI
            use_polars: Use Polars for dataframes (default: True)
            version_id: Optional S3 version ID
            **options: Format-specific options

        Returns:
            Parsed data in appropriate format
        """
        p = Path(uri)
        suffix = p.suffix.lower()

        # TODO: Integrate ContentService for PDF/DOCX parsing
        if suffix == ".pdf":
            logger.warning("PDF parsing not yet implemented - use ContentService")
            raise NotImplementedError(
                "PDF parsing requires ContentService integration. "
                "TODO: from rem.services.content import ContentService; return ContentService().process_uri(uri)"
            )

        if suffix == ".docx":
            logger.warning("DOCX parsing not yet implemented")
            # TODO: Add python-docx provider
            raise NotImplementedError(
                "DOCX parsing not yet implemented. "
                "TODO: Add python-docx to dependencies and implement DocxProvider"
            )

        # Structured data formats
        if suffix in [".yml", ".yaml"]:
            if not yaml:
                raise ImportError("PyYAML is required for YAML support")
            return yaml.safe_load(self.get_streaming_body(uri, version_id=version_id, **options))

        if suffix == ".json":
            return json.load(self.get_streaming_body(uri, version_id=version_id, **options))

        if suffix == ".txt" or suffix == ".log" or suffix == ".md":
            return self.get_streaming_body(uri, version_id=version_id, **options).read().decode()

        # Columnar data formats
        dataframe_lib = pl if use_polars and pl else pd
        if not dataframe_lib:
            raise ImportError(
                "Either Polars or Pandas is required for tabular data support. "
                "Install with: uv add polars"
            )

        if suffix == ".csv":
            with self.open(uri, "rb") as f:
                return dataframe_lib.read_csv(f, **options)

        if suffix == ".parquet":
            with self.open(uri, "rb") as f:
                return dataframe_lib.read_parquet(f, **options)

        if suffix == ".feather":
            with self.open(uri, "rb") as f:
                # TODO: Verify feather support in Polars
                if use_polars and pl:
                    logger.warning("Feather support in Polars may vary - consider using Pandas")
                return dataframe_lib.read_feather(f, **options)

        if suffix in [".xls", ".xlsx"]:
            # Excel requires pandas
            if not pd:
                raise ImportError("Pandas is required for Excel support")
            # TODO: Add openpyxl or xlrd to dependencies
            logger.warning("Excel support requires openpyxl or xlrd - add to pyproject.toml if needed")
            return pd.read_excel(uri, sheet_name=None, **options)

        # Image formats
        if suffix in [".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
            if not Image:
                raise ImportError("Pillow is required for image support. Install with: uv add pillow")
            with self.open(uri, "rb") as s3f:
                return Image.open(s3f)

        if suffix == ".svg":
            return self.get_streaming_body(uri, version_id=version_id, **options).read().decode()

        # TODO: Audio formats
        if suffix in [".wav", ".mp3", ".flac"]:
            logger.warning(f"Audio format {suffix} not yet supported")
            # TODO: Add librosa or pydub provider
            raise NotImplementedError(
                f"Audio format {suffix} requires audio processing library. "
                "TODO: Add librosa or pydub to dependencies"
            )

        # Binary formats
        if suffix == ".pickle":
            import pickle
            with self.open(uri, "rb") as f:
                return pickle.load(f)

        raise ValueError(
            f"Unsupported file format: {suffix}. "
            f"Supported formats: .json, .yaml, .csv, .parquet, .txt, .png, .jpg, etc."
        )

    def write(self, uri: str, data: Any, **options):
        """
        Write data to S3 with format detection.

        Args:
            uri: S3 URI
            data: Data to write (DataFrame, dict, Image, bytes, str)
            **options: Format-specific options
        """
        p = Path(uri)
        suffix = p.suffix.lower()
        bucket, prefix = self._split_bucket_and_blob_from_path(uri)

        def write_object(writer_fn):
            """
            Helper to write via BytesIO stream.

            Pattern: write_object(lambda s: data.write_parquet(s))
            - Creates in-memory buffer
            - Calls writer function to populate buffer
            - Uploads buffer contents to S3
            - Avoids writing temporary files to disk
            """
            stream = io.BytesIO()
            writer_fn(stream)
            self._client.put_object(Bucket=bucket, Key=prefix, Body=stream.getvalue())

        # Dataframe formats
        if suffix == ".parquet":
            if hasattr(data, "write_parquet"):  # Polars
                return write_object(lambda s: data.write_parquet(s, **options))
            elif hasattr(data, "to_parquet"):  # Pandas
                return write_object(lambda s: data.to_parquet(s, **options))
            raise TypeError(f"Cannot write {type(data)} to parquet")

        if suffix == ".csv":
            if hasattr(data, "write_csv"):  # Polars
                return write_object(lambda s: data.write_csv(s, **options))
            elif hasattr(data, "to_csv"):  # Pandas
                from functools import partial
                fn = partial(data.to_csv, index=False)
                return write_object(lambda s: fn(s, **options))
            elif isinstance(data, (bytes, str)):
                content = data.encode("utf-8") if isinstance(data, str) else data
                return self._client.put_object(
                    Bucket=bucket, Key=prefix, Body=content, ContentType="text/csv"
                )
            raise TypeError(f"Cannot write {type(data)} to CSV")

        if suffix == ".feather":
            if hasattr(data, "write_feather"):  # Polars (check method name)
                logger.warning("Feather support in Polars - verify method name")
                return write_object(lambda s: data.write_feather(s, **options))
            elif hasattr(data, "to_feather"):  # Pandas
                return write_object(lambda s: data.to_feather(s, **options))
            raise TypeError(f"Cannot write {type(data)} to feather")

        # Structured data formats
        if suffix in [".yml", ".yaml"]:
            if isinstance(data, dict):
                if not yaml:
                    raise ImportError("PyYAML required for YAML support")
                content = yaml.safe_dump(data)
                return self._client.put_object(Bucket=bucket, Key=prefix, Body=content)
            raise TypeError(f"YAML requires dict, got {type(data)}")

        if suffix == ".json":
            if isinstance(data, dict):
                content = json.dumps(data)
                return self._client.put_object(Bucket=bucket, Key=prefix, Body=content)
            raise TypeError(f"JSON requires dict, got {type(data)}")

        # Image formats
        if suffix in [".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
            if not Image:
                raise ImportError("Pillow required for image support")
            if not isinstance(data, Image.Image):
                data = Image.fromarray(data)
            format_name = suffix[1:]  # Remove leading dot
            _data = BytesIO()
            save_options = {"format": format_name, **options}
            if "dpi" in options:
                dpi = options["dpi"]
                save_options["dpi"] = (dpi, dpi) if isinstance(dpi, int) else dpi
            data.save(_data, **save_options)
            return self._client.put_object(Bucket=bucket, Key=prefix, Body=_data.getvalue())

        # Document formats
        if suffix == ".pdf":
            return self._client.put_object(
                Bucket=bucket, Key=prefix, Body=data, ContentType="application/pdf"
            )

        if suffix == ".html":
            return self._client.put_object(
                Bucket=bucket, Key=prefix, Body=data, ContentType="text/html"
            )

        # Binary/text fallback
        if suffix == ".pickle":
            import pickle
            with self.open(uri, "wb") as f:
                return write_object(lambda s: pickle.dump(data, s, **options))

        # Default: write as bytes/string
        return self._client.put_object(Bucket=bucket, Key=prefix, Body=data)

    def copy(self, uri_from: str, uri_to: str):
        """
        Copy files between S3, local, or S3-to-S3.

        Args:
            uri_from: Source URI (s3://... or local path)
            uri_to: Destination URI (s3://... or local path)
        """
        from_s3 = self.is_s3_uri(uri_from)
        to_s3 = self.is_s3_uri(uri_to)

        if to_s3 and not from_s3:
            # Upload: local -> S3
            bucket, path = self._split_bucket_and_blob_from_path(uri_to)
            self._client.upload_file(uri_from, bucket, path)

        elif not to_s3 and from_s3:
            # Download: S3 -> local
            bucket, path = self._split_bucket_and_blob_from_path(uri_from)
            # TODO: Add progress bar with tqdm
            logger.info(f"Downloading {uri_from} to {uri_to}")
            self._client.download_file(bucket, path, uri_to)

        elif to_s3 and from_s3:
            # S3 to S3 copy
            with self.open(uri_from) as from_obj:
                with self.open(uri_to, "wb") as to_obj:
                    to_obj.write(from_obj.read())
        else:
            raise ValueError("At least one of uri_from or uri_to must be an S3 path")

    def ls(self, uri: str, file_type: str = "*", search: str = "**/", **kwargs) -> list[str]:
        """
        List files under S3 prefix.

        Args:
            uri: S3 prefix URI
            file_type: File extension filter (default: all)
            search: Search pattern (default: recursive)

        Returns:
            List of S3 URIs
        """
        results = self.glob(uri, file_type=file_type, search=search, **kwargs)
        return [obj.uri for obj in results]

    def glob(
        self, uri: str, file_type: str = "*", search: str = "**/", **kwargs
    ) -> list[S3ObjectListing]:
        """
        List S3 objects with metadata.

        Args:
            uri: S3 prefix URI
            file_type: File extension filter
            search: Search pattern

        Returns:
            List of S3ObjectListing objects
        """
        bucket, prefix = self._split_bucket_and_blob_from_path(uri)

        # Ensure trailing slash for directory prefixes
        if prefix and not prefix.endswith("/"):
            prefix = prefix + "/"

        try:
            response = self._client.list_objects_v2(Prefix=prefix, Bucket=bucket)
            contents = response.get("Contents")

            if not contents:
                return []

            return [S3ObjectListing(**d, bucket=bucket) for d in contents]

        except ClientError as ex:
            logger.error(f"Failed to list S3 objects at {uri}: {ex}")
            return []

    def ls_dirs(self, uri: str, max_keys: int = 100) -> list[str]:
        """
        List immediate child directories under S3 prefix.

        Args:
            uri: S3 prefix URI
            max_keys: Maximum directories to return

        Returns:
            List of directory URIs
        """
        bucket, key = self._split_bucket_and_blob_from_path(uri)
        key = f"{key.rstrip('/')}/"

        response = self._client.list_objects_v2(
            Bucket=bucket, Prefix=key, Delimiter="/", MaxKeys=max_keys
        )

        prefixes = response.get("CommonPrefixes", [])
        dirs = [p["Prefix"].rstrip("/").split("/")[-1] for p in prefixes]
        return [f"{uri}/{d}" for d in dirs]

    def ls_iter(self, uri: str, **options) -> Iterator[str]:
        """
        Iterate over S3 objects with pagination.

        TODO: Implement pagination with continuation tokens.

        Args:
            uri: S3 prefix URI
            **options: Listing options

        Yields:
            S3 URIs
        """
        # TODO: Implement pagination for large result sets
        logger.warning("ls_iter pagination not yet implemented - returning all results")
        yield from self.ls(uri, **options)

    def delete(self, uri: str, limit: int = 50) -> list[str]:
        """
        Delete S3 objects under prefix.

        Safety limit prevents accidental bulk deletions.

        Args:
            uri: S3 URI (file or prefix)
            limit: Maximum files to delete (safety limit)

        Returns:
            List of deleted URIs
        """
        deleted_files = self.ls(uri)

        if len(deleted_files) > limit:
            raise ValueError(
                f"Attempting to delete {len(deleted_files)} files exceeds "
                f"safety limit of {limit}. Increase limit parameter if intentional."
            )

        s3_resource = boto3.resource("s3")
        for file_uri in deleted_files:
            logger.debug(f"Deleting {file_uri}")
            bucket, key = self._split_bucket_and_blob_from_path(file_uri)
            s3_resource.Object(bucket, key).delete()

        # Delete the prefix marker if it exists
        bucket, key = self._split_bucket_and_blob_from_path(uri)
        try:
            s3_resource.Object(bucket, key).delete()
        except:
            pass  # Prefix marker may not exist

        return deleted_files

    def read_dataset(self, uri: str):
        """
        Read S3 data as PyArrow dataset.

        Useful for partitioned parquet datasets and lazy loading.

        Args:
            uri: S3 dataset URI

        Returns:
            PyArrow Dataset
        """
        if not pl:
            raise ImportError("Polars required for dataset operations. Install with: uv add polars")

        with self.open(uri, mode="rb") as f:
            return pl.read_parquet(f).to_arrow()

    def read_image(self, uri: str, version_id: str | None = None):
        """
        Read S3 object as PIL Image.

        Args:
            uri: S3 image URI
            version_id: Optional S3 version ID

        Returns:
            PIL Image
        """
        if not Image:
            raise ImportError("Pillow required for image support. Install with: uv add pillow")

        if version_id:
            bucket, key = self._split_bucket_and_blob_from_path(uri)
            response = self._client.get_object(Bucket=bucket, Key=key, VersionId=version_id)
            return Image.open(BytesIO(response["Body"].read()))

        with self.open(uri, "rb") as f:
            return Image.open(f)

    def cache_data(
        self,
        data: Any,
        cache_location: str | None = None,
        suffix: str | None = None,
        **kwargs,
    ) -> str:
        """
        Cache data to S3 (typically images).

        Args:
            data: Data to cache (Image, etc.)
            cache_location: S3 prefix for cache (default: from settings)
            suffix: File extension
            **kwargs: Additional options (uri, etc.)

        Returns:
            S3 URI of cached data
        """
        if "uri" in kwargs:
            return kwargs["uri"]

        cache_location = cache_location or f"s3://{settings.s3.bucket_name}/cache"

        if Image and isinstance(data, Image.Image):
            suffix = suffix or ".png"
            # TODO: Implement res_hash for unique file naming
            import uuid
            file_id = str(uuid.uuid4())
            uri = f"{cache_location}/images/{file_id}{suffix}"
            self.write(uri, data)
            return uri

        raise NotImplementedError(
            f"Caching not implemented for type {type(data)}. "
            "Currently supports: PIL Image. TODO: Add support for other types."
        )

    def apply(self, uri: str, fn: Callable[[str], Any]) -> Any:
        """
        Apply function to S3 file via temporary local copy.

        Downloads file to /tmp, applies function, then cleans up.

        Args:
            uri: S3 URI
            fn: Function that takes local file path

        Returns:
            Result of function call
        """
        with self.open(uri, "rb") as s3f:
            suffix = Path(uri).suffix
            with tempfile.NamedTemporaryFile(
                suffix=suffix, prefix="s3_", mode="wb", delete=False
            ) as f:
                f.write(s3f.read())
                f.flush()
                try:
                    return fn(f.name)
                finally:
                    # Clean up temp file
                    Path(f.name).unlink(missing_ok=True)

    def local_file(self, uri: str) -> str:
        """
        Download S3 file to /tmp and return local path.

        Args:
            uri: S3 URI

        Returns:
            Local file path
        """
        filename = Path(uri).name
        local_path = f"/tmp/{filename}"
        self.copy(uri, local_path)
        return local_path
