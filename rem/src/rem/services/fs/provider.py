"""
Unified file system interface abstracting S3 and local storage.

Design principles:
- No upload/download methods - use copy(from, to) instead
- No zip/unzip - use archive formats in copy operations
- Extension-based format detection
- Polars for columnar data by default
- ContentService integration for special formats
"""

from pathlib import Path
from typing import Any, Callable, BinaryIO, Iterator
import io

from rem.services.fs.s3_provider import S3Provider
from rem.services.fs.local_provider import LocalProvider
from rem.services.fs.git_provider import GitProvider, is_git
from rem.settings import settings


def is_s3(uri: str) -> bool:
    """Check if URI is an S3 path."""
    return uri.startswith("s3://")


def is_archive(uri: str) -> bool:
    """Check if URI is an archive file."""
    return ".zip" in uri.lower() or ".tar" in uri.lower() or ".gz" in uri.lower()


class FS:
    """
    Entry point to file systems abstracting S3 and local storage.

    All operations work seamlessly across S3 and local filesystems.
    Uses Polars for columnar data and ContentService for special formats.
    """

    def __init__(self):
        """Initialize filesystem with S3, local, and Git providers."""
        self._s3_provider = S3Provider()
        self._local_provider = LocalProvider()
        self._git_provider = GitProvider() if settings.git.enabled else None

    def https_to_file(self, web_request_uri: str, target_uri: str, token: str | None = None):
        """
        Download a remote resource to the filesystem.

        Examples:
            - Download Airtable/Slack files to S3
            - Download public files to local storage

        Args:
            web_request_uri: HTTPS URL to download from
            target_uri: Destination (s3://... or local path)
            token: Optional bearer token for authorization
        """
        import requests

        headers = {"Authorization": f"Bearer {token}"} if token else None
        response = requests.get(web_request_uri, headers=headers)
        response.raise_for_status()

        with self.open(target_uri, "wb") as f:
            f.write(response.content)

    def open(self, uri: str, mode: str = "rb") -> BinaryIO:
        """
        Open file for read or write.

        Args:
            uri: File path (s3://... or local path)
            mode: File mode (r, rb, w, wb, etc.)

        Returns:
            File-like object
        """
        if is_s3(uri):
            return self._s3_provider.open(uri, mode=mode)
        else:
            return self._local_provider.open(uri, mode=mode)

    def exists(self, uri: str) -> bool:
        """
        Check if file or folder exists.

        Args:
            uri: File or directory path (s3://, git://, or local)

        Returns:
            True if exists, False otherwise
        """
        if is_git(uri):
            if not self._git_provider:
                raise ValueError("Git provider not enabled. Set GIT__ENABLED=true")
            return self._git_provider.exists(uri)
        elif is_s3(uri):
            return self._s3_provider.exists(uri)
        else:
            return self._local_provider.exists(uri)

    def from_parent_dir(self, uri: str, file: str | None = None) -> str:
        """
        Construct path from parent directory.

        Args:
            uri: Current file path
            file: Optional file name to append

        Returns:
            Parent directory path (optionally with file appended)
        """
        pth = str(Path(uri).parent)
        if is_s3(uri):
            pth = pth.replace("s3:/", "s3://")
        return pth if not file else f"{pth}/{file}"

    def read(self, uri: str, use_polars: bool = True, **options) -> Any:
        """
        Read any data type - extensions determine the reader.

        Supports:
            - Columnar: .csv, .parquet, .feather, .avro (via Polars/Pandas)
            - Structured: .json, .yaml, .yml
            - Documents: .pdf, .docx, .md, .txt
            - Images: .png, .jpg, .jpeg, .tiff, .svg
            - Binary: .pickle
            - Audio: .wav, .mp3 (TODO)
            - Spreadsheets: .xlsx, .xls

        Args:
            uri: File path (s3://, git://, or local)
            use_polars: Use Polars for dataframes (default: True)
            **options: Format-specific options

        Returns:
            Parsed data in appropriate format
        """
        if is_git(uri):
            if not self._git_provider:
                raise ValueError("Git provider not enabled. Set GIT__ENABLED=true")
            return self._git_provider.read(uri, **options)
        elif is_s3(uri):
            return self._s3_provider.read(uri, use_polars=use_polars, **options)
        else:
            return self._local_provider.read(uri, use_polars=use_polars, **options)

    def write(self, uri: str, data: Any, **options):
        """
        Write any data type - extensions determine the writer.

        Args:
            uri: File path
            data: Data to write
            **options: Format-specific options
        """
        if is_s3(uri):
            return self._s3_provider.write(uri, data, **options)
        else:
            return self._local_provider.write(uri, data, **options)

    def copy(self, uri_from: str, uri_to: str):
        """
        Copy files between filesystems.

        Supports:
            - s3 -> s3
            - local -> s3 (upload)
            - s3 -> local (download)
            - local -> local

        Args:
            uri_from: Source path
            uri_to: Destination path
        """
        from_s3 = is_s3(uri_from)
        to_s3 = is_s3(uri_to)

        if from_s3 and to_s3:
            # S3 to S3
            return self._s3_provider.copy(uri_from, uri_to)
        elif from_s3 and not to_s3:
            # S3 to local (download)
            return self._s3_provider.copy(uri_from, uri_to)
        elif not from_s3 and to_s3:
            # Local to S3 (upload)
            return self._s3_provider.copy(uri_from, uri_to)
        else:
            # Local to local
            return self._local_provider.copy(uri_from, uri_to)

    def cache_data(self, data: Any, **kwargs) -> str:
        """
        Cache data to S3 storage.

        Currently supports images, can be extended for other types.

        Args:
            data: Data to cache
            **kwargs: Additional options (uri, suffix, etc.)

        Returns:
            URI of cached data
        """
        return self._s3_provider.cache_data(data, **kwargs)

    def ls(self, uri: str, **options) -> list[str]:
        """
        List files from a prefix recursively.

        Args:
            uri: Directory path or prefix (s3://, git://, or local)
            **options: Provider-specific options

        Returns:
            List of file URIs
        """
        if is_git(uri):
            if not self._git_provider:
                raise ValueError("Git provider not enabled. Set GIT__ENABLED=true")
            return self._git_provider.ls(uri, **options)
        elif is_s3(uri):
            return self._s3_provider.ls(uri, **options)
        else:
            return self._local_provider.ls(uri, **options)

    def ls_dirs(self, uri: str, **options) -> list[str]:
        """
        List immediate child directories.

        Args:
            uri: Directory path or prefix
            **options: Provider-specific options

        Returns:
            List of directory URIs
        """
        if is_s3(uri):
            return self._s3_provider.ls_dirs(uri, **options)
        else:
            return self._local_provider.ls_dirs(uri, **options)

    def ls_iter(self, uri: str, **options) -> Iterator[str]:
        """
        Iterate over files from a prefix (for pagination).

        Args:
            uri: Directory path or prefix
            **options: Provider-specific options

        Yields:
            File URIs
        """
        if is_s3(uri):
            yield from self._s3_provider.ls_iter(uri, **options)
        else:
            yield from self._local_provider.ls_iter(uri, **options)

    def delete(self, uri: str, limit: int = 100):
        """
        Delete objects in a folder/directory.

        Safety limit prevents accidental bulk deletions.

        Args:
            uri: File or directory path
            limit: Maximum number of files to delete

        Returns:
            List of deleted file URIs
        """
        if is_s3(uri):
            return self._s3_provider.delete(uri, limit=limit)
        else:
            return self._local_provider.delete(uri, limit=limit)

    def read_dataset(self, uri: str):
        """
        Read data as PyArrow dataset.

        Useful for:
            - Lazy loading large datasets
            - Partitioned data
            - S3 Express use cases

        Args:
            uri: Dataset path (parquet, etc.)

        Returns:
            PyArrow Dataset
        """
        if is_s3(uri):
            return self._s3_provider.read_dataset(uri)
        else:
            return self._local_provider.read_dataset(uri)

    def read_image(self, uri: str):
        """
        Read image as PIL Image.

        Args:
            uri: Image file path

        Returns:
            PIL Image object
        """
        if is_s3(uri):
            return self._s3_provider.read_image(uri)
        else:
            return self._local_provider.read_image(uri)

    def apply(self, uri: str, fn: Callable[[str], Any]) -> Any:
        """
        Apply a function to a file.

        Downloads file to temporary location if needed, then passes
        local path to the function.

        Args:
            uri: File path
            fn: Function that takes a local file path

        Returns:
            Result of function call
        """
        if is_s3(uri):
            return self._s3_provider.apply(uri, fn)
        else:
            return self._local_provider.apply(uri, fn)

    def local_file(self, uri: str) -> str:
        """
        Get local file path, downloading from S3 if needed.

        Args:
            uri: File path (s3://... or local)

        Returns:
            Local file path
        """
        if is_s3(uri):
            return self._s3_provider.local_file(uri)
        else:
            return uri

    # ========================================================================
    # Parsing Hooks
    # ========================================================================

    def get_parsed_uri(self, uri: str, resource: str = "content.md") -> str:
        """
        Get URI for parsed version of a file.

        Args:
            uri: Original file URI
            resource: Resource within parsed directory (default: content.md)

        Returns:
            Parsed resource URI

        Example:
            fs = FS()
            parsed_uri = fs.get_parsed_uri("s3://bucket/file.pdf")
            metadata_uri = fs.get_parsed_uri("s3://bucket/file.pdf", "metadata.json")
        """
        if is_s3(uri):
            return self._s3_provider.get_parsed_uri(uri, resource)
        else:
            return self._local_provider.get_parsed_uri(uri, resource)

    def has_parsed(self, uri: str) -> bool:
        """
        Check if parsed version exists for a file.

        Args:
            uri: Original file URI

        Returns:
            True if metadata.json exists in .parsed/ directory

        Example:
            if fs.has_parsed("s3://bucket/file.pdf"):
                content = fs.read_parsed("s3://bucket/file.pdf")
        """
        if is_s3(uri):
            return self._s3_provider.has_parsed(uri)
        else:
            return self._local_provider.has_parsed(uri)

    def read_parsed(self, uri: str, resource: str = "content.md", **options) -> Any:
        """
        Read parsed content for a file.

        Args:
            uri: Original file URI
            resource: Resource to read (default: content.md)
            **options: Format-specific read options

        Returns:
            Parsed content (format depends on resource)

        Example:
            # Read parsed markdown
            markdown = fs.read_parsed("s3://bucket/file.pdf")

            # Read parse metadata
            metadata = fs.read_parsed("s3://bucket/file.pdf", "metadata.json")
        """
        if is_s3(uri):
            return self._s3_provider.read_parsed(uri, resource, **options)
        else:
            return self._local_provider.read_parsed(uri, resource, **options)

    def write_parsed(
        self,
        uri: str,
        content: Any,
        resource: str = "content.md",
        metadata: dict[str, Any] | None = None,
    ):
        """
        Write parsed content for a file.

        Args:
            uri: Original file URI
            content: Parsed content to write
            resource: Resource name (default: content.md)
            metadata: Optional parse metadata

        Example:
            fs.write_parsed(
                "s3://bucket/file.pdf",
                markdown_content,
                metadata={"provider": "kreuzberg", "page_count": 10}
            )
        """
        if is_s3(uri):
            self._s3_provider.write_parsed(uri, content, resource, metadata)
        else:
            self._local_provider.write_parsed(uri, content, resource, metadata)

    def list_parsed_resources(self, uri: str) -> list[str]:
        """
        List all resources in parsed directory.

        Args:
            uri: Original file URI

        Returns:
            List of resource paths (relative to .parsed/ directory)

        Example:
            resources = fs.list_parsed_resources("s3://bucket/file.pdf")
            # ['content.md', 'metadata.json', 'images/page_1.png']
        """
        if is_s3(uri):
            return self._s3_provider.list_parsed_resources(uri)
        else:
            return self._local_provider.list_parsed_resources(uri)
