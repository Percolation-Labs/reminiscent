"""Content provider plugins for different file types."""

from abc import ABC, abstractmethod
from typing import Any


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
