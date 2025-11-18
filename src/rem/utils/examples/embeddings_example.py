"""
Example usage of embeddings utility for generating vector embeddings.

This demonstrates batch processing, error handling with tenacity automatic retries,
and integration patterns for the PostgresService.
"""

from rem.utils.embeddings import (
    EmbeddingError,
    RateLimitError,
    generate_embeddings,
    get_embedding_dimension,
)


def example_single_embedding():
    """Generate embedding for a single text."""
    print("=" * 80)
    print("SINGLE EMBEDDING EXAMPLE")
    print("=" * 80)

    text = "What is the meaning of life?"
    embedding_provider = "openai:text-embedding-3-small"

    try:
        # Generate embedding
        embedding = generate_embeddings(embedding_provider, text)

        # Check dimensions
        dimension = get_embedding_dimension(embedding_provider)

        print(f"\nText: {text}")
        print(f"Provider: {embedding_provider}")
        print(f"Embedding dimension: {dimension}")
        print(f"Actual length: {len(embedding)}")
        print(f"First 5 values: {embedding[:5]}")

    except EmbeddingError as e:
        print(f"Error: {e}")


def example_batch_embeddings():
    """Generate embeddings for multiple texts in a single API call."""
    print("\n" + "=" * 80)
    print("BATCH EMBEDDING EXAMPLE")
    print("=" * 80)

    texts = [
        "What is the meaning of life?",
        "How do I bake a chocolate cake?",
        "Explain quantum physics in simple terms",
        "Write a haiku about programming",
        "What is the capital of France?",
    ]

    embedding_provider = "openai:text-embedding-3-small"

    try:
        # Generate embeddings in batch (more efficient than individual calls)
        embeddings = generate_embeddings(embedding_provider, texts)

        print(f"\nGenerated {len(embeddings)} embeddings")
        print(f"Provider: {embedding_provider}\n")

        for i, (text, embedding) in enumerate(zip(texts, embeddings)):
            print(f"{i+1}. {text[:50]}...")
            print(f"   Dimension: {len(embedding)}")
            print(f"   First 3 values: {embedding[:3]}")

    except RateLimitError as e:
        print(f"Rate limit exceeded: {e}")
        print("Tenacity automatic retry failed. Consider reducing batch size or waiting.")
    except EmbeddingError as e:
        print(f"Error: {e}")


def example_multiple_providers():
    """Compare embeddings from different providers."""
    print("\n" + "=" * 80)
    print("MULTIPLE PROVIDERS EXAMPLE")
    print("=" * 80)

    text = "Machine learning is transforming software development"

    providers = [
        "openai:text-embedding-3-small",
        "openai:text-embedding-3-large",
        "openai:text-embedding-ada-002",
    ]

    print(f"\nText: {text}\n")

    for provider in providers:
        try:
            embedding = generate_embeddings(provider, text)
            dimension = get_embedding_dimension(provider)

            print(f"Provider: {provider}")
            print(f"  Dimension: {dimension}")
            print(f"  First 3 values: {embedding[:3]}\n")

        except EmbeddingError as e:
            print(f"Provider: {provider}")
            print(f"  Error: {e}\n")


def example_error_handling():
    """Demonstrate error handling and retries."""
    print("\n" + "=" * 80)
    print("ERROR HANDLING EXAMPLE")
    print("=" * 80)

    # Invalid provider format
    try:
        generate_embeddings("invalid_format", "test")
    except ValueError as e:
        print(f"\nInvalid format error (expected): {e}")

    # Empty text
    try:
        generate_embeddings("openai:text-embedding-3-small", [])
    except ValueError as e:
        print(f"\nEmpty input error (expected): {e}")

    # Unknown model
    try:
        get_embedding_dimension("openai:unknown-model")
    except ValueError as e:
        print(f"\nUnknown model error (expected): {e}")


def example_postgres_integration():
    """
    Example pattern for PostgresService integration.

    This shows how to use embeddings utility in a PostgresService method.
    """
    print("\n" + "=" * 80)
    print("POSTGRES INTEGRATION PATTERN")
    print("=" * 80)

    print(
        """
# In PostgresService class:

async def generate_and_store_embedding(
    self,
    table_name: str,
    record_id: str,
    text_content: str,
    embedding_provider: str = "openai:text-embedding-3-small"
) -> None:
    '''
    Generate embedding for text content and store in database.

    Args:
        table_name: Table containing the record
        record_id: ID of the record to update
        text_content: Text to embed
        embedding_provider: Provider and model for embeddings
    '''
    from rem.utils.embeddings import generate_embeddings, get_embedding_dimension

    # Generate embedding
    embedding = generate_embeddings(embedding_provider, text_content)

    # Get dimension for vector column
    dimension = get_embedding_dimension(embedding_provider)

    # Ensure vector column exists
    await self.execute(f'''
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS embedding vector({dimension})
    ''')

    # Store embedding
    await self.execute(
        f'''
        UPDATE {table_name}
        SET embedding = $1::vector
        WHERE id = $2
        ''',
        embedding,
        record_id
    )


async def batch_generate_embeddings(
    self,
    table_name: str,
    text_column: str = "content",
    embedding_provider: str = "openai:text-embedding-3-small",
    batch_size: int = 100
) -> None:
    '''
    Generate embeddings for all records in a table (batch processing).

    Args:
        table_name: Table to process
        text_column: Column containing text to embed
        embedding_provider: Provider and model for embeddings
        batch_size: Number of records to process per batch
    '''
    from rem.utils.embeddings import generate_embeddings, get_embedding_dimension

    # Get dimension
    dimension = get_embedding_dimension(embedding_provider)

    # Ensure vector column exists
    await self.execute(f'''
        ALTER TABLE {table_name}
        ADD COLUMN IF NOT EXISTS embedding vector({dimension})
    ''')

    # Get all records without embeddings
    records = await self.fetch_all(f'''
        SELECT id, {text_column}
        FROM {table_name}
        WHERE embedding IS NULL
        LIMIT {batch_size}
    ''')

    if not records:
        return

    # Extract texts and IDs
    texts = [record[text_column] for record in records]
    ids = [record['id'] for record in records]

    # Generate embeddings in batch
    embeddings = generate_embeddings(embedding_provider, texts)

    # Store embeddings
    for record_id, embedding in zip(ids, embeddings):
        await self.execute(
            f'''
            UPDATE {table_name}
            SET embedding = $1::vector
            WHERE id = $2
            ''',
            embedding,
            record_id
        )
"""
    )


if __name__ == "__main__":
    # Run examples
    # NOTE: Requires OPENAI_API_KEY or LLM__OPENAI_API_KEY environment variable

    # Check if API key is available
    import os

    if not (os.getenv("OPENAI_API_KEY") or os.getenv("LLM__OPENAI_API_KEY")):
        print("=" * 80)
        print("SETUP REQUIRED")
        print("=" * 80)
        print("\nTo run these examples, set your OpenAI API key:")
        print("  export OPENAI_API_KEY='sk-...'")
        print("  # OR")
        print("  export LLM__OPENAI_API_KEY='sk-...'")
        print("\nThen run:")
        print("  python embeddings_example.py")
        exit(1)

    # Run examples (comment out if you don't want to make API calls)
    example_single_embedding()
    example_batch_embeddings()
    example_multiple_providers()
    example_error_handling()
    example_postgres_integration()

    print("\n" + "=" * 80)
    print("BEST PRACTICES")
    print("=" * 80)
    print(
        """
1. Batch Processing:
   - Process multiple texts in a single API call (up to 2048 for OpenAI)
   - Reduces API overhead and stays within rate limits (RPM)
   - Example: generate_embeddings(provider, [text1, text2, ...])

2. Rate Limit Handling:
   - Uses tenacity library for automatic exponential backoff (default: 1 retry)
   - Adjust max_retries parameter if needed (default: 1)
   - Monitor your usage and adjust batch_size accordingly
   - Consider implementing a queue for large-scale processing

3. Error Handling:
   - Catch EmbeddingError for general API errors
   - Catch RateLimitError for rate limit specific handling
   - Validate embedding_provider format before batch processing

4. Cost Optimization:
   - OpenAI text-embedding-3-small: $0.02 / 1M tokens
   - OpenAI text-embedding-3-large: $0.13 / 1M tokens
   - Use smaller models unless you need higher accuracy

5. PostgreSQL Integration:
   - Use vector({dimension}) column type with pgvector extension
   - Create indexes: CREATE INDEX ON table USING ivfflat (embedding vector_cosine_ops)
   - For similarity search: ORDER BY embedding <=> query_vector LIMIT 10
"""
    )
