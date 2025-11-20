# ContentService - File Processing System

Event-driven file processing service with pluggable providers for different file formats.

## Overview

ContentService provides a unified interface for processing various file types with support for:
- S3 URI support (`s3://bucket/key`)
- Local file support (`./path/to/file`)
- Provider plugins for different file types
- Extensible via `register_provider()`
- Integration with event-driven processing pipeline

## File Processing Conventions

### S3 Path Structure

When files are uploaded to S3, they follow a strict convention for organization:

```
s3://bucket/uploads/path/to/document.pdf          # Original uploaded file
s3://bucket/parsed/path/to/document-pdf/          # Parsed artifacts directory
  ├── document.pdf.parsed.md                      # Structured markdown output
  ├── document.pdf.meta.yaml                      # Extraction metadata
  └── artifacts/                                  # Extracted artifacts
      ├── images/                                 # Extracted images
      │   ├── page-1-img-0.png
      │   ├── page-2-img-1.jpg
      │   └── ...
      └── tables/                                 # Extracted tables
          ├── table-0.csv
          ├── table-0.png                         # Cropped table image
          ├── table-1.csv
          └── ...
```

### Path Mapping Convention

The parsed path mirrors the upload path with two changes:
1. Replace `/uploads/` prefix with `/parsed/`
2. Use filename with extension as directory name (dots converted to hyphens)

**Examples:**
```
uploads/docs/report.pdf          → parsed/docs/report-pdf/
uploads/data/sheet.xlsx          → parsed/data/sheet-xlsx/
uploads/user/123/invoice.pdf     → parsed/user/123/invoice-pdf/
```

### Output File Formats

#### 1. Structured Markdown (`.parsed.md`)

All documents are converted to structured markdown before chunking and embedding. This provides:
- Consistent format for downstream processing
- Preserves document structure (headings, lists, tables)
- Human-readable intermediate representation
- Easy to version control and diff

**Example structure:**
```markdown
# Document Title

## Metadata
- **Source**: report.pdf
- **Pages**: 42
- **Extracted**: 2025-01-15T10:30:00Z
- **Parser**: kreuzberg
- **Language**: en (0.98 confidence)

## Content

Lorem ipsum dolor sit amet...

### Section 1

Content with **formatting** preserved.

### Tables

See [Table 1](artifacts/tables/table-0.csv) - Financial Summary

### Images

![Diagram 1](artifacts/images/page-5-img-0.png)
```

#### 2. Metadata YAML (`.meta.yaml`)

Comprehensive extraction metadata in YAML format for downstream processing:

```yaml
# Source file metadata
source:
  uri: s3://bucket/uploads/docs/report.pdf
  filename: report.pdf
  size_bytes: 2456789
  content_type: application/pdf
  uploaded_at: "2025-01-15T10:25:00Z"
  etag: "abc123..."

# Extraction metadata
extraction:
  parser: kreuzberg
  parser_version: "3.21.0"
  extracted_at: "2025-01-15T10:30:00Z"
  processing_time_seconds: 45.2
  config:
    extract_tables: true
    extract_images: true
    force_ocr: false

# Document metadata
document:
  page_count: 42
  word_count: 8542
  char_count: 52341
  detected_language: en
  language_confidence: 0.98
  document_type: report
  document_type_confidence: 0.87

# Extracted artifacts
artifacts:
  tables:
    - id: table-0
      page: 5
      rows: 12
      columns: 6
      file: artifacts/tables/table-0.csv
      image: artifacts/tables/table-0.png
      confidence: 0.92
    - id: table-1
      page: 18
      rows: 8
      columns: 4
      file: artifacts/tables/table-1.csv
      image: artifacts/tables/table-1.png
      confidence: 0.88

  images:
    - id: img-0
      page: 3
      file: artifacts/images/page-3-img-0.png
      width: 1200
      height: 800
      format: png
      ocr_applied: false
    - id: img-1
      page: 12
      file: artifacts/images/page-12-img-1.jpg
      width: 800
      height: 600
      format: jpeg
      ocr_applied: true
      ocr_text: "Extracted text from image..."

# Quality metrics
quality:
  overall_score: 0.94
  ocr_required: false
  warnings: []

# Chunking metadata (added after embedding)
chunking:
  strategy: semantic
  chunk_count: 156
  avg_chunk_size: 512
  overlap_tokens: 50
```

### Processing Pipeline

```
1. Upload to S3
   └─> uploads/docs/report.pdf

2. S3 Event → SQS → Worker Pod
   └─> ContentService.process_uri()

3. Extract with Kreuzberg
   ├─> Text content
   ├─> Tables (CSV + images)
   ├─> Images (PNG/JPEG)
   └─> Metadata

4. Generate structured outputs
   ├─> Convert to markdown
   ├─> Save artifacts to S3
   └─> Generate meta.yaml

5. Write to S3 parsed directory
   └─> parsed/docs/report-pdf/
       ├── report.pdf.parsed.md
       ├── report.pdf.meta.yaml
       └── artifacts/
           ├── images/
           └── tables/

6. Chunk and embed markdown
   └─> PostgreSQL + pgvector (as Resources)

7. Create graph edges
   └─> Link Resources to User, Files, Moments
```

### Why This Convention?

**Separation of concerns:**
- `/uploads/` - Raw user-uploaded files (immutable)
- `/parsed/` - Processed, structured outputs (reproducible)

**Artifact organization:**
- Keeps all related files together in one directory
- Easy to reference artifacts from markdown
- Preserves relative paths for portability
- Simple to delete all artifacts for a document

**Structured markdown:**
- Single format for all document types
- Consistent chunking and embedding strategy
- Easier to build RAG context
- Human-readable for debugging

**Metadata tracking:**
- Complete audit trail of processing
- Reproducible extraction (config stored)
- Quality metrics for filtering
- Artifact registry for lookup

## Architecture

```
User uploads file
       ↓
S3: s3://rem/uploads/docs/report.pdf
       ↓ (S3 ObjectCreated event)
SQS: rem-file-processing queue
       ↓ (KEDA monitors queue depth)
K8s Deployment: file-processor (0-20 pods)
       ↓ (SQSFileProcessor worker)
ContentService.process_uri()
       ↓ (Kreuzberg DocProvider)
Extract: text + tables + images + metadata
       ↓
Generate structured outputs:
  - report.pdf.parsed.md (markdown)
  - report.pdf.meta.yaml (metadata)
  - artifacts/images/*.png
  - artifacts/tables/*.csv
       ↓
S3: s3://rem/parsed/docs/report-pdf/
       ↓ (TODO: chunking + embedding)
PostgreSQL + pgvector (as Resources)
       ↓ (TODO: graph edges)
Link to User, File entities
```

## Quick Start

### Basic Usage

```python
from rem.services.content import ContentService

service = ContentService()

# Process local file
result = service.process_uri("./README.md")

# Process S3 file
result = service.process_uri("s3://rem/uploads/doc.md")

print(result["content"])  # Extracted text
print(result["metadata"])  # File metadata
print(result["provider"])  # "markdown"
```

### CLI Usage

```bash
# Process local file
rem process uri ./README.md

# Process S3 file
rem process uri s3://rem/uploads/document.md

# Save to file
rem process uri s3://rem/uploads/doc.md -s output.json

# Text-only output
rem process uri ./file.md -o text
```

## Supported File Formats

### Currently Supported

#### Markdown (`.md`, `.markdown`)
- **Provider**: `TextProvider`
- **Capabilities**: UTF-8 text extraction, heading analysis, line/char counts
- **Use case**: Documentation, notes, structured text

#### PDF (`.pdf`)
- **Provider**: `DocProvider` (powered by Kreuzberg)
- **Capabilities**:
  - Text extraction with OCR fallback (Tesseract)
  - Intelligent table detection and reconstruction
  - Multi-format support (native PDF, scanned, password-protected)
  - Daemon-safe subprocess workaround for ASGI servers
  - Configurable accuracy thresholds
- **Use case**: Documents, reports, forms, scanned papers

#### Audio (`.wav`, `.mp3`, `.m4a`, `.flac`, `.ogg`)
- **Provider**: `AudioProvider` (powered by OpenAI Whisper)
- **Capabilities**:
  - Speech-to-text transcription
  - Automatic silence-based chunking
  - Markdown-formatted output with timestamps
  - Cost estimation ($0.006/minute)
- **Use case**: Meeting recordings, interviews, podcasts, voice memos

#### Images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`)
- **Provider**: `ImageProvider` (vision LLM + CLIP embeddings)
- **Capabilities**:
  - **Tier-based vision analysis**: Gold tier users always get vision LLM descriptions
  - **Sampling-based analysis**: Non-gold users get analysis based on sample rate (0.0-1.0)
  - **Multi-provider support**: Anthropic Claude, Google Gemini, OpenAI GPT-4o
  - **Metadata extraction**: Image dimensions, format detection
  - **Markdown descriptions**: Vision LLM generates detailed markdown descriptions
  - **CLIP embeddings**: Semantic image search with Jina AI (512/768-dim vectors)
  - **Graceful degradation**: Falls back when API keys unavailable
- **Use case**: Screenshots, diagrams, charts, photos, scanned images
- **Configuration**:
  - Vision LLM (expensive, tier/sample-gated):
    - `CONTENT__IMAGE_VLLM_SAMPLE_RATE`: Sampling rate (0.0 = never, 1.0 = always)
    - `CONTENT__IMAGE_VLLM_PROVIDER`: Provider (anthropic, gemini, openai)
    - `CONTENT__IMAGE_VLLM_MODEL`: Model name (optional, uses provider default)
  - CLIP Embeddings (cheap, always-on when key provided):
    - `CONTENT__CLIP_PROVIDER`: Provider (jina for API, self-hosted for future, default: jina)
    - `CONTENT__CLIP_MODEL`: Model (jina-clip-v1 or jina-clip-v2, default: v2)
    - `CONTENT__JINA_API_KEY`: Jina AI API key (get free key at https://jina.ai/embeddings/)
- **Storage**: Saves to `ImageResource` table (separate from regular `Resource`)
- **Pricing**:
  - Vision LLM: ~$0.01-0.05 per image (varies by provider)
  - CLIP: ~$0.02 per million tokens (~4K tokens per 512x512 image = $0.00008/image)
  - Free tier: 10M CLIP tokens (~2,500 images)

### Planned Support (via Kreuzberg)

Kreuzberg supports 50+ file formats. Easy to add via provider pattern:

#### Documents & Productivity
- **Word**: `.docx`, `.doc` - Microsoft Word documents
- **Excel**: `.xlsx`, `.xls`, `.ods` - Spreadsheets with table extraction
- **PowerPoint**: `.pptx`, `.ppt` - Presentations
- **Rich Text**: `.rtf` - Formatted text documents
- **EPUB**: Digital books

#### Structured Data
- **Web**: `.html`, `.xml` - Web pages and markup
- **Data**: `.json`, `.yaml`, `.toml` - Configuration and data files

#### Academic & Technical
- **LaTeX**: `.tex`, `.bib` - Academic papers and bibliographies
- **Jupyter**: `.ipynb` - Notebooks with code and outputs
- **Markup**: `.rst`, `.org` - reStructuredText, Org Mode
- **Markdown variants**: Enhanced markdown processing

#### Communication
- **Email**: `.eml`, `.msg` - Email messages with attachments

#### Archives
- **Compressed**: `.zip`, `.tar`, `.gz`, `.7z` - Extract and process contents

## Kreuzberg Document Intelligence

### What is Kreuzberg?

Kreuzberg is a polyglot document processing system with a Rust core that extracts text, metadata, and structured information from documents. It provides:

- **50+ file format support** - PDFs, Office docs, images, HTML, XML, archives, email, and more
- **OCR with table extraction** - Multiple backends (Tesseract, EasyOCR, PaddleOCR)
- **Intelligent table detection** - Reconstructs table structure with configurable thresholds
- **Batch processing** - Concurrent document handling with automatic resource management
- **Memory efficiency** - Streaming parsers handle multi-GB files with constant memory
- **Language detection** - Automatic detection with confidence thresholds
- **Metadata extraction** - Authors, titles, dates, page counts, EXIF, format-specific props

### ExtractionConfig Options

Kreuzberg's `ExtractionConfig` provides fine-grained control over extraction:

```python
from kreuzberg import ExtractionConfig, GMFTConfig

config = ExtractionConfig(
    # Table extraction
    extract_tables=True,                    # Enable table detection
    extract_tables_from_ocr=False,          # Extract tables from OCR images
    gmft_config=GMFTConfig(
        detector_base_threshold=0.85,       # Detection confidence threshold
        enable_multi_header=True,           # Support multi-row headers
        remove_null_rows=True,              # Clean up empty rows
    ),

    # Image extraction
    extract_images=True,                    # Extract embedded images
    deduplicate_images=True,                # Remove duplicate images
    ocr_extracted_images=False,             # Run OCR on extracted images
    image_ocr_min_dimensions=(50, 50),      # Min image size for OCR
    image_ocr_max_dimensions=(10000, 10000),# Max image size for OCR

    # OCR configuration
    force_ocr=False,                        # Force OCR even for native text
    ocr_backend='tesseract',                # 'tesseract', 'paddle', 'easyocr'

    # Content processing
    chunk_content=False,                    # Enable semantic chunking
    max_chars=2000,                         # Max chars per chunk
    max_overlap=100,                        # Overlap between chunks

    # Entity extraction
    extract_entities=False,                 # Extract named entities
    extract_keywords=False,                 # Extract keywords
    keyword_count=10,                       # Number of keywords to extract

    # Language detection
    auto_detect_language=False,             # Auto-detect document language
    language_detection_model='auto',        # 'lite', 'full', 'auto'

    # Document classification
    auto_detect_document_type=False,        # Classify document type
    document_type_confidence_threshold=0.5, # Min confidence threshold

    # Quality processing
    enable_quality_processing=True,         # Enable quality assessment

    # PDF-specific
    pdf_password='',                        # Password for encrypted PDFs
    target_dpi=150,                         # Target DPI for rendering
    auto_adjust_dpi=True,                   # Auto-adjust DPI for large pages

    # HTML/JSON-specific
    html_to_markdown_config=None,           # HTML→Markdown options
    json_config=None,                       # JSON extraction options

    # Performance
    use_cache=True,                         # Enable extraction cache
)
```

### Extraction Result Structure

Kreuzberg returns a rich result object with comprehensive metadata:

```python
from kreuzberg import extract_file_sync
from pathlib import Path

result = extract_file_sync(Path("document.pdf"), config=config)

# Core content
result.content                    # str: Full extracted text
result.mime_type                  # str: Detected MIME type

# Tables (list of dicts)
for table in result.tables:
    table['page_number']          # int: Source page
    table['text']                 # str: Table as markdown/text
    table['df']                   # pandas.DataFrame: Structured data
    table['cropped_image']        # PIL.Image: Cropped table image

# Images (list of dicts)
for img in result.images:
    img['page']                   # int: Source page
    img['image']                  # PIL.Image: Image data
    img['width'], img['height']   # int: Dimensions
    img['format']                 # str: Image format

# Document metadata
result.metadata = {
    'page_count': int,            # Number of pages
    'author': str,                # Document author
    'title': str,                 # Document title
    'creation_date': str,         # ISO8601 timestamp
    'modification_date': str,     # ISO8601 timestamp
    'summary': str,               # Auto-generated summary
    'quality_score': float,       # 0.0-1.0 quality metric
}

# Language detection
result.detected_languages = [
    {'language': 'en', 'confidence': 0.98},
    {'language': 'es', 'confidence': 0.02},
]

# Document classification
result.document_type              # str: 'report', 'invoice', etc.
result.document_type_confidence   # float: 0.0-1.0

# Entity extraction (if enabled)
result.entities = {
    'PERSON': ['John Doe', 'Jane Smith'],
    'ORG': ['Acme Corp', 'TechCo'],
    'GPE': ['New York', 'London'],
    'DATE': ['2025-01-15', '2024-12-31'],
}

# Keywords (if enabled)
result.keywords = ['machine learning', 'artificial intelligence', ...]

# Chunks (if chunk_content=True)
result.chunks = [
    {'text': '...', 'start': 0, 'end': 2000},
    {'text': '...', 'start': 1900, 'end': 3900},
]

# OCR results (if OCR was applied)
result.image_ocr_results = [...]

# Layout information
result.layout                     # Document layout structure

# Utility methods
result.to_dict()                  # Convert to dict for serialization
result.to_markdown()              # Convert to markdown format
result.export_tables_to_csv(dir) # Export all tables to CSV files
result.export_tables_to_tsv(dir) # Export all tables to TSV files
result.get_table_summaries()      # Get summaries of all tables
```

### Daemon Process Workaround

When running in ASGI servers (Hypercorn, Uvicorn), Kreuzberg's ProcessPoolExecutor may fail due to daemon restrictions. Our `DocProvider` implements a subprocess workaround:

```python
def _is_daemon_process(self) -> bool:
    """Check if running in a daemon process."""
    try:
        return multiprocessing.current_process().daemon
    except Exception:
        return False

def _parse_in_subprocess(self, file_path: Path) -> dict:
    """Run kreuzberg in a separate subprocess to bypass daemon restrictions."""
    # Executes parsing in isolated subprocess
    # Serializes config and result as JSON
    # 5 minute timeout for large documents
```

This pattern ensures reliable parsing in production deployments.

## Provider Configuration

### Default Provider Settings

Providers are configured via `ContentSettings` in `settings.py`:

```python
from rem.settings import settings

# View default supported types
print(settings.content.supported_text_types)
# [".txt", ".md", ".json", ".yaml", ".py", ".js", ...]

print(settings.content.supported_doc_types)
# [".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ...]

print(settings.content.supported_audio_types)
# [".wav", ".mp3", ".m4a", ".flac", ".ogg"]
```

### Environment Variable Overrides

You can override the default extension lists via environment variables:

```bash
# Override document types to only support PDFs
export CONTENT__SUPPORTED_DOC_TYPES=".pdf"

# Override text types to only support markdown and Python
export CONTENT__SUPPORTED_TEXT_TYPES=".md,.py"

# Override audio types to only support WAV
export CONTENT__SUPPORTED_AUDIO_TYPES=".wav"

# Disable audio transcription in development
export CONTENT__SUPPORTED_AUDIO_TYPES=""
```

### Benefits of Settings-Based Configuration

1. **No Long Lists** - Extension lists defined in one place (settings.py)
2. **Environment Override** - Easy configuration via env vars
3. **Clean Code** - ContentService.__init__() is concise
4. **Testable** - Settings can be mocked/overridden in tests
5. **DRY** - Single source of truth for supported file types

## Provider Plugin System

You can register custom providers to either:
1. **Add support for new file types** (e.g., `.epub`, `.rtf`)
2. **Override default providers** for specific formats (e.g., use PyMuPDF instead of Kreuzberg for PDFs)

### Example: Custom Provider for New File Type

```python
from rem.services.content import ContentService
from rem.services.content.providers import ContentProvider

class EpubProvider(ContentProvider):
    @property
    def name(self) -> str:
        return "epub"

    def extract(self, content: bytes, metadata: dict) -> dict:
        # Use ebooklib or other EPUB parser
        text = extract_text_from_epub(content)
        return {
            "text": text,
            "metadata": {
                "chapters": 12,
                "author": "...",
            }
        }

# Register for new file type
service = ContentService()
service.register_provider([".epub"], EpubProvider())
```

### Example: Override Default Provider

**Note**: This is a hypothetical example. The default `DocProvider` already handles PDFs well via Kreuzberg.

```python
# Hypothetical: Override DocProvider with custom PDF parser
class CustomPDFProvider(ContentProvider):
    @property
    def name(self) -> str:
        return "custom_pdf"

    def extract(self, content: bytes, metadata: dict) -> dict:
        # Use PyMuPDF, pdfplumber, or other library instead of Kreuzberg
        text = extract_text_with_pymupdf(content)
        return {
            "text": text,
            "metadata": {"parser": "pymupdf"}
        }

# Override .pdf extension to use custom provider instead of DocProvider
service = ContentService()
service.register_provider([".pdf"], CustomPDFProvider())
```

### Provider Interface

All providers must implement:

```python
class ContentProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., 'markdown', 'pdf')."""
        pass

    @abstractmethod
    def extract(self, content: bytes, metadata: dict) -> dict:
        """
        Extract content from file bytes.

        Args:
            content: Raw file bytes
            metadata: File metadata (size, mime_type, etc.)

        Returns:
            Dict with 'text' and optional 'metadata' fields
        """
        pass
```

## Event-Driven Processing

### SQS Worker

Background worker that consumes S3 events from SQS queue.

**Features:**
- Long polling (20s) for efficient SQS usage
- Graceful shutdown (SIGTERM/SIGINT)
- Batch processing (up to 10 messages)
- DLQ support (3 retries)
- IRSA authentication (no credentials in code)

**Entry point:**
```bash
python -m rem.workers.sqs_file_processor
```

### K8s Deployment

Production deployment with KEDA autoscaling at `manifests/application/file-processor/`

**Scaling Example:**
- 0 messages → 0 pods (scale to zero)
- 25 messages → 3 pods
- 100 messages → 10 pods
- 250 messages → 20 pods (max)

## Configuration

### Environment Variables

```bash
# .env or K8s ConfigMap
SQS__QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/rem-file-processing
SQS__REGION=us-east-1
SQS__MAX_MESSAGES=10
SQS__WAIT_TIME_SECONDS=20
SQS__VISIBILITY_TIMEOUT=300

S3__BUCKET_NAME=rem
S3__REGION=us-east-1
```

### IRSA Permissions

Worker pods need two IAM roles:

1. **KEDA operator role** - Read SQS metrics
   ```
   sqs:GetQueueAttributes
   sqs:ListQueues
   ```

2. **File processor role** - Consume queue + read S3
   ```
   sqs:ReceiveMessage
   sqs:DeleteMessage
   sqs:ChangeMessageVisibility
   s3:GetObject
   ```

## Local Development

### Test ContentService

```bash
cd rem
uv pip install -e .

# Test with local file
echo "# Test Document" > test.md
python -c "from rem.services.content import ContentService; \
           print(ContentService().process_uri('test.md'))"
```

### Test CLI

```bash
# Test with local file
rem process uri test.md

# Test with S3 (requires AWS credentials or IRSA)
aws s3 cp test.md s3://rem/uploads/
rem process uri s3://rem/uploads/test.md
```

### Test Worker

```bash
# Set environment variables
export SQS__QUEUE_URL=https://sqs.us-east-1.amazonaws.com/ACCOUNT_ID/rem-file-processing
export SQS__REGION=us-east-1
export S3__BUCKET_NAME=rem
export S3__REGION=us-east-1

# Run worker
python -m rem.workers.sqs_file_processor

# Upload test file (in another terminal)
aws s3 cp test.md s3://rem/uploads/

# Watch worker logs process the file
```

## Production Deployment

### 1. Build and push Docker image

```bash
cd rem
docker build -f Dockerfile.worker -t your-registry/rem:latest .
docker push your-registry/rem:latest
```

### 2. Deploy infrastructure (Pulumi)

```bash
cd ../manifests/infra/file-queue
pulumi up
# Note queue URL and IAM policy ARNs
```

### 3. Deploy KEDA platform

```bash
cd ../../platform/keda
kubectl apply -f application.yaml
```

### 4. Configure IRSA roles

```bash
# Annotate KEDA operator ServiceAccount
kubectl annotate sa keda-operator -n keda \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT_ID:role/keda-operator-role
```

### 5. Deploy file processor

```bash
cd ../../application/file-processor

# Update ACCOUNT_ID in deployment.yaml and keda-scaledobject.yaml
sed -i 's/ACCOUNT_ID/123456789012/g' *.yaml

kubectl apply -f .
```

### 6. Verify scaling

```bash
# Should start at 0 pods
kubectl get pods -l app=file-processor

# Upload test files
for i in {1..25}; do
  echo "test $i" | aws s3 cp - s3://rem/uploads/test-$i.md
done

# Watch scale up to 3 pods
kubectl get pods -l app=file-processor -w

# Watch HPA
kubectl get hpa file-processor-scaler -w
```

## Cost Optimization

- **Scale to zero**: No cost when idle
- **Spot instances**: 70-90% savings (configured in Deployment affinity)
- **Long polling**: Reduces SQS API calls
- **Batch processing**: Up to 10 messages per receive
- **KEDA efficiency**: Only scales when needed

**Monthly cost estimate** (us-east-1, assuming 10k files/day):
- SQS: ~$1 (requests + data transfer)
- S3 storage: ~$5 (100 GB)
- Compute: ~$10 (spot instances, avg 2 pods)
- **Total: ~$16/month**

## Future Enhancements

### Short Term
- [ ] PDF support (PyMuPDF/pdfplumber provider)
- [ ] PostgreSQL storage integration
- [ ] Embedding generation (OpenAI/local models)
- [ ] Graph edge creation

### Medium Term
- [ ] HTML/web page extraction
- [ ] DOCX/Office formats
- [ ] Image OCR (Tesseract/cloud OCR)
- [ ] Chunking strategies for large documents

### Long Term
- [ ] Video transcription
- [ ] Audio processing
- [ ] Custom ML model inference
- [ ] Multi-language support

## Monitoring

### CloudWatch Metrics

- **Queue depth**: `ApproximateNumberOfMessagesVisible`
- **Processing rate**: Messages per second
- **DLQ depth**: Failed messages
- **Pod count**: Kubernetes metrics

### Logs

```bash
# Worker logs
kubectl logs -l app=file-processor -f

# KEDA scaling events
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=100
```

### Alerts

- Queue depth > 100 for 5+ minutes (backlog)
- DLQ depth > 0 (processing failures)
- Pod crash loops (worker errors)

## Troubleshooting

### Pods not scaling

```bash
# Check ScaledObject
kubectl describe scaledobject file-processor-scaler

# Check KEDA logs
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=50
```

### Access Denied errors

```bash
# Verify IRSA annotation
kubectl get sa file-processor -o yaml | grep role-arn

# Check pod environment
kubectl get pod -l app=file-processor -o yaml | grep -A5 env:
```

### Messages not being processed

```bash
# Check queue has messages
aws sqs get-queue-attributes \
  --queue-url QUEUE_URL \
  --attribute-names ApproximateNumberOfMessages

# Check worker logs
kubectl logs -l app=file-processor --tail=100
```

## See Also

- Architecture: `/CLAUDE.md`
- FS Service: `rem/src/rem/services/fs/` - Unified S3/local file operations
- Settings: `rem/settings.py` - S3Settings, SQSSettings configuration
- Infrastructure: `manifests/infra/file-queue/README.md`
- KEDA: `manifests/platform/keda/README.md`
- Deployment: `manifests/application/file-processor/README.md`
