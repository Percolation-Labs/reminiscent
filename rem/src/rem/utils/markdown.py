"""Markdown conversion utilities for document processing."""


def to_markdown(content: str, filename: str) -> str:
    """
    Convert extracted content to structured markdown.

    Args:
        content: Extracted text content
        filename: Source filename

    Returns:
        Structured markdown string with header
    """
    lines = [f"# {filename}\n", content]
    return "\n".join(lines)
