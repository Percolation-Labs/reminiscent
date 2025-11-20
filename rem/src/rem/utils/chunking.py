"""Text chunking utilities using semchunk."""

from semchunk import chunkerify

from rem.settings import settings


def chunk_text(text: str) -> list[str]:
    """
    Chunk text using semantic chunking.

    Uses semchunk with configured chunk size from settings.

    Args:
        text: Text to chunk

    Returns:
        List of text chunks
    """
    # Semchunk uses character-based chunking by default
    chunker = chunkerify("o200k_base", chunk_size=settings.chunking.chunk_size)

    chunks = []
    for chunk in chunker(text):
        # Skip tiny chunks
        if len(chunk) < settings.chunking.min_chunk_size:
            continue

        # Truncate oversized chunks
        if len(chunk) > settings.chunking.max_chunk_size:
            chunk = chunk[: settings.chunking.max_chunk_size]

        chunks.append(chunk)

    return chunks
