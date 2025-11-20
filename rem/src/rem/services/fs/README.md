# REM File System Service

Unified file system abstraction for S3 and local storage with format detection and Polars integration.

## Features

- **Unified Interface**: Seamless operations across S3 and local filesystems
- **Format Detection**: Automatic reader/writer selection based on file extensions
- **Polars First**: Columnar data operations using Polars (with Pandas fallback)
- **Presigned URLs**: Generate S3 presigned URLs for direct access
- **ContentService Integration**: Pluggable content providers for specialized formats
- **Type Safety**: Full Pydantic validation for S3 metadata

## Installation

```bash
# Core dependencies (already in main dependencies)
uv add boto3 pyyaml

# File system extras
uv add --optional fs polars pillow

# Or install individually
uv add polars pillow
```

## Quick Start

```python
from rem.services.fs import FS, generate_presigned_url

fs = FS()

# Read from S3 or local - same interface
df = fs.read("s3://bucket/data.parquet")
df = fs.read("/local/path/data.csv", use_polars=True)

# Write with automatic format detection
fs.write("s3://bucket/output.json", {"key": "value"})
fs.write("/tmp/data.parquet", dataframe)

# Copy between filesystems
fs.copy("s3://bucket/file.pdf", "/tmp/local.pdf")  # Download
fs.copy("/local/image.png", "s3://bucket/image.png")  # Upload

# List files
files = fs.ls("s3://bucket/prefix/")
dirs = fs.ls_dirs("s3://bucket/")

# Generate presigned URLs
url = generate_presigned_url("s3://bucket/file.pdf", expiry=3600)
upload_url = generate_presigned_url("s3://bucket/new.pdf", for_upload=True)
```

## Supported Formats

### Columnar Data (Polars/Pandas)
- **CSV** (`.csv`) - `pl.read_csv()` / `pl.write_csv()`
- **Parquet** (`.parquet`) - `pl.read_parquet()` / `pl.write_parquet()`
- **Feather** (`.feather`) - `pl.read_feather()` / `pl.write_feather()`

### Structured Data
- **JSON** (`.json`) - Python dict serialization
- **YAML** (`.yml`, `.yaml`) - PyYAML integration

### Documents
- **Text** (`.txt`, `.md`, `.log`) - UTF-8 text
- **PDF** (`.pdf`) - TODO: ContentService integration
- **DOCX** (`.docx`) - TODO: python-docx provider
- **HTML** (`.html`) - Raw HTML read/write

### Images (Pillow)
- **PNG** (`.png`)
- **JPEG** (`.jpg`, `.jpeg`)
- **TIFF** (`.tiff`, `.tif`)
- **SVG** (`.svg`) - Read as text

### Spreadsheets
- **Excel** (`.xlsx`, `.xls`) - TODO: Add `openpyxl`/`xlrd` to dependencies

### Audio
- **WAV** (`.wav`) - TODO: Add `librosa` or `pydub` provider
- **MP3** (`.mp3`) - TODO: Audio processing library
- **FLAC** (`.flac`) - TODO: Audio processing library

### Binary
- **Pickle** (`.pickle`) - Python pickle serialization

## Configuration

Uses REM settings from `.env`:

```bash
# S3 Settings (rem/settings.py -> S3Settings)
S3__BUCKET_NAME=rem-storage
S3__REGION=us-east-1

# For local dev (MinIO)
S3__ENDPOINT_URL=http://localhost:9000
S3__ACCESS_KEY_ID=minioadmin
S3__SECRET_ACCESS_KEY=minioadmin
S3__USE_SSL=false

# For production (IRSA in EKS)
# No access keys needed - uses IAM role
```

## Architecture

```
FS (facade)
├── S3Provider
│   ├── boto3 client (from settings)
│   ├── Format detection
│   ├── Presigned URLs
│   └── Multipart uploads (TODO)
└── LocalProvider
    ├── pathlib operations
    ├── Format detection
    └── Same interface as S3Provider
```

## Design Principles

1. **No upload/download methods** - Use `copy(from, to)` instead
2. **No zip/unzip methods** - Use archive formats with `copy()`
3. **Extension-based format detection** - Automatic reader/writer selection
4. **DRY** - Shared format handling between S3 and local
5. **Lean implementation** - Stubs/TODOs for heavy dependencies

## API Reference

### Core Operations

#### `fs.read(uri, use_polars=True, **options) -> Any`
Read file with automatic format detection.

```python
# Columnar data (returns Polars DataFrame by default)
df = fs.read("s3://bucket/data.csv")
df = fs.read("s3://bucket/data.parquet", use_polars=False)  # Pandas

# Structured data
config = fs.read("s3://bucket/config.yaml")
data = fs.read("s3://bucket/data.json")

# Images
img = fs.read("s3://bucket/image.png")  # PIL Image

# Text
content = fs.read("s3://bucket/readme.md")
```

#### `fs.write(uri, data, **options)`
Write file with automatic format detection.

```python
# Columnar data
fs.write("s3://bucket/output.csv", polars_df)
fs.write("s3://bucket/output.parquet", pandas_df)

# Structured data
fs.write("s3://bucket/config.yaml", {"key": "value"})
fs.write("s3://bucket/data.json", {"data": [1, 2, 3]})

# Images
fs.write("s3://bucket/image.png", pil_image, dpi=300)

# Text
fs.write("s3://bucket/output.txt", "Hello, world!")
```

#### `fs.copy(uri_from, uri_to)`
Copy between filesystems.

```python
# S3 to S3
fs.copy("s3://bucket1/file.csv", "s3://bucket2/file.csv")

# Download
fs.copy("s3://bucket/file.pdf", "/tmp/file.pdf")

# Upload
fs.copy("/local/file.png", "s3://bucket/images/file.png")

# Local to local
fs.copy("/src/file.txt", "/dst/file.txt")
```

#### `fs.ls(uri, **options) -> list[str]`
List files recursively.

```python
# S3
files = fs.ls("s3://bucket/prefix/")
# [
#   "s3://bucket/prefix/file1.csv",
#   "s3://bucket/prefix/subdir/file2.json",
# ]

# Local
files = fs.ls("/path/to/dir/")
```

#### `fs.ls_dirs(uri, **options) -> list[str]`
List immediate child directories.

```python
dirs = fs.ls_dirs("s3://bucket/")
# [
#   "s3://bucket/data",
#   "s3://bucket/models",
# ]
```

#### `fs.exists(uri) -> bool`
Check if file/directory exists.

```python
if fs.exists("s3://bucket/file.csv"):
    df = fs.read("s3://bucket/file.csv")
```

#### `fs.delete(uri, limit=100) -> list[str]`
Delete file or directory contents (with safety limit).

```python
deleted = fs.delete("s3://bucket/old_data/", limit=50)
```

### Advanced Operations

#### `fs.read_dataset(uri) -> pyarrow.Dataset`
Read as PyArrow dataset for lazy loading.

```python
dataset = fs.read_dataset("s3://bucket/partitioned.parquet")
```

#### `fs.read_image(uri) -> PIL.Image`
Read image explicitly.

```python
img = fs.read_image("s3://bucket/photo.jpg")
img.show()
```

#### `fs.apply(uri, fn) -> Any`
Apply function to file (downloads to /tmp if S3).

```python
def process_image(path):
    from PIL import Image
    img = Image.open(path)
    return img.size

width, height = fs.apply("s3://bucket/image.png", process_image)
```

#### `fs.local_file(uri) -> str`
Get local path (downloads from S3 if needed).

```python
local_path = fs.local_file("s3://bucket/model.pkl")
# Returns: "/tmp/model.pkl"
```

#### `generate_presigned_url(url, expiry=3600, for_upload=False) -> str`
Generate S3 presigned URL.

```python
# Download URL (expires in 1 hour)
download_url = generate_presigned_url("s3://bucket/file.pdf")

# Upload URL
upload_url = generate_presigned_url(
    "s3://bucket/upload.pdf",
    expiry=300,  # 5 minutes
    for_upload=True
)
```

## ContentService Integration

For specialized document parsing (PDF, DOCX, etc.), use `ContentService`:

```python
from rem.services.content import ContentService

content_service = ContentService()

# Process PDF with OCR, layout detection, etc.
result = content_service.process_uri("s3://bucket/document.pdf")
# {
#   "uri": "s3://bucket/document.pdf",
#   "content": "Extracted text...",
#   "metadata": {...},
#   "provider": "pdf"
# }
```

The `ContentService` provides pluggable providers for complex formats that require specialized parsing.

## Parsing Hooks

Manage parsed file versions with clean separation from uploads. When you upload a PDF, what you really care about is the structured markdown + extracted images/tables. The FS provider maps uploads to parsed content deterministically.

### Convention

Separate `uploads/` and `parsed/` directories with deterministic path mapping:

```
# S3 paths
s3://rem-io-staging/v1/uploads/user-123/2025/01/19/report.pdf              # Original
s3://rem-io-staging/v1/parsed/user-123/2025/01/19/report.pdf/              # Parsed directory
  ├── content.md                                                           # Primary content
  ├── metadata.json                                                        # Parse metadata
  ├── images/page_1.png                                                    # Extracted images
  └── tables/table_0.parquet                                               # Extracted tables

# Local paths
~/.rem/fs/v1/uploads/user-123/2025/01/19/report.pdf                       # Original
~/.rem/fs/v1/parsed/user-123/2025/01/19/report.pdf/                       # Parsed directory
  ├── content.md
  ├── metadata.json
  ├── images/page_1.png
  └── tables/table_0.parquet
```

### Configuration

Control paths via environment variables:

```bash
# S3 Settings
S3__BUCKET_NAME=rem-io-staging
S3__VERSION=v1
S3__UPLOADS_PREFIX=uploads
S3__PARSED_PREFIX=parsed
```

### Basic Usage

```python
from rem.services.fs import FS

fs = FS()
upload_uri = "s3://rem-io-staging/v1/uploads/user-123/2025/01/19/report.pdf"

# Check if already parsed
if fs.has_parsed(upload_uri):
    markdown = fs.read_parsed(upload_uri)
else:
    # Parse and cache
    result = parse_file(upload_uri)
    fs.write_parsed(
        upload_uri,
        result.markdown,
        metadata={"provider": "kreuzberg", "page_count": 10}
    )
    # Writes to: s3://rem-io-staging/v1/parsed/user-123/2025/01/19/report.pdf/content.md

# List all parsed resources
resources = fs.list_parsed_resources(upload_uri)
# ['content.md', 'metadata.json', 'images/page_1.png', 'tables/table_0.parquet']

# Read specific resources
metadata = fs.read_parsed(upload_uri, "metadata.json")
image = fs.read_parsed(upload_uri, "images/page_1.png")
table = fs.read_parsed(upload_uri, "tables/table_0.parquet")
```

### Benefits

- **Separation of concerns**: Uploads and parsed content in separate directories
- **Deterministic mapping**: uploads/user/date/file.pdf -> parsed/user/date/file.pdf/
- **Caching**: Check `has_parsed()` before re-parsing expensive files
- **Discoverability**: `list_parsed_resources()` shows what's available
- **Flexibility**: Store markdown, images, tables, any extracted content
- **Scalable**: Clean separation works across S3 and local filesystems

See `parsing-hooks-examples.md` for more detailed examples.

## TODO: Future Enhancements

### High Priority
- [ ] **ContentService integration** for PDF parsing in `read()`
- [ ] **Multipart uploads** for large S3 files (>5GB)
- [ ] **Progress bars** for large uploads/downloads (tqdm)
- [ ] **Pagination** in `ls_iter()` for massive directories

### Medium Priority
- [ ] **python-docx provider** for `.docx` files
- [ ] **Audio providers** (librosa/pydub) for `.wav`, `.mp3`, `.flac`
- [ ] **Excel dependencies** (openpyxl/xlrd) for full `.xlsx`/`.xls` support
- [ ] **Archive operations** (`.zip`, `.tar.gz`) via copy interface
- [ ] **S3 versioning** support in all operations

### Low Priority
- [ ] **Local caching** strategy for `LocalProvider.cache_data()`
- [ ] **SVG to PIL** conversion for image operations
- [ ] **Video formats** (`.mp4`, `.avi`) via opencv or ffmpeg
- [ ] **Compression** options (gzip, brotli) for text formats

## Testing

```python
# Test basic operations
from rem.services.fs import FS

fs = FS()

# Write and read
fs.write("/tmp/test.json", {"test": "data"})
data = fs.read("/tmp/test.json")
assert data == {"test": "data"}

# S3 operations (requires configured bucket)
fs.write("s3://test-bucket/data.csv", df)
df2 = fs.read("s3://test-bucket/data.csv")
```

## Contributing

When adding new format support:

1. Add reader logic to both `S3Provider.read()` and `LocalProvider.read()`
2. Add writer logic to both `S3Provider.write()` and `LocalProvider.write()`
3. Add optional dependency to `pyproject.toml` with comment
4. Add format documentation to this README
5. Consider ContentService for complex formats (PDF, DOCX, etc.)

## Path Conventions

REM uses standardized path conventions for consistent file organization across local and S3 storage.

### Path Structure

```
{base_uri}/rem/{version}/{category}/{scope}/{date_parts}/
```

**Base URI:**
- **Local**: `$REM_HOME/fs/` (defaults to `~/.rem/fs`)
- **S3**: `s3://{bucket}/` (from settings)
- **Auto-detection**: Uses S3 in production, local in development

**Components:**

| Component | Description | Example |
|-----------|-------------|---------|
| `base_uri` | Storage location | `s3://rem-bucket` or `/Users/user/.rem/fs` |
| `rem` | Namespace | `rem` |
| `version` | API version | `v1`, `v2` |
| `category` | Resource type | `uploads`, `schemas`, `users`, `temp` |
| `scope` | User or system | `system`, `user-123` |
| `date_parts` | Date hierarchy | `2025/01/19` or `2025/01/19/14_30` |

### Upload Paths

Standard structure for file uploads with date-based partitioning:

```python
from rem.services.fs import get_uploads_path, FS

# System uploads (no user)
path = get_uploads_path()
# /Users/user/.rem/fs/rem/v1/uploads/system/2025/01/19

# User-specific uploads
path = get_uploads_path(user_id="user-123")
# /Users/user/.rem/fs/rem/v1/uploads/user-123/2025/01/19

# With specific date
from datetime import date
path = get_uploads_path(user_id="user-456", dt=date(2025, 1, 15))
# /Users/user/.rem/fs/rem/v1/uploads/user-456/2025/01/15

# Include hour/minute for high-frequency uploads
from datetime import datetime
path = get_uploads_path(user_id="user-789", dt=datetime.now(), include_time=True)
# /Users/user/.rem/fs/rem/v1/uploads/user-789/2025/01/19/14_30

# Force S3
path = get_uploads_path(user_id="user-123", use_s3=True)
# s3://rem-bucket/rem/v1/uploads/user-123/2025/01/19

# Use with FS
fs = FS()
upload_dir = get_uploads_path(user_id="user-123")
fs.write(f"{upload_dir}/data.json", {"key": "value"})
```

### Versioned Resource Paths

For schemas, agents, tools, and datasets:

```python
from rem.services.fs import get_versioned_path

# Schemas
path = get_versioned_path("schemas", "user-schema")
# /Users/user/.rem/fs/rem/v1/schemas/user-schema

# Agents (with version)
path = get_versioned_path("agents", "query-agent", version="v2")
# /Users/user/.rem/fs/rem/v2/agents/query-agent

# Tools
path = get_versioned_path("tools", "web-scraper")
# /Users/user/.rem/fs/rem/v1/tools/web-scraper

# Datasets
path = get_versioned_path("datasets", "training-data")
# /Users/user/.rem/fs/rem/v1/datasets/training-data
```

### User-Scoped Paths

For user-specific storage:

```python
from rem.services.fs import get_user_path

# User root
path = get_user_path("user-123")
# /Users/user/.rem/fs/rem/v1/users/user-123

# User documents
path = get_user_path("user-123", "documents")
# /Users/user/.rem/fs/rem/v1/users/user-123/documents

# User images
path = get_user_path("user-456", "images")
# /Users/user/.rem/fs/rem/v1/users/user-456/images
```

### Temporary Paths

For temporary file processing with timestamps:

```python
from rem.services.fs import get_temp_path

# Default temp
path = get_temp_path()
# /Users/user/.rem/fs/rem/v1/temp/tmp/20250119_143045

# Processing temp
path = get_temp_path("processing")
# /Users/user/.rem/fs/rem/v1/temp/processing/20250119_143045

# Conversion temp
path = get_temp_path("conversion")
# /Users/user/.rem/fs/rem/v1/temp/conversion/20250119_143045
```

### Path Utilities

```python
from rem.services.fs import (
    get_base_uri,
    get_rem_home,
    ensure_dir_exists,
    join_path
)

# Get base URI (auto-detect based on environment)
base = get_base_uri()

# Force local or S3
base = get_base_uri(use_s3=False)  # /Users/user/.rem/fs
base = get_base_uri(use_s3=True)   # s3://rem-bucket

# Get REM_HOME directory
home = get_rem_home()  # /Users/user/.rem

# Ensure directory exists (local only, no-op for S3)
path = ensure_dir_exists("/path/to/dir")

# Join paths (auto-detects S3 vs local)
path = join_path("s3://bucket", "rem", "v1", "uploads")
# s3://bucket/rem/v1/uploads

path = join_path("/home/user", "rem", "data")
# /home/user/rem/data
```

### Best Practices

1. **Always use path functions** - Don't hardcode paths
```python
# ✅ Good
from rem.services.fs import get_uploads_path
path = get_uploads_path(user_id="user-123")

# ❌ Bad
path = "/Users/user/.rem/fs/rem/v1/uploads/user-123/2025/01/19"
```

2. **Trust auto-detection** - Let environment determine S3 vs local
```python
# ✅ Good - auto-detects based on ENVIRONMENT
path = get_uploads_path(user_id="user-123")

# ❌ Unnecessary - only force when you have a specific reason
path = get_uploads_path(user_id="user-123", use_s3=False)
```

3. **Use date partitioning** - Leverage hierarchy for scalability
```python
# ✅ Good - partitioned by date
path = get_uploads_path(user_id="user-123", dt=datetime.now())

# ✅ Also good - include time for high-frequency uploads
path = get_uploads_path(user_id="user-123", include_time=True)
```

4. **User vs system scope** - Use user_id for user files, omit for system files
```python
# User files
user_upload = get_uploads_path(user_id="user-123")

# System files (logs, configs, etc.)
system_upload = get_uploads_path()  # Uses "system"
```

5. **Ensure directories exist** - For local paths before writing
```python
from rem.services.fs import get_uploads_path, ensure_dir_exists, FS

path = get_uploads_path(user_id="user-123")
ensure_dir_exists(path)  # No-op for S3

fs = FS()
fs.write(f"{path}/data.json", data)
```

### Path Reference

Quick reference for all path types:

| Function | Path Structure | Example |
|----------|----------------|---------|
| `get_uploads_path()` | `rem/v1/uploads/{system\|user_id}/{yyyy}/{mm}/{dd}[/{hh_mm}]` | `rem/v1/uploads/user-123/2025/01/19` |
| `get_versioned_path()` | `rem/{version}/{resource_type}/{name}` | `rem/v1/schemas/user-schema` |
| `get_user_path()` | `rem/v1/users/{user_id}[/{subpath}]` | `rem/v1/users/user-123/documents` |
| `get_temp_path()` | `rem/v1/temp/{prefix}/{timestamp}` | `rem/v1/temp/processing/20250119_143045` |

### Examples

See `rem/src/rem/services/fs/examples_paths.py` for complete working examples:

```bash
python -m rem.services.fs.examples_paths
```

## See Also

- ContentService: `rem/src/rem/services/content/` - Specialized parsing (PDF, DOCX, etc.)
- Settings: `rem/settings.py` - S3Settings, REM_HOME configuration
- Examples: `rem/src/rem/services/fs/examples_paths.py` - Path convention examples
