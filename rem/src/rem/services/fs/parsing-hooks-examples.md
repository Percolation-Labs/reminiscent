# fs parsing hooks - extended examples

Clean pattern for managing parsed file versions in REM filesystem abstraction.

## convention

Separate `uploads/` and `parsed/` directories with deterministic path mapping:

**S3:**
- Uploads: `s3://rem-io-staging/v1/uploads/user-123/2025/01/19/report.pdf`
- Parsed:  `s3://rem-io-staging/v1/parsed/user-123/2025/01/19/report.pdf/{resource}`

**Local:**
- Uploads: `~/.rem/fs/v1/uploads/user-123/2025/01/19/report.pdf`
- Parsed:  `~/.rem/fs/v1/parsed/user-123/2025/01/19/report.pdf/{resource}`

**Resources:**
- `metadata.json` - parse metadata (provider, timestamp, etc.)
- `content.md` - primary parsed content (markdown)
- `images/` - extracted images
- `tables/` - extracted tables (parquet)

## basic usage

```python
from rem.services.fs import FS

fs = FS()
upload_uri = "s3://rem-io-staging/v1/uploads/user-123/2025/01/19/report.pdf"

# check and read
if fs.has_parsed(upload_uri):
    markdown = fs.read_parsed(upload_uri)
else:
    # trigger parsing
    from rem.services.content import ContentService
    service = ContentService()
    await service.process_and_save(upload_uri)
```

## writing parsed content

```python
# write markdown with metadata
fs.write_parsed(
    uri,
    markdown_content,
    metadata={
        "provider": "kreuzberg",
        "page_count": 10,
        "table_count": 2,
    }
)

# write extracted image
fs.write_parsed(uri, image_data, resource="images/page_1.png")

# write extracted table
fs.write_parsed(uri, table_df, resource="tables/table_0.parquet")
```

## reading specific resources

```python
# read metadata
metadata = fs.read_parsed(uri, "metadata.json")

# read image
image = fs.read_parsed(uri, "images/page_1.png")

# read table
table = fs.read_parsed(uri, "tables/table_0.parquet")
```

## discovering resources

```python
# list all parsed resources
resources = fs.list_parsed_resources(uri)
# ['content.md', 'metadata.json', 'images/page_1.png', 'tables/table_0.parquet']

# iterate and read
for resource in resources:
    if resource.endswith('.png'):
        image = fs.read_parsed(uri, resource)
    elif resource.endswith('.parquet'):
        table = fs.read_parsed(uri, resource)
```

## integration with ContentService

```python
class ContentService:
    async def process_and_save(self, uri: str, user_id: str | None = None):
        # check cache first
        if self.fs.has_parsed(uri):
            logger.info(f"using cached parse for {uri}")
            return self.fs.read_parsed(uri, "metadata.json")

        # extract and parse
        result = self.process_uri(uri)
        markdown = to_markdown(result["content"], Path(uri).name)

        # write parsed version
        self.fs.write_parsed(
            uri,
            markdown,
            metadata={
                "provider": result["provider"],
                "timestamp": datetime.now().isoformat(),
                "content_type": result["metadata"].get("content_type"),
            }
        )

        # chunk and save to database...
```

## multi-resource parsing

For complex documents with many extracted resources:

```python
# parse pdf and extract everything
result = parse_pdf_advanced(uri)

# write markdown
fs.write_parsed(uri, result.markdown)

# write images
for i, img in enumerate(result.images):
    fs.write_parsed(uri, img, resource=f"images/page_{i}.png")

# write tables
for i, table in enumerate(result.tables):
    fs.write_parsed(uri, table, resource=f"tables/table_{i}.parquet")

# write metadata
fs.write_parsed(
    uri,
    result.markdown,
    metadata={
        "provider": "advanced_parser",
        "page_count": len(result.images),
        "table_count": len(result.tables),
    }
)
```

## benefits

- **separation of concerns**: parsed files alongside originals, not in database
- **caching**: check `has_parsed()` before re-parsing expensive files
- **discoverability**: `list_parsed_resources()` shows what's available
- **flexibility**: store markdown, images, tables, any extracted content
- **convention over configuration**: standard `.parsed/` suffix

## local provider

Same interface for local files:

```python
from rem.services.fs import LocalProvider

fs = LocalProvider()
uri = "/data/docs/report.pdf"

if fs.has_parsed(uri):
    markdown = fs.read_parsed(uri)
else:
    markdown = parse_pdf(uri)
    fs.write_parsed(uri, markdown, metadata={"provider": "kreuzberg"})
```
