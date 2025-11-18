"""
Local filesystem provider for REM.

Provides consistent interface with S3Provider for local file operations.
Supports same formats and operations as S3Provider.
"""

from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator
import json
import shutil
import glob as glob_module

from loguru import logger

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


class LocalProvider:
    """
    Local filesystem provider with format detection.

    Mirrors S3Provider interface for seamless filesystem abstraction.
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

        return open(uri, mode)

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

        Args:
            uri: Local file path
            data: Data to write
            **options: Format-specific options
        """
        p = Path(uri)
        suffix = p.suffix.lower()

        # Ensure parent directory exists
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
