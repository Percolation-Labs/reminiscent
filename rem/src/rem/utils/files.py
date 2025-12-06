"""
File utilities for consistent file handling throughout REM.

Provides context managers and helpers for temporary file operations,
ensuring proper cleanup and consistent patterns.

Also provides DataFrame I/O utilities using Polars with automatic
format detection based on file extension.
"""

import tempfile
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Generator, Optional, Union

import polars as pl
from loguru import logger


@contextmanager
def temp_file_from_bytes(
    content: bytes,
    suffix: str = "",
    prefix: str = "rem_",
    dir: Optional[str] = None,
) -> Generator[Path, None, None]:
    """
    Create a temporary file from bytes, yield path, cleanup automatically.

    This context manager ensures proper cleanup of temporary files even
    if an exception occurs during processing.

    Args:
        content: Bytes to write to the temporary file
        suffix: File extension (e.g., ".pdf", ".wav")
        prefix: Prefix for the temp file name
        dir: Directory for temp file (uses system temp if None)

    Yields:
        Path to the temporary file

    Example:
        >>> with temp_file_from_bytes(pdf_bytes, suffix=".pdf") as tmp_path:
        ...     result = process_pdf(tmp_path)
        # File is automatically cleaned up after the block

    Note:
        The file is created with delete=False so we control cleanup.
        This allows the file to be read by external processes.
    """
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix=prefix,
            dir=dir,
            delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        yield tmp_path

    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")


@contextmanager
def temp_file_empty(
    suffix: str = "",
    prefix: str = "rem_",
    dir: Optional[str] = None,
) -> Generator[Path, None, None]:
    """
    Create an empty temporary file, yield path, cleanup automatically.

    Useful when you need to write to a file after creation or when
    an external process will write to the file.

    Args:
        suffix: File extension
        prefix: Prefix for the temp file name
        dir: Directory for temp file

    Yields:
        Path to the empty temporary file
    """
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix=prefix,
            dir=dir,
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        yield tmp_path

    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp file {tmp_path}: {e}")


@contextmanager
def temp_directory(
    prefix: str = "rem_",
    dir: Optional[str] = None,
) -> Generator[Path, None, None]:
    """
    Create a temporary directory, yield path, cleanup automatically.

    Args:
        prefix: Prefix for the temp directory name
        dir: Parent directory for temp directory

    Yields:
        Path to the temporary directory
    """
    import shutil

    tmp_dir: Optional[Path] = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=dir))
        yield tmp_dir

    finally:
        if tmp_dir is not None:
            try:
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory {tmp_dir}: {e}")


def ensure_parent_exists(path: Path) -> Path:
    """
    Ensure parent directory exists, creating if necessary.

    Args:
        path: File path whose parent should exist

    Returns:
        The original path (for chaining)
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def safe_delete(path: Path) -> bool:
    """
    Safely delete a file, returning success status.

    Args:
        path: Path to delete

    Returns:
        True if deleted or didn't exist, False on error
    """
    try:
        path.unlink(missing_ok=True)
        return True
    except Exception as e:
        logger.warning(f"Failed to delete {path}: {e}")
        return False


# Extension to Polars reader mapping
_EXTENSION_READERS = {
    ".csv": pl.read_csv,
    ".tsv": lambda p, **kw: pl.read_csv(p, separator="\t", **kw),
    ".parquet": pl.read_parquet,
    ".pq": pl.read_parquet,
    ".json": pl.read_json,
    ".jsonl": pl.read_ndjson,
    ".ndjson": pl.read_ndjson,
    ".avro": pl.read_avro,
    ".xlsx": pl.read_excel,
    ".xls": pl.read_excel,
    ".ods": pl.read_ods,
    ".ipc": pl.read_ipc,
    ".arrow": pl.read_ipc,
    ".feather": pl.read_ipc,
}

# Extension to Polars writer mapping
_EXTENSION_WRITERS = {
    ".csv": "write_csv",
    ".tsv": "write_csv",  # with separator="\t"
    ".parquet": "write_parquet",
    ".pq": "write_parquet",
    ".json": "write_json",
    ".jsonl": "write_ndjson",
    ".ndjson": "write_ndjson",
    ".avro": "write_avro",
    ".xlsx": "write_excel",
    ".ipc": "write_ipc",
    ".arrow": "write_ipc",
    ".feather": "write_ipc",
}


def read_dataframe(
    source: Union[str, Path, bytes],
    filename: Optional[str] = None,
    **kwargs,
) -> pl.DataFrame:
    """
    Read a DataFrame from a file, inferring format from extension.

    Supports all Polars-compatible formats:
    - CSV (.csv), TSV (.tsv)
    - Parquet (.parquet, .pq)
    - JSON (.json), JSONL/NDJSON (.jsonl, .ndjson)
    - Avro (.avro)
    - Excel (.xlsx, .xls)
    - OpenDocument (.ods)
    - Arrow IPC (.ipc, .arrow, .feather)

    Args:
        source: File path (str/Path) or bytes content
        filename: Required when source is bytes, to determine format
        **kwargs: Additional arguments passed to the Polars reader

    Returns:
        Polars DataFrame

    Raises:
        ValueError: If format cannot be determined or is unsupported

    Examples:
        >>> df = read_dataframe("data.csv")
        >>> df = read_dataframe("data.parquet")
        >>> df = read_dataframe(csv_bytes, filename="data.csv")
    """
    # Determine the file extension
    if isinstance(source, bytes):
        if not filename:
            raise ValueError("filename is required when source is bytes")
        ext = Path(filename).suffix.lower()
        # For bytes, we need to wrap in BytesIO
        file_like = BytesIO(source)
    else:
        path = Path(source)
        ext = path.suffix.lower()
        file_like = path

    # Get the appropriate reader
    reader = _EXTENSION_READERS.get(ext)
    if reader is None:
        supported = ", ".join(sorted(_EXTENSION_READERS.keys()))
        raise ValueError(
            f"Unsupported file format: {ext}. "
            f"Supported formats: {supported}"
        )

    try:
        return reader(file_like, **kwargs)
    except Exception as e:
        logger.error(f"Failed to read DataFrame from {ext} format: {e}")
        raise


def write_dataframe(
    df: pl.DataFrame,
    dest: Union[str, Path],
    **kwargs,
) -> None:
    """
    Write a DataFrame to a file, inferring format from extension.

    Supports most Polars-writable formats:
    - CSV (.csv), TSV (.tsv)
    - Parquet (.parquet, .pq)
    - JSON (.json), JSONL/NDJSON (.jsonl, .ndjson)
    - Avro (.avro)
    - Excel (.xlsx)
    - Arrow IPC (.ipc, .arrow, .feather)

    Args:
        df: Polars DataFrame to write
        dest: Destination file path
        **kwargs: Additional arguments passed to the Polars writer

    Raises:
        ValueError: If format cannot be determined or is unsupported

    Examples:
        >>> write_dataframe(df, "output.csv")
        >>> write_dataframe(df, "output.parquet")
        >>> write_dataframe(df, "output.jsonl")
    """
    path = Path(dest)
    ext = path.suffix.lower()

    writer_method = _EXTENSION_WRITERS.get(ext)
    if writer_method is None:
        supported = ", ".join(sorted(_EXTENSION_WRITERS.keys()))
        raise ValueError(
            f"Unsupported file format for writing: {ext}. "
            f"Supported formats: {supported}"
        )

    # Ensure parent directory exists
    ensure_parent_exists(path)

    # Handle TSV special case
    if ext == ".tsv":
        kwargs.setdefault("separator", "\t")

    try:
        writer = getattr(df, writer_method)
        writer(path, **kwargs)
    except Exception as e:
        logger.error(f"Failed to write DataFrame to {ext} format: {e}")
        raise
