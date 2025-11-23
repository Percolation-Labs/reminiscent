"""
Local filesystem provider for REM.

Provides consistent interface with S3Provider for local file operations.
Supports same formats and operations as S3Provider.

Parsing Hooks:
- Convention: Separate uploads/ and parsed/ directories
  - Uploads: ~/.rem/fs/v1/uploads/user/2025/01/19/file.pdf
  - Parsed:  ~/.rem/fs/v1/parsed/user/2025/01/19/file.pdf/{resource}
- get_parsed_uri(): Get path for parsed content/metadata/images/tables
- has_parsed(): Check if file has been parsed
- read_parsed(): Read parsed markdown, metadata, or extracted resources
- write_parsed(): Write parsed content with automatic metadata tracking
- list_parsed_resources(): Discover all parsed resources

Example:
    fs = LocalProvider()
    upload_path = "/home/user/.rem/fs/v1/uploads/user-123/2025/01/19/report.pdf"

    # Check if already parsed
    if fs.has_parsed(upload_path):
        markdown = fs.read_parsed(upload_path)
    else:
        # Parse and cache locally
        result = parse_file(upload_path)
        fs.write_parsed(
            upload_path,
            result.markdown,
            metadata={"provider": "kreuzberg", "page_count": 10}
        )

    # List all parsed resources
    resources = fs.list_parsed_resources(upload_path)
    # ['content.md', 'metadata.json', 'images/page_1.png', 'tables/table_0.parquet']
"""

from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator
from datetime import datetime
import json
import shutil
import glob as glob_module

from loguru import logger

# Optional imports for specific formats
try:
    import polars as pl
except ImportError:
    pl = None  # type: ignore[assignment]

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore[assignment]

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]


class LocalProvider:
    """
    Local filesystem provider with format detection.

    Mirrors S3Provider interface for seamless filesystem abstraction.

    Parsing Hooks:
    - get_parsed_uri(): Get path for parsed version of a file
    - read_parsed(): Read parsed content (markdown, images, etc.)
    - write_parsed(): Write parsed content with metadata
    - has_parsed(): Check if parsed version exists

    Convention:
    - Parsed files stored at {original_path}.parsed/
    - Metadata at {original_path}.parsed/metadata.json
    - Content at {original_path}.parsed/content.md (or other formats)
    """

    def exists(self, uri: str) -> bool:
        """
        Check if local file or directory exists.

        Args:
            uri: Local file path

        Returns:
            True if exists, False otherwise
        """
        return Path(uri).exists()

    def open(self, uri: str, mode: str = "rb") -> BinaryIO:
        """
        Open local file.

        Args:
            uri: Local file path
            mode: File mode (r, rb, w, wb, etc.)

        Returns:
            File object
        """
        # Ensure parent directory exists for write operations
        if mode[0] == "w" or mode[0] == "a":
            Path(uri).parent.mkdir(parents=True, exist_ok=True)

        return open(uri, mode)  # type: ignore[return-value]

    def read(self, uri: str, use_polars: bool = True, **options) -> Any:
        """
        Read local file with format detection.

        Supports same formats as S3Provider:
            - JSON (.json)
            - YAML (.yml, .yaml)
            - CSV (.csv)
            - Parquet (.parquet)
            - Feather (.feather)
            - Excel (.xlsx, .xls)
            - Text (.txt, .log, .md)
            - Images (.png, .jpg, .jpeg, .tiff, .svg)
            - PDF (.pdf) - TODO: ContentService integration
            - DOCX (.docx) - TODO: python-docx integration

        Args:
            uri: Local file path
            use_polars: Use Polars for dataframes (default: True)
            **options: Format-specific options

        Returns:
            Parsed data
        """
        p = Path(uri)
        suffix = p.suffix.lower()

        if not p.exists():
            raise FileNotFoundError(f"File not found: {uri}")

        # TODO: Integrate ContentService for PDF/DOCX
        if suffix == ".pdf":
            logger.warning("PDF parsing not yet implemented - use ContentService")
            raise NotImplementedError(
                "PDF parsing requires ContentService integration. "
                "TODO: from rem.services.content import ContentService"
            )

        if suffix == ".docx":
            logger.warning("DOCX parsing not yet implemented")
            # TODO: Add python-docx
            raise NotImplementedError(
                "DOCX requires python-docx. "
                "TODO: uv add python-docx and implement DocxProvider"
            )

        # Structured data
        if suffix in [".yml", ".yaml"]:
            if not yaml:
                raise ImportError("PyYAML required for YAML support")
            with open(uri, "r") as f:
                return yaml.safe_load(f)

        if suffix == ".json":
            with open(uri, "r") as f:
                return json.load(f)

        if suffix in [".txt", ".log", ".md"]:
            with open(uri, "r") as f:
                return f.read()

        # Columnar data
        dataframe_lib = pl if use_polars and pl else pd
        if not dataframe_lib:
            raise ImportError(
                "Either Polars or Pandas required for tabular data. "
                "Install with: uv add polars"
            )

        if suffix == ".csv":
            return dataframe_lib.read_csv(uri, **options)

        if suffix == ".parquet":
            return dataframe_lib.read_parquet(uri, **options)

        if suffix == ".feather":
            # TODO: Verify Polars feather support
            if use_polars and pl:
                logger.warning("Feather in Polars - consider Pandas if issues")
            return dataframe_lib.read_feather(uri, **options)

        if suffix in [".xls", ".xlsx"]:
            if not pd:
                raise ImportError("Pandas required for Excel")
            # TODO: Requires openpyxl or xlrd
            logger.warning("Excel requires openpyxl/xlrd - add to pyproject.toml if needed")
            return pd.read_excel(uri, sheet_name=None, **options)

        # Images
        if suffix in [".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
            if not Image:
                raise ImportError("Pillow required for images. Install with: uv add pillow")
            return Image.open(uri)

        if suffix == ".svg":
            # TODO: SVG to PIL conversion
            with open(uri, "r") as f:
                return f.read()  # Return SVG as text for now

        # TODO: Audio formats
        if suffix in [".wav", ".mp3", ".flac"]:
            logger.warning(f"Audio format {suffix} not supported")
            raise NotImplementedError(
                f"Audio format {suffix} requires audio library. "
                "TODO: Add librosa or pydub"
            )

        # Binary
        if suffix == ".pickle":
            import pickle
            with open(uri, "rb") as f:
                return pickle.load(f)

        raise ValueError(
            f"Unsupported file format: {suffix}. "
            "Supported: .json, .yaml, .csv, .parquet, .txt, .png, etc."
        )

    def write(self, uri: str, data: Any, **options):
        """
        Write data to local file with format detection.

        Mirrors S3Provider.write() interface for seamless filesystem abstraction.
        Key difference: writes directly to disk instead of BytesIO buffer.

        Args:
            uri: Local file path
            data: Data to write (DataFrame, dict, Image, bytes, str)
            **options: Format-specific options
        """
        p = Path(uri)
        suffix = p.suffix.lower()

        # Ensure parent directory exists (unlike S3, local FS needs explicit mkdir)
        p.parent.mkdir(parents=True, exist_ok=True)

        # Dataframes
        if suffix == ".parquet":
            if hasattr(data, "write_parquet"):  # Polars
                data.write_parquet(uri, **options)
            elif hasattr(data, "to_parquet"):  # Pandas
                data.to_parquet(uri, **options)
            else:
                raise TypeError(f"Cannot write {type(data)} to parquet")
            return

        if suffix == ".csv":
            if hasattr(data, "write_csv"):  # Polars
                data.write_csv(uri, **options)
            elif hasattr(data, "to_csv"):  # Pandas
                data.to_csv(uri, index=False, **options)
            elif isinstance(data, (str, bytes)):
                mode = "wb" if isinstance(data, bytes) else "w"
                with open(uri, mode) as f:
                    f.write(data)
            else:
                raise TypeError(f"Cannot write {type(data)} to CSV")
            return

        if suffix == ".feather":
            if hasattr(data, "write_feather"):  # Polars (verify method)
                data.write_feather(uri, **options)
            elif hasattr(data, "to_feather"):  # Pandas
                data.to_feather(uri, **options)
            else:
                raise TypeError(f"Cannot write {type(data)} to feather")
            return

        # Structured data
        if suffix in [".yml", ".yaml"]:
            if not isinstance(data, dict):
                raise TypeError(f"YAML requires dict, got {type(data)}")
            if not yaml:
                raise ImportError("PyYAML required for YAML")
            with open(uri, "w") as f:
                yaml.safe_dump(data, f)
            return

        if suffix == ".json":
            if not isinstance(data, dict):
                raise TypeError(f"JSON requires dict, got {type(data)}")
            with open(uri, "w") as f:
                json.dump(data, f, indent=2)
            return

        # Images
        if suffix in [".png", ".jpg", ".jpeg", ".tiff", ".tif"]:
            if not Image:
                raise ImportError("Pillow required for images")
            if not isinstance(data, Image.Image):
                data = Image.fromarray(data)
            format_name = suffix[1:]
            save_options = {"format": format_name, **options}
            if "dpi" in options:
                dpi = options["dpi"]
                save_options["dpi"] = (dpi, dpi) if isinstance(dpi, int) else dpi
            data.save(uri, **save_options)
            return

        # Documents
        if suffix == ".pdf":
            with open(uri, "wb") as f:
                f.write(data if isinstance(data, bytes) else data.encode())
            return

        if suffix == ".html":
            with open(uri, "w") as f:
                f.write(data if isinstance(data, str) else data.decode())
            return

        # Binary
        if suffix == ".pickle":
            import pickle
            with open(uri, "wb") as f:
                pickle.dump(data, f, **options)
            return

        # Text/binary fallback
        if isinstance(data, str):
            with open(uri, "w") as f:
                f.write(data)
        elif isinstance(data, bytes):
            with open(uri, "wb") as f:
                f.write(data)
        else:
            raise TypeError(f"Cannot write {type(data)} to {uri}")

    def copy(self, uri_from: str, uri_to: str):
        """
        Copy local file or directory.

        Args:
            uri_from: Source path
            uri_to: Destination path
        """
        source = Path(uri_from)
        dest = Path(uri_to)

        if not source.exists():
            raise FileNotFoundError(f"Source not found: {uri_from}")

        # Ensure destination parent exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        if source.is_file():
            shutil.copy2(source, dest)
        elif source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            raise ValueError(f"Cannot copy {source}")

    def ls(self, uri: str, **options) -> list[str]:
        """
        List files under directory recursively.

        Args:
            uri: Directory path
            **options: Listing options

        Returns:
            List of file paths
        """
        p = Path(uri)

        if not p.exists():
            return []

        if p.is_file():
            return [str(p)]

        # Recursive glob
        pattern = options.get("pattern", "**/*")
        results = []
        for item in p.glob(pattern):
            if item.is_file():
                results.append(str(item))

        return sorted(results)

    def ls_dirs(self, uri: str, **options) -> list[str]:
        """
        List immediate child directories.

        Args:
            uri: Directory path
            **options: Listing options

        Returns:
            List of directory paths
        """
        p = Path(uri)

        if not p.exists() or not p.is_dir():
            return []

        dirs = [str(d) for d in p.iterdir() if d.is_dir()]
        return sorted(dirs)

    def ls_iter(self, uri: str, **options) -> Iterator[str]:
        """
        Iterate over files in directory.

        Args:
            uri: Directory path
            **options: Listing options

        Yields:
            File paths
        """
        for file_path in self.ls(uri, **options):
            yield file_path

    def delete(self, uri: str, limit: int = 100) -> list[str]:
        """
        Delete file or directory contents.

        Safety limit prevents accidental bulk deletions.

        Args:
            uri: File or directory path
            limit: Maximum files to delete

        Returns:
            List of deleted paths
        """
        p = Path(uri)

        if not p.exists():
            return []

        deleted = []

        if p.is_file():
            p.unlink()
            deleted.append(str(p))
        elif p.is_dir():
            files = self.ls(uri)
            if len(files) > limit:
                raise ValueError(
                    f"Attempting to delete {len(files)} files exceeds "
                    f"safety limit of {limit}. Increase limit if intentional."
                )
            for file_path in files:
                Path(file_path).unlink()
                deleted.append(file_path)
            # Remove empty directories
            shutil.rmtree(p, ignore_errors=True)

        return deleted

    def read_dataset(self, uri: str):
        """
        Read local data as PyArrow dataset.

        Args:
            uri: Dataset path (parquet, etc.)

        Returns:
            PyArrow Dataset
        """
        if not pl:
            raise ImportError("Polars required for datasets. Install with: uv add polars")

        return pl.read_parquet(uri).to_arrow()

    def read_image(self, uri: str):
        """
        Read local image as PIL Image.

        Args:
            uri: Image file path

        Returns:
            PIL Image
        """
        if not Image:
            raise ImportError("Pillow required for images. Install with: uv add pillow")

        return Image.open(uri)

    def apply(self, uri: str, fn: Callable[[str], Any]) -> Any:
        """
        Apply function to local file.

        Since file is already local, just pass the path.

        Args:
            uri: Local file path
            fn: Function that takes file path

        Returns:
            Result of function call
        """
        p = Path(uri)
        if not p.exists():
            raise FileNotFoundError(f"File not found: {uri}")

        return fn(str(p.absolute()))

    def cache_data(self, data: Any, **kwargs) -> str:
        """
        Cache data locally.

        TODO: Implement local caching strategy.

        Args:
            data: Data to cache
            **kwargs: Caching options

        Returns:
            Local file path
        """
        raise NotImplementedError(
            "Local caching not yet implemented. "
            "TODO: Implement /tmp or ~/.rem/cache strategy"
        )

    def local_file(self, uri: str) -> str:
        """
        Return local file path (already local).

        Args:
            uri: Local file path

        Returns:
            Same path
        """
        return uri

    # ========================================================================
    # Parsing Hooks
    # ========================================================================
    # Convention: Separate uploads/ and parsed/ directories with deterministic matching
    # Uploads: ~/.rem/fs/v1/uploads/user-123/2025/01/19/file.pdf
    # Parsed:  ~/.rem/fs/v1/parsed/user-123/2025/01/19/file.pdf/content.md
    #          ~/.rem/fs/v1/parsed/user-123/2025/01/19/file.pdf/metadata.json
    #          ~/.rem/fs/v1/parsed/user-123/2025/01/19/file.pdf/images/page_1.png
    # ========================================================================

    def get_parsed_uri(self, uri: str, resource: str = "content.md") -> str:
        """
        Get path for parsed version of a file.

        Maps uploads/ paths to parsed/ paths deterministically:
            uploads/user/2025/01/19/file.pdf -> parsed/user/2025/01/19/file.pdf/{resource}

        Args:
            uri: Original file path (e.g., /data/v1/uploads/user/2025/01/19/file.pdf)
            resource: Resource within parsed directory (default: content.md)

        Returns:
            Parsed resource path (e.g., /data/v1/parsed/user/2025/01/19/file.pdf/content.md)

        Example:
            # Original upload
            upload_path = "/home/user/.rem/fs/v1/uploads/user-123/2025/01/19/report.pdf"

            # Get parsed markdown
            parsed_path = fs.get_parsed_uri(upload_path)
            # -> /home/user/.rem/fs/v1/parsed/user-123/2025/01/19/report.pdf/content.md

            # Get parse metadata
            meta_path = fs.get_parsed_uri(upload_path, "metadata.json")
            # -> /home/user/.rem/fs/v1/parsed/user-123/2025/01/19/report.pdf/metadata.json

            # Get extracted image
            img_path = fs.get_parsed_uri(upload_path, "images/page_1.png")
            # -> /home/user/.rem/fs/v1/parsed/user-123/2025/01/19/report.pdf/images/page_1.png
        """
        from rem.settings import settings

        # Use Path for clean manipulation
        path = Path(uri)
        path_str = str(path)

        # Replace uploads/ with parsed/ in the path
        uploads_prefix = settings.s3.uploads_prefix
        parsed_prefix = settings.s3.parsed_prefix

        if f"/{uploads_prefix}/" in path_str:
            # Replace uploads/ with parsed/ in the path
            new_path = path_str.replace(f"/{uploads_prefix}/", f"/{parsed_prefix}/", 1)
            # Append resource to the end (filename becomes a directory)
            parsed_path = f"{new_path}/{resource}"
        elif path_str.startswith(f"{uploads_prefix}/"):
            # Handle case without leading slash
            new_path = path_str.replace(f"{uploads_prefix}/", f"{parsed_prefix}/", 1)
            parsed_path = f"{new_path}/{resource}"
        else:
            # Fallback: append .parsed/ if not in uploads/ directory
            # This handles legacy paths or custom directories
            parsed_path = f"{path_str}.parsed/{resource}"

        return parsed_path

    def has_parsed(self, uri: str) -> bool:
        """
        Check if parsed version exists for a file.

        Args:
            uri: Original file path

        Returns:
            True if metadata.json exists in .parsed/ directory

        Example:
            if fs.has_parsed("/data/file.pdf"):
                content = fs.read_parsed("/data/file.pdf")
            else:
                # Trigger parsing workflow
                content_service.process_and_save(uri)
        """
        metadata_path = self.get_parsed_uri(uri, "metadata.json")
        return self.exists(metadata_path)

    def read_parsed(self, uri: str, resource: str = "content.md", **options) -> Any:
        """
        Read parsed content for a file.

        Args:
            uri: Original file path
            resource: Resource to read (default: content.md)
            **options: Format-specific read options

        Returns:
            Parsed content (format depends on resource)

        Raises:
            FileNotFoundError: If parsed version doesn't exist

        Example:
            # Read parsed markdown
            markdown = fs.read_parsed("/data/file.pdf")

            # Read parse metadata
            metadata = fs.read_parsed("/data/file.pdf", "metadata.json")

            # Read extracted table
            table = fs.read_parsed("/data/file.pdf", "tables/table_0.parquet")
        """
        parsed_path = self.get_parsed_uri(uri, resource)

        if not self.exists(parsed_path):
            raise FileNotFoundError(
                f"Parsed resource not found: {resource}. "
                f"Parse file first with ContentService.process_and_save('{uri}')"
            )

        return self.read(parsed_path, **options)

    def write_parsed(
        self,
        uri: str,
        content: Any,
        resource: str = "content.md",
        metadata: dict[str, Any] | None = None,
    ):
        """
        Write parsed content for a file.

        Automatically writes metadata.json with parse info if provided.

        Args:
            uri: Original file path
            content: Parsed content to write
            resource: Resource name (default: content.md)
            metadata: Optional parse metadata (provider, timestamp, etc.)

        Example:
            # Write parsed markdown
            fs.write_parsed(
                "/data/file.pdf",
                markdown_content,
                metadata={
                    "provider": "kreuzberg",
                    "timestamp": datetime.now().isoformat(),
                    "page_count": 10,
                }
            )

            # Write extracted image
            fs.write_parsed(
                "/data/file.pdf",
                image_data,
                resource="images/page_1.png"
            )

            # Write extracted table
            fs.write_parsed(
                "/data/file.pdf",
                table_df,
                resource="tables/table_0.parquet"
            )
        """
        # Write primary content
        parsed_path = self.get_parsed_uri(uri, resource)
        self.write(parsed_path, content)

        # Write metadata if provided
        if metadata is not None:
            # Add standard fields if not present
            if "timestamp" not in metadata:
                metadata["timestamp"] = datetime.now().isoformat()
            if "source_uri" not in metadata:
                metadata["source_uri"] = uri

            metadata_path = self.get_parsed_uri(uri, "metadata.json")
            self.write(metadata_path, metadata)

    def list_parsed_resources(self, uri: str) -> list[str]:
        """
        List all resources in parsed directory.

        Args:
            uri: Original file path (upload path)

        Returns:
            List of resource paths (relative to parsed file directory)

        Example:
            upload_path = "/home/user/.rem/fs/v1/uploads/user-123/2025/01/19/report.pdf"
            resources = fs.list_parsed_resources(upload_path)
            # Returns: ['content.md', 'metadata.json', 'images/page_1.png', 'tables/table_0.parquet']

            # Read all resources
            for resource in resources:
                data = fs.read_parsed(upload_path, resource)
        """
        # Get the parsed directory path (without specific resource)
        parsed_base = self.get_parsed_uri(uri, "")
        # Remove trailing slash for consistent listing
        parsed_base = parsed_base.rstrip("/")

        # List all files under the parsed directory
        all_paths = self.ls(parsed_base)

        # Extract relative paths from the parsed base
        resources = []
        for full_path in all_paths:
            # Remove the parsed base prefix to get relative path
            if full_path.startswith(parsed_base + "/"):
                relative = full_path[len(parsed_base) + 1:]  # +1 for the /
                resources.append(relative)

        return resources
