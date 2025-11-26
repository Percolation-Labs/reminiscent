# Sample PDF Documents

This directory contains sample PDF documents for testing REM's document processing, extraction, and ontology features.

## Document Types

### Legal Documents

1. **nda_agreement.pdf** (70KB)
   - Type: Non-Disclosure Agreement
   - Source: nondisclosureagreement.com
   - Content: Basic confidentiality agreement template
   - Use Cases: Contract analysis, legal document parsing, entity extraction

2. **consulting_agreement.pdf** (110KB)
   - Type: Consulting Agreement
   - Source: Iowa State University Extension
   - Content: Sample consulting services agreement
   - Use Cases: Contract parsing, obligation extraction, party identification

3. **service_contract.pdf** (28KB)
   - Type: Service Contract Template
   - Source: University of Rochester
   - Content: Template for consulting services
   - Use Cases: Contract analysis, terms extraction

### Business Documents

4. **sample_business_plan.pdf** (340KB)
   - Type: Business Plan
   - Source: Oklahoma State University via UVM
   - Content: Food business startup plan example
   - Use Cases: Financial data extraction, business analysis, strategic planning

5. **annual_financial_report.pdf** (96KB)
   - Type: Financial Report
   - Source: California PTA
   - Content: Annual financial statement sample
   - Use Cases: Financial metrics extraction, accounting data parsing

6. **sample_invoice.pdf** (373KB)
   - Type: Invoice
   - Source: WM Access
   - Content: Sample invoice with line items
   - Use Cases: Invoice processing, financial data extraction

### Professional Documents

7. **sample_resume.pdf** (295KB)
   - Type: Resume/CV
   - Source: MSN Labs
   - Content: Professional resume example
   - Use Cases: Candidate screening, skills extraction, experience parsing

8. **sample_research_paper.pdf** (842KB)
   - Type: Academic Research Paper
   - Source: Purdue University Global Writing Center
   - Content: APA format research paper example
   - Use Cases: Academic document processing, citation extraction, abstract analysis

## Usage

### With REM CLI

```bash
# Process all PDFs through file processor
rem process files \
   \
  --directory tests/data/content-examples/pdf

# Run ontology extraction on processed files
rem dreaming custom \
   \
  --extractor cv-parser-v1

# Query extracted data
rem query "SEARCH(type='ontology', query='candidate with Python skills')"
```

### With REM API

```python
from rem.services.fs import FS
from rem.services.file_processor import FileProcessorService

# Upload and process
fs = FS()
processor = FileProcessorService()

for pdf_file in Path("tests/data/content-examples/pdf").glob("*.pdf"):
    # Upload to S3
    uri = await fs.upload(pdf_file, tenant_id="demo")

    # Process file
    await processor.process_file(uri, tenant_id="demo")
```

### With Docker

```bash
# Copy files into container
docker cp tests/data/content-examples/pdf rem-api:/app/tests/data/content-examples/pdf

# Process files
docker exec rem-api rem process files \
   \
  --directory /app/tests/data/content-examples/pdf
```

## Ontology Extractors

These sample documents are designed to work with the following agent schemas:

- **cv-parser-v1** - Extracts candidate information from resumes
- **contract-analyzer-v1** - Analyzes contracts for parties, terms, obligations
- **invoice-parser-v1** - Extracts invoice details, line items, amounts
- **financial-report-analyzer-v1** - Parses financial metrics and statements

See `rem/schemas/ontology_extractors/` for schema definitions.

## Testing Scenarios

### 1. Multi-Document Contract Analysis
```bash
# Process all legal documents
rem process files  --file-pattern "*agreement*.pdf" --extractor contract-analyzer-v1
```

### 2. Candidate Screening
```bash
# Extract candidate data from resumes
rem process files  --file-pattern "*resume*.pdf" --extractor cv-parser-v1
```

### 3. Financial Analysis
```bash
# Process financial documents
rem process files  --file-pattern "*financial*.pdf,*invoice*.pdf" --extractor financial-report-analyzer-v1
```

### 4. Full Pipeline Test
```bash
# Process all documents with dreaming workflow
rem dreaming full  --user-id test-user

# Query results
rem ask "What candidates have we reviewed?"
rem ask "What are the key terms in our NDAs?"
rem ask "What is our total invoiced amount?"
```

## File Metadata

| Filename | Size | Type | Pages | Source Domain |
|----------|------|------|-------|---------------|
| nda_agreement.pdf | 70KB | Legal | ~3 | .com |
| consulting_agreement.pdf | 110KB | Legal | ~5 | .edu |
| service_contract.pdf | 28KB | Legal | ~2 | .edu |
| sample_business_plan.pdf | 340KB | Business | ~15 | .edu |
| annual_financial_report.pdf | 96KB | Financial | ~4 | .org |
| sample_invoice.pdf | 373KB | Financial | ~1 | .com |
| sample_resume.pdf | 295KB | Professional | ~2 | .com |
| sample_research_paper.pdf | 842KB | Academic | ~10 | .edu |

## License & Attribution

These documents are publicly available templates and samples from their respective sources. They are intended for testing and educational purposes only. Not suitable for actual legal or business use.

**Attribution:**
- Iowa State University Extension
- University of Vermont
- Oklahoma State University
- University of Rochester
- Purdue University Global Writing Center
- California PTA
- Various template providers

## Notes

- All documents are **sample/template** data, not real contracts or agreements
- Use for **testing purposes only** - not legal advice or real business documents
- PDFs contain realistic structure and content for training ML models
- File sizes range from 28KB to 842KB for performance testing
- Documents include text, tables, and formatting for comprehensive extraction testing
