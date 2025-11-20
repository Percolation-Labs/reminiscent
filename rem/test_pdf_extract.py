"""Test PDF extraction and chunking (no database)."""

from pathlib import Path

from loguru import logger

from rem.services.content import ContentService
from rem.utils.chunking import chunk_text
from rem.utils.markdown import to_markdown


def test_process_pdf():
    """Test processing a PDF file without database."""
    # PDF to test
    pdf_path = Path("/Users/sirsh/Downloads/01_stock_hotel.pdf")

    logger.info(f"Testing PDF processing: {pdf_path}")

    # Create content service (no repositories)
    service = ContentService()

    # Extract content
    result = service.process_uri(str(pdf_path))

    logger.info(f"Extraction complete:")
    logger.info(f"  Provider: {result['provider']}")
    logger.info(f"  Content length: {len(result['content'])} chars")

    # Convert to markdown
    markdown = to_markdown(result["content"], pdf_path.name)
    logger.info(f"  Markdown length: {len(markdown)} chars")

    # Chunk
    chunks = chunk_text(markdown)
    logger.info(f"  Chunks created: {len(chunks)}")
    logger.info(f"  Avg chunk size: {sum(len(c) for c in chunks) / len(chunks):.0f} chars")

    # Show first chunk
    logger.info(f"\n  First chunk preview:")
    logger.info(f"  {chunks[0][:200]}...")


if __name__ == "__main__":
    test_process_pdf()
