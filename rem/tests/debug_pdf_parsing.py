"""
Debug script to test PDF parsing in isolation.
"""
import sys
import logging
from pathlib import Path

# Add source to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from rem.services.content.providers import DocProvider
from loguru import logger

# Configure logging
logger.remove()
logger.add(sys.stderr, level="DEBUG")

def test_pdf_extraction():
    pdf_path = Path("rem/tests/data/content-examples/pdf/service_contract.pdf")
    if not pdf_path.exists():
        logger.error(f"PDF not found at {pdf_path}")
        return

    logger.info(f"Testing extraction for {pdf_path}")
    content = pdf_path.read_bytes()
    
    provider = DocProvider()
    
    try:
        result = provider.extract(content, {"content_type": "application/pdf"})
        text = result.get("text", "")
        logger.info(f"Extraction successful. extracted {len(text)} characters.")
        logger.debug(f"Preview: {text[:200]}...")
        
        if len(text) == 0:
            logger.warning("Extracted text is empty!")
        
        logger.info(f"Metadata: {result.get('metadata')}")
        
    except Exception as e:
        logger.exception(f"Extraction failed: {e}")

if __name__ == "__main__":
    test_pdf_extraction()
