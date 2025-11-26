"""
File utilities for consistent file handling throughout REM.

Provides context managers and helpers for temporary file operations,
ensuring proper cleanup and consistent patterns.
"""

import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

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
