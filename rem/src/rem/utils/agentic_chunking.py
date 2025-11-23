"""Agentic chunking utilities for splitting large inputs across model context windows.

This module provides token-aware chunking for agent inputs that exceed model
context limits. Chunks can be processed independently by agents and merged
back using configurable strategies.

Key Features:
- Token counting using tiktoken for OpenAI models
- Character estimation fallback for other providers
- Model-specific context window limits
- Smart section-based chunking for markdown
- Configurable merge strategies: concatenate, merge_json, llm_merge (planned)

Usage:
    from rem.utils.agentic_chunking import smart_chunk_text, merge_results, MergeStrategy

    # Smart chunking (recommended - auto-sizes based on model)
    chunks = smart_chunk_text(text, model="gpt-4o")

    # Process each chunk with agent
    results = [agent.run(chunk) for chunk in chunks]

    # Merge results
    merged = merge_results(results, strategy=MergeStrategy.CONCATENATE_LIST)
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Module logger
logger = logging.getLogger(__name__)

# Constants for token estimation and chunking
CHARS_PER_TOKEN_HEURISTIC = 4  # Conservative estimate: ~4 characters per token
TOKEN_OVERHEAD_MULTIPLIER = 1.05  # Add 5% overhead for special tokens/encoding
DEFAULT_BUFFER_RATIO = 0.75  # Use 75% of available tokens (conservative for safety)


@dataclass
class ModelLimits:
    """Token limits for a model."""

    max_context: int
    max_output: int

    @property
    def max_input(self) -> int:
        """Maximum tokens for input (context - output buffer)."""
        return self.max_context - self.max_output


# Model context limits (conservative estimates)
# Source: Provider documentation as of Jan 2025
MODEL_LIMITS = {
    # OpenAI
    "gpt-4o": ModelLimits(max_context=128000, max_output=16384),
    "gpt-4o-mini": ModelLimits(max_context=128000, max_output=16384),
    "gpt-4-turbo": ModelLimits(max_context=128000, max_output=4096),
    "gpt-3.5-turbo": ModelLimits(max_context=16385, max_output=4096),
    "o1": ModelLimits(max_context=200000, max_output=100000),
    "o1-mini": ModelLimits(max_context=128000, max_output=65536),
    # Anthropic
    "claude-sonnet-4-20250514": ModelLimits(max_context=200000, max_output=8192),
    "claude-sonnet-4": ModelLimits(max_context=200000, max_output=8192),
    "claude-3-5-sonnet-20241022": ModelLimits(max_context=200000, max_output=8192),
    "claude-3-opus-20240229": ModelLimits(max_context=200000, max_output=4096),
    "claude-3-sonnet-20240229": ModelLimits(max_context=200000, max_output=4096),
    # Google
    "gemini-2.0-flash-exp": ModelLimits(max_context=1000000, max_output=8192),
    "gemini-1.5-pro": ModelLimits(max_context=2000000, max_output=8192),
    # Default fallback
    "default": ModelLimits(max_context=32000, max_output=4096),
}


class MergeStrategy(str, Enum):
    """Strategy for merging chunked agent results.

    Available strategies:
    - CONCATENATE_LIST: Merge lists, shallow update dicts, keep first scalar (default)
    - MERGE_JSON: Deep recursive merge of nested JSON objects
    - LLM_MERGE: Use LLM for intelligent semantic merging (NOT YET IMPLEMENTED)
    """

    CONCATENATE_LIST = "concatenate_list"  # Default: merge lists, update dicts, keep first scalar
    MERGE_JSON = "merge_json"  # Deep merge JSON objects
    LLM_MERGE = "llm_merge"  # PLANNED: Use LLM to intelligently merge results


def get_model_limits(model: str) -> ModelLimits:
    """Get token limits for a model.

    Args:
        model: Model name (e.g., "gpt-4o", "claude-sonnet-4")

    Returns:
        ModelLimits for the model

    Examples:
        >>> limits = get_model_limits("gpt-4o")
        >>> limits.max_input
        111616

        >>> limits = get_model_limits("claude-sonnet-4")
        >>> limits.max_input
        191808
    """
    # Direct lookup
    if model in MODEL_LIMITS:
        return MODEL_LIMITS[model]

    # Fuzzy match by model family
    model_lower = model.lower()

    # OpenAI family
    if "gpt-4o-mini" in model_lower:
        return MODEL_LIMITS["gpt-4o-mini"]
    elif "gpt-4o" in model_lower:
        return MODEL_LIMITS["gpt-4o"]
    elif "gpt-4" in model_lower:
        return MODEL_LIMITS["gpt-4-turbo"]
    elif "gpt-3.5" in model_lower or "gpt-35" in model_lower:
        return MODEL_LIMITS["gpt-3.5-turbo"]
    elif "o1-mini" in model_lower:
        return MODEL_LIMITS["o1-mini"]
    elif "o1" in model_lower:
        return MODEL_LIMITS["o1"]

    # Anthropic family
    if "claude-sonnet-4" in model_lower or "claude-4" in model_lower:
        return MODEL_LIMITS["claude-sonnet-4"]
    elif "claude-3.5" in model_lower or "claude-3-5" in model_lower:
        return MODEL_LIMITS["claude-3-5-sonnet-20241022"]
    elif "claude-3" in model_lower:
        return MODEL_LIMITS["claude-3-sonnet-20240229"]
    elif "claude" in model_lower:
        return MODEL_LIMITS["claude-3-sonnet-20240229"]

    # Google family
    if "gemini-2" in model_lower:
        return MODEL_LIMITS["gemini-2.0-flash-exp"]
    elif "gemini" in model_lower:
        return MODEL_LIMITS["gemini-1.5-pro"]

    # Default fallback
    return MODEL_LIMITS["default"]


def estimate_tokens(text: str, model: str | None = None) -> int:
    """Estimate token count for text.

    Uses tiktoken for OpenAI models (exact count).
    Falls back to character-based heuristic for other providers.

    Args:
        text: Text to estimate tokens for
        model: Optional model name for tiktoken encoding selection

    Returns:
        Estimated token count

    Examples:
        >>> estimate_tokens("Hello world", model="gpt-4o")
        2

        >>> estimate_tokens("Hello world", model="claude-sonnet-4")
        3  # Heuristic estimate
    """
    if not text:
        return 0

    # Try tiktoken for OpenAI models (exact counting)
    if model and ("gpt" in model.lower() or "o1" in model.lower()):
        try:
            import tiktoken

            # Get encoding for model
            try:
                encoding = tiktoken.encoding_for_model(model)
                token_count = len(encoding.encode(text))
                logger.debug(f"Exact token count via tiktoken: {token_count} tokens (model: {model})")
                return token_count
            except KeyError:
                # Fall back to cl100k_base for unknown OpenAI models
                logger.warning(
                    f"Unknown OpenAI model '{model}', falling back to cl100k_base encoding. "
                    "Token counts may be inaccurate."
                )
                encoding = tiktoken.get_encoding("cl100k_base")
                return len(encoding.encode(text))
        except ImportError:
            # tiktoken not installed, fall through to heuristic
            logger.debug(
                "tiktoken not installed, using character-based heuristic for token estimation. "
                "Install tiktoken for exact OpenAI token counting: pip install tiktoken"
            )

    # Character-based heuristic
    base_estimate = len(text) / CHARS_PER_TOKEN_HEURISTIC
    token_estimate = int(base_estimate * TOKEN_OVERHEAD_MULTIPLIER)
    logger.debug(
        f"Heuristic token estimate: {token_estimate} tokens "
        f"(chars={len(text)}, ratio={CHARS_PER_TOKEN_HEURISTIC}, overhead={TOKEN_OVERHEAD_MULTIPLIER})"
    )
    return token_estimate


def smart_chunk_text(
    text: str,
    model: str,
    system_prompt: str = "",
    buffer_ratio: float = DEFAULT_BUFFER_RATIO,
    preserve_lines: bool = True,
) -> list[str]:
    """Intelligently chunk text based on model limits with automatic sizing.

    This is the recommended way to chunk text - it automatically calculates
    optimal chunk size based on the model's context window, accounting for
    system prompt overhead and safety buffers.

    Args:
        text: Text to chunk
        model: Model name (e.g., "gpt-4o", "claude-sonnet-4")
        system_prompt: System prompt that will be used (to account for overhead)
        buffer_ratio: Ratio of available tokens to use (default 0.75 = 75%)
        preserve_lines: If True, avoid splitting mid-line

    Returns:
        List of text chunks, each optimally sized for the model

    Examples:
        >>> # CV extraction - will fit in single chunk for GPT-4o (128K context)
        >>> cv_text = load_cv("john-doe.txt")  # 5K tokens
        >>> chunks = smart_chunk_text(cv_text, model="gpt-4o")
        >>> len(chunks)
        1

        >>> # Large contract - will split intelligently
        >>> contract = load_contract("agreement.pdf")  # 150K tokens
        >>> chunks = smart_chunk_text(contract, model="gpt-4o")
        >>> len(chunks)
        2

        >>> # With custom system prompt overhead
        >>> chunks = smart_chunk_text(
        ...     text,
        ...     model="gpt-4o",
        ...     system_prompt="Extract key terms from this contract...",
        ...     buffer_ratio=0.7  # More conservative for complex prompts
        ... )
    """
    try:
        if not text:
            logger.debug("smart_chunk_text called with empty text")
            return []

        # Get model limits
        limits = get_model_limits(model)

        # Calculate overhead from system prompt
        system_tokens = estimate_tokens(system_prompt, model) if system_prompt else 0

        # Calculate available tokens for content
        # Reserve space for: system prompt + output buffer + safety margin
        available_tokens = limits.max_input - system_tokens

        # Apply buffer ratio for safety
        max_chunk_tokens = int(available_tokens * buffer_ratio)

        # Check if text fits in single chunk
        text_tokens = estimate_tokens(text, model)

        logger.debug(
            f"Chunking analysis: model={model}, text_tokens={text_tokens}, "
            f"max_chunk_tokens={max_chunk_tokens} (buffer={buffer_ratio*100:.0f}%), "
            f"system_overhead={system_tokens}, available={available_tokens}"
        )

        if text_tokens <= max_chunk_tokens:
            logger.debug("Text fits in single chunk, no chunking needed")
            return [text]

        # Need to chunk
        strategy = "line-based" if preserve_lines else "character-based"
        logger.info(
            f"Chunking required: {text_tokens} tokens exceeds {max_chunk_tokens} limit "
            f"(model: {model}). Using {strategy} strategy."
        )

        if preserve_lines:
            chunks = _chunk_by_lines(text, max_chunk_tokens, model)
        else:
            chunks = _chunk_by_chars(text, max_chunk_tokens, model)

        logger.info(
            f"Created {len(chunks)} chunks from {text_tokens} token input "
            f"(avg {text_tokens//len(chunks)} tokens/chunk)"
        )
        return chunks

    except Exception as e:
        logger.exception(
            f"Chunking failed: model={model}, text_length={len(text)}, "
            f"buffer_ratio={buffer_ratio}"
        )
        raise


def chunk_text(
    text: str,
    max_tokens: int,
    model: str | None = None,
    preserve_lines: bool = True,
) -> list[str]:
    """Chunk text to fit within token limit.

    NOTE: Consider using smart_chunk_text() instead, which automatically
    calculates optimal chunk size based on model limits.

    Args:
        text: Text to chunk
        max_tokens: Maximum tokens per chunk
        model: Optional model name for token counting
        preserve_lines: If True, avoid splitting mid-line

    Returns:
        List of text chunks, each within token limit

    Examples:
        >>> text = "Line 1\\nLine 2\\nLine 3\\n" * 1000
        >>> chunks = chunk_text(text, max_tokens=1000, model="gpt-4o")
        >>> len(chunks) > 1
        True
        >>> all(estimate_tokens(c, "gpt-4o") <= 1000 for c in chunks)
        True
    """
    if not text:
        return []

    # Check if text fits in single chunk
    text_tokens = estimate_tokens(text, model)
    if text_tokens <= max_tokens:
        return [text]

    # Need to chunk - use line-based or character-based approach
    if preserve_lines:
        return _chunk_by_lines(text, max_tokens, model)
    else:
        return _chunk_by_chars(text, max_tokens, model)


def _chunk_by_lines(text: str, max_tokens: int, model: str | None) -> list[str]:
    """Chunk text by lines, preserving line boundaries.

    Args:
        text: Text to chunk
        max_tokens: Maximum tokens per chunk
        model: Optional model name for token counting

    Returns:
        List of text chunks
    """
    chunks = []
    lines = text.split("\n")
    current_chunk: list[str] = []
    current_tokens = 0

    logger.debug(f"Line-based chunking: {len(lines)} lines, max_tokens={max_tokens}")

    for line_num, line in enumerate(lines, 1):
        line_tokens = estimate_tokens(line + "\n", model)

        # If single line exceeds limit, split it by characters
        if line_tokens > max_tokens:
            logger.warning(
                f"Line {line_num} exceeds token limit ({line_tokens} > {max_tokens}), "
                f"falling back to character-based chunking. Line preview: {line[:100]}..."
            )

            # Save current chunk if any
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_tokens = 0

            # Split the large line
            line_chunks = _chunk_by_chars(line, max_tokens, model)
            chunks.extend(line_chunks)
            continue

        # Check if adding this line would exceed limit
        if current_tokens + line_tokens > max_tokens and current_chunk:
            # Save current chunk and start new one
            logger.debug(f"Chunk boundary at line {line_num} ({current_tokens} tokens)")
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_tokens = line_tokens
        else:
            # Add to current chunk
            current_chunk.append(line)
            current_tokens += line_tokens

    # Add final chunk
    if current_chunk:
        chunks.append("\n".join(current_chunk))

    logger.debug(f"Line chunking complete: {len(chunks)} chunks created")
    return chunks if chunks else [text]


def _chunk_by_chars(text: str, max_tokens: int, model: str | None) -> list[str]:
    """Fallback: chunk text by characters when line-based chunking fails.

    Args:
        text: Text to chunk
        max_tokens: Maximum tokens per chunk
        model: Optional model name for token counting

    Returns:
        List of text chunks
    """
    # Convert tokens to approximate chars using heuristic
    max_chars = int(max_tokens * CHARS_PER_TOKEN_HEURISTIC)

    chunks = []
    start = 0
    text_len = len(text)

    logger.debug(
        f"Character-based chunking: text_length={text_len} chars, "
        f"max_chars={max_chars} (max_tokens={max_tokens})"
    )

    while start < text_len:
        # Calculate end position
        end = min(start + max_chars, text_len)

        # Try to break at word boundary if not at text end
        if end < text_len:
            # Look back for space
            space_pos = text.rfind(" ", start, end)
            if space_pos > start:
                original_end = end
                end = space_pos
                logger.debug(
                    f"Adjusted chunk boundary for word break: {original_end} → {end}"
                )

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end

    logger.debug(
        f"Character chunking complete: {len(chunks)} chunks created "
        f"(avg {text_len//len(chunks) if chunks else 0} chars/chunk)"
    )
    return chunks if chunks else [text]


def merge_results(
    results: list[dict[str, Any]],
    strategy: MergeStrategy = MergeStrategy.CONCATENATE_LIST,
) -> dict[str, Any]:
    """Merge multiple agent results using specified strategy.

    Args:
        results: List of result dictionaries from agent chunks
        strategy: Merge strategy to use

    Returns:
        Merged result dictionary

    Examples:
        >>> results = [
        ...     {"items": [1, 2], "count": 2},
        ...     {"items": [3, 4], "count": 2}
        ... ]
        >>> merged = merge_results(results, MergeStrategy.CONCATENATE_LIST)
        >>> merged["items"]
        [1, 2, 3, 4]
        >>> merged["count"]
        2
    """
    try:
        if not results:
            logger.debug("merge_results called with empty results list")
            return {}

        if len(results) == 1:
            logger.debug("merge_results called with single result, returning as-is")
            return results[0]

        logger.info(
            f"Merging {len(results)} chunk results using strategy: {strategy.value}"
        )

        if strategy == MergeStrategy.CONCATENATE_LIST:
            merged = _merge_concatenate(results)
        elif strategy == MergeStrategy.MERGE_JSON:
            merged = _merge_json_deep(results)
        elif strategy == MergeStrategy.LLM_MERGE:
            raise NotImplementedError("LLM merge strategy not yet implemented")
        else:
            raise ValueError(f"Unknown merge strategy: {strategy}")

        logger.debug(f"Merge complete: result has {len(merged)} top-level keys")
        return merged

    except Exception as e:
        logger.exception(
            f"Merge failed: strategy={strategy.value}, num_results={len(results)}"
        )
        raise


def _merge_concatenate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Default merge: concatenate lists, update dicts, keep first scalar.

    Args:
        results: List of result dictionaries

    Returns:
        Merged result
    """
    merged = results[0].copy()
    logger.debug(f"Starting concatenate merge with {len(results)} results")

    for chunk_num, result in enumerate(results[1:], start=2):
        logger.debug(f"Merging chunk {chunk_num}/{len(results)}")

        for key, value in result.items():
            if key not in merged:
                merged[key] = value
                logger.debug(f"  Added new key '{key}' from chunk {chunk_num}")
                continue

            merged_value = merged[key]

            # Merge lists by concatenation
            if isinstance(merged_value, list) and isinstance(value, list):
                original_len = len(merged_value)
                merged[key] = merged_value + value
                logger.debug(
                    f"  Concatenated list '{key}': {original_len} + {len(value)} = {len(merged[key])} items"
                )

            # Merge dicts by update (shallow)
            elif isinstance(merged_value, dict) and isinstance(value, dict):
                merged[key].update(value)
                logger.debug(f"  Updated dict '{key}' with {len(value)} keys from chunk {chunk_num}")

            # For scalars, prefer non-None values, or keep first
            else:
                if merged_value is None:
                    merged[key] = value
                    logger.debug(f"  Replaced None value for '{key}' with value from chunk {chunk_num}")
                elif value is not None and merged_value != value:
                    # CRITICAL: Warn about silent data loss
                    logger.warning(
                        f"Scalar value conflict for key '{key}': "
                        f"keeping first value ({merged_value!r}), "
                        f"discarding chunk {chunk_num} value ({value!r})"
                    )

    logger.debug(f"Concatenate merge complete: {len(merged)} keys in result")
    return merged


def _merge_json_deep(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Deep merge JSON objects recursively.

    Args:
        results: List of result dictionaries

    Returns:
        Deeply merged result
    """
    logger.debug(f"Starting deep JSON merge with {len(results)} results")

    def deep_merge(base: dict, update: dict, depth: int = 0) -> dict:
        """Recursively merge update into base."""
        merged = base.copy()
        indent = "  " * depth

        for key, value in update.items():
            if key not in merged:
                merged[key] = value
                logger.debug(f"{indent}Added new key '{key}' at depth {depth}")
            elif isinstance(merged[key], dict) and isinstance(value, dict):
                logger.debug(f"{indent}Deep merging dict '{key}' at depth {depth}")
                merged[key] = deep_merge(merged[key], value, depth + 1)
            elif isinstance(merged[key], list) and isinstance(value, list):
                original_len = len(merged[key])
                merged[key] = merged[key] + value
                logger.debug(
                    f"{indent}Concatenated list '{key}' at depth {depth}: "
                    f"{original_len} + {len(value)} = {len(merged[key])} items"
                )
            else:
                # Keep first non-None value
                if merged[key] is None:
                    merged[key] = value
                    logger.debug(f"{indent}Replaced None value for '{key}' at depth {depth}")
                elif value is not None and merged[key] != value:
                    logger.warning(
                        f"{indent}Scalar conflict at depth {depth} for '{key}': "
                        f"keeping first value ({merged[key]!r}), discarding ({value!r})"
                    )

        return merged

    result = results[0].copy()
    for chunk_num, r in enumerate(results[1:], start=2):
        logger.debug(f"Deep merging chunk {chunk_num}/{len(results)}")
        result = deep_merge(result, r, depth=0)

    logger.debug(f"Deep merge complete: {len(result)} top-level keys")
    return result
