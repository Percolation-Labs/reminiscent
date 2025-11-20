"""Content provider plugins for different file types."""

import json
import multiprocessing
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from loguru import logger


class ContentProvider(ABC):
    """Base class for content extraction providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/debugging."""
        pass

    @abstractmethod
    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract text content from file bytes.

        Args:
            content: Raw file bytes
            metadata: File metadata (size, type, etc.)

        Returns:
            dict with:
                - text: Extracted text content
                - metadata: Additional metadata from extraction (optional)
        """
        pass


class MarkdownProvider(ContentProvider):
    """
    Markdown content provider.

    Simple UTF-8 text extraction with basic metadata.
    Future: Could add frontmatter parsing, heading extraction, etc.
    """

    @property
    def name(self) -> str:
        return "markdown"

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract markdown content.

        Args:
            content: Markdown file bytes
            metadata: File metadata

        Returns:
            dict with text and optional metadata (heading count, links, etc.)
        """
        # Decode UTF-8 (with fallback to latin-1)
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1")

        # Basic markdown analysis
        lines = text.split("\n")
        headings = [line for line in lines if line.strip().startswith("#")]

        extraction_metadata = {
            "line_count": len(lines),
            "heading_count": len(headings),
            "char_count": len(text),
        }

        return {
            "text": text,
            "metadata": extraction_metadata,
        }


class PDFProvider(ContentProvider):
    """
    PDF content provider using Kreuzberg.

    Handles:
    - Text extraction with OCR fallback
    - Table detection and extraction
    - Daemon process workaround for multiprocessing restrictions
    """

    @property
    def name(self) -> str:
        return "pdf"

    def _is_daemon_process(self) -> bool:
        """Check if running in a daemon process."""
        try:
            return multiprocessing.current_process().daemon
        except Exception:
            return False

    def _parse_in_subprocess(self, file_path: Path) -> dict:
        """Run kreuzberg in a separate subprocess to bypass daemon restrictions."""
        script = """
import json
import sys
from pathlib import Path
from kreuzberg import ExtractionConfig, extract_file_sync

# Parse PDF with table extraction
config = ExtractionConfig(
    extract_tables=True,
    chunk_content=False,
    extract_keywords=False,
)

result = extract_file_sync(Path(sys.argv[1]), config=config)

# Serialize result to JSON
output = {
    'content': result.content,
    'tables': [
        {
            'page_number': t.get('page_number', 0),
            'text': t.get('text', ''),
        }
        for t in result.tables
    ],
    'metadata': result.metadata
}
print(json.dumps(output))
"""

        # Run in subprocess
        result = subprocess.run(
            [sys.executable, "-c", script, str(file_path)],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode != 0:
            raise RuntimeError(f"Subprocess parsing failed: {result.stderr}")

        return json.loads(result.stdout)

    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract PDF content using Kreuzberg.

        Args:
            content: PDF file bytes
            metadata: File metadata

        Returns:
            dict with text and extraction metadata
        """
        # Write bytes to temp file for kreuzberg
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            # Check if running in daemon process
            if self._is_daemon_process():
                logger.info("Daemon process detected - using subprocess workaround for PDF parsing")
                try:
                    result_dict = self._parse_in_subprocess(tmp_path)
                    text = result_dict["content"]
                    extraction_metadata = {
                        "table_count": len(result_dict["tables"]),
                        "parser": "kreuzberg_subprocess",
                    }
                except Exception as e:
                    logger.error(f"Subprocess parsing failed: {e}. Falling back to text-only.")
                    # Fallback to simple text extraction
                    from kreuzberg import ExtractionConfig, extract_file_sync
                    config = ExtractionConfig(extract_tables=False)
                    result = extract_file_sync(tmp_path, config=config)
                    text = result.content
                    extraction_metadata = {"parser": "kreuzberg_fallback"}
            else:
                # Normal execution (not in daemon)
                from kreuzberg import ExtractionConfig, extract_file_sync
                config = ExtractionConfig(
                    extract_tables=True,
                    chunk_content=False,
                    extract_keywords=False,
                )
                result = extract_file_sync(tmp_path, config=config)
                text = result.content
                extraction_metadata = {
                    "table_count": len(result.tables),
                    "parser": "kreuzberg",
                }

            return {
                "text": text,
                "metadata": extraction_metadata,
            }

        finally:
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)
