"""
Text chunking utilities for document storage.

**ARCHITECTURE NOTE - Chunking vs Token Counting**:

This module handles SEMANTIC CHUNKING for document storage:
- Character-based limits (not tokens!)
- Respects document structure (paragraphs, sections)
- Creates 2-3 paragraph chunks for searchable resources
- Stored in database with embeddings

TikToken (token counting) is used ELSEWHERE for LLM context management:
- Agent flows preparing prompts (agentic/*)
- Context window limits (128K tokens, 200K tokens)
- Agentic chunking for large inputs (utils/agentic_chunking.py)

DO NOT use tiktoken here - document chunks are storage units, not LLM inputs!
"""

import re
from rem.settings import settings


def chunk_text(text: str) -> list[str]:
    """
    Chunk text using semantic character-based chunking.

    **IMPORTANT**: Uses CHARACTER limits, NOT tokens. This creates storage chunks
    for database/embeddings. Token counting happens later in agent flows when
    preparing LLM prompts.

    Chunking strategy:
    1. Split on double newlines (paragraph boundaries) - PRIMARY
    2. Split on single newlines if paragraph too large
    3. Split on sentence endings (. ! ?) if still too large
    4. Hard split at max_chunk_size if necessary

    This creates natural 2-3 paragraph chunks suitable for semantic search.

    Args:
        text: Text to chunk

    Returns:
        List of text chunks (typically 10-50 chunks per document)

    Example:
        >>> text = "\\n\\n".join([f"Paragraph {i}. " + "Sentence. " * 20 for i in range(10)])
        >>> chunks = chunk_text(text)  # ~10 paragraphs → ~5-10 chunks
        >>> len(chunks)  # Should be reasonable, not 100+
    """
    if not text or not text.strip():
        return []

    chunks = []
    current_chunk: list[str] = []
    current_size = 0

    # Split by paragraphs (double newline) first
    paragraphs = re.split(r'\n\n+', text)

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        para_len = len(para)

        # If adding this paragraph would exceed target size, flush current chunk
        if current_size > 0 and current_size + para_len + 2 > settings.chunking.chunk_size:
            # Flush current chunk
            chunk_text = '\n\n'.join(current_chunk)
            if len(chunk_text) >= settings.chunking.min_chunk_size:
                chunks.append(chunk_text)
            current_chunk = []
            current_size = 0

        # If paragraph itself is too large, split it
        if para_len > settings.chunking.max_chunk_size:
            # Try splitting on sentences
            sentences = re.split(r'([.!?]+\s+)', para)
            sentence_chunk = ""

            for i in range(0, len(sentences), 2):
                sentence = sentences[i]
                delimiter = sentences[i + 1] if i + 1 < len(sentences) else ""

                if len(sentence_chunk) + len(sentence) + len(delimiter) > settings.chunking.max_chunk_size:
                    if sentence_chunk:
                        chunks.append(sentence_chunk.strip())
                    sentence_chunk = sentence + delimiter
                else:
                    sentence_chunk += sentence + delimiter

            if sentence_chunk.strip():
                if len(sentence_chunk) >= settings.chunking.min_chunk_size:
                    chunks.append(sentence_chunk.strip())
        else:
            # Add paragraph to current chunk
            current_chunk.append(para)
            current_size += para_len + 2  # +2 for the \n\n we'll add when joining

    # Flush remaining chunk
    if current_chunk:
        chunk_text = '\n\n'.join(current_chunk)
        if len(chunk_text) >= settings.chunking.min_chunk_size:
            chunks.append(chunk_text)

    return chunks
