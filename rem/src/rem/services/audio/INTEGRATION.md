# Audio Provider Integration

The AudioProvider is now fully integrated into REM's ContentService with a **consistent interface** that matches all other content providers.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                     ContentService                         │
│                  (Pluggable Providers)                     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  ┌──────────────┐  ┌────────────┐  ┌─────────────────┐   │
│  │ TextProvider │→│DocProvider │→│ AudioProvider   │   │
│  └──────────────┘  └────────────┘  └─────────────────┘   │
│         │                  │                  │           │
│         ▼                  ▼                  ▼           │
│      extract()         extract()         extract()        │
│         │                  │                  │           │
│         ▼                  ▼                  ▼           │
│     Markdown           Markdown           Markdown        │
│       text               text               text          │
│         │                  │                  │           │
│         └──────────────────┼──────────────────┘           │
│                            │                              │
│                            ▼                              │
│                    chunk_text() → embed()                 │
│                            │                              │
│                            ▼                              │
│                   Save to Database                        │
│                 (File + Resource entities)                │
└────────────────────────────────────────────────────────────┘
```

## Consistent Interface

All content providers implement the same `ContentProvider` base class:

```python
class ContentProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/debugging."""
        pass

    @abstractmethod
    def extract(self, content: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Extract text content from file bytes.

        Args:
            content: Raw file bytes
            metadata: File metadata (size, type, etc.)

        Returns:
            dict with:
                - text: Extracted text content
                - metadata: Additional metadata from extraction (optional)
        """
        pass
```

## Provider Implementations

### 1. TextProvider
```python
def extract(self, content: bytes, metadata: dict) -> dict:
    text = content.decode("utf-8")
    return {
        "text": text,
        "metadata": {"line_count": len(text.split("\n"))}
    }
```

### 2. DocProvider (Kreuzberg)
```python
def extract(self, content: bytes, metadata: dict) -> dict:
    # Uses Kreuzberg for PDF extraction
    result = extract_file_sync(tmp_path, config=config)
    return {
        "text": result.content,
        "metadata": {"table_count": len(result.tables)}
    }
```

### 3. AudioProvider (AudioChunker + Whisper)
```python
def extract(self, content: bytes, metadata: dict) -> dict:
    # 1. Chunk audio by silence
    chunks = chunker.chunk_audio(tmp_path)

    # 2. Transcribe chunks
    results = transcriber.transcribe_chunks(chunks)

    # 3. Format as markdown with timestamps
    markdown_parts = []
    for result in results:
        timestamp = f"{result.start_seconds:.1f}s - {result.end_seconds:.1f}s"
        markdown_parts.append(f"## [{timestamp}]\n\n{result.text}\n")

    return {
        "text": "\n".join(markdown_parts),
        "metadata": {
            "chunk_count": len(chunks),
            "duration_seconds": total_duration,
            "estimated_cost": estimated_cost,
        }
    }
```

## Markdown Format

All providers return markdown-formatted text. AudioProvider returns:

```markdown
## [0.0s - 60.0s]

Transcription of first minute goes here...

## [60.0s - 120.0s]

Transcription of second minute goes here...

## [120.0s - 180.0s]

Transcription of third minute goes here...
```

This format:
- ✅ Is valid markdown
- ✅ Has clear section boundaries
- ✅ Preserves temporal information
- ✅ Can be chunked further if needed
- ✅ Embeds naturally with other content

## Processing Pipeline

### Example: Audio File Processing

```python
from rem.services.content import ContentService

service = ContentService()

# Process audio file (same interface as PDF/markdown!)
result = service.process_uri("s3://bucket/meeting.m4a")

# Result structure (same for all providers):
{
    "uri": "s3://bucket/meeting.m4a",
    "content": "## [0.0s - 60.0s]\n\nDiscussion about...\n\n## [60.0s - 120.0s]...",
    "metadata": {
        "chunk_count": 5,
        "duration_seconds": 300.0,
        "estimated_cost": 0.030,
        "parser": "whisper_api"
    },
    "provider": "audio"
}
```

### End-to-End Processing

```python
# Process and save to database
await service.process_and_save(
    uri="s3://bucket/meeting.m4a",
    user_id="user-123"
)

# This automatically:
# 1. Downloads from S3
# 2. Chunks audio by silence
# 3. Transcribes with Whisper
# 4. Converts to markdown
# 5. Chunks markdown text
# 6. Saves File entity
# 7. Saves Resource entities (one per chunk)
# 8. Generates embeddings (ready for vector search)
```

## Registered Extensions

The AudioProvider is automatically registered for:
- `.wav` - Uncompressed audio
- `.mp3` - Compressed audio
- `.m4a` - Apple audio format
- `.flac` - Lossless compression
- `.ogg` - Ogg Vorbis

## Graceful Degradation

Without OpenAI API key:
```python
result = audio_provider.extract(content, metadata)

# Returns:
{
    "text": "[Audio transcription requires OPENAI_API_KEY environment variable]",
    "metadata": {"error": "missing_api_key"}
}
```

Without pydub installed:
```python
# Returns:
{
    "text": "[Audio processing requires: pip install rem[audio]]",
    "metadata": {"error": "missing_dependencies"}
}
```

## Testing

All providers tested for interface consistency:

```bash
# Run integration tests
pytest tests/integration/services/test_content_providers.py -v

# Results:
# ✓ test_markdown_provider_interface PASSED
# ✓ test_pdf_provider_interface PASSED
# ✓ test_audio_provider_interface PASSED
# ✓ test_content_service_has_all_providers PASSED
# ✓ test_markdown_file_processing PASSED
# ✓ test_audio_file_processing_without_api_key PASSED
# ✓ test_all_providers_return_text_and_metadata PASSED
# ✓ test_all_providers_handle_empty_content PASSED
# ✓ test_markdown_to_audio_consistency PASSED
# ✓ test_audio_returns_markdown_with_timestamps PASSED
```

## Consistency Guarantees

All providers:

1. **Accept same input**: `extract(content: bytes, metadata: dict)`
2. **Return same structure**: `{"text": str, "metadata": dict}`
3. **Return markdown format**: Text is markdown-compatible
4. **Handle errors gracefully**: Return error messages, don't crash
5. **Register with ContentService**: Via file extension mapping
6. **Follow pipeline**: extract → markdown → chunk → embed → save

## Usage Examples

### Process Single File

```python
from rem.services.content import ContentService

service = ContentService()

# Process markdown
md_result = service.process_uri("document.md")

# Process PDF
pdf_result = service.process_uri("report.pdf")

# Process audio (same interface!)
audio_result = service.process_uri("meeting.m4a")

# All return same structure
assert "content" in md_result
assert "content" in pdf_result
assert "content" in audio_result
```

### Process with S3

```python
# S3 URI - automatic download and processing
result = service.process_uri("s3://recordings/standup.m4a")

# Transcribed, chunked, and ready to save
```

### Custom Provider Registration

```python
# Register custom provider
service.register_provider(
    extensions=[".custom"],
    provider=CustomProvider()
)

# Now .custom files use CustomProvider
```

## Future Enhancements

1. **Streaming Transcription**: Process long audio files in streams
2. **Speaker Diarization**: Identify different speakers
3. **Language Detection**: Auto-detect language for transcription
4. **Timestamp Refinement**: More accurate timestamps via VAD
5. **Batch Processing**: Parallel transcription of multiple files

## Key Takeaways

✅ **Pluggable**: Easy to add new content types
✅ **Consistent**: Same interface for all providers
✅ **Testable**: All providers tested for consistency
✅ **Graceful**: Handles missing dependencies/keys elegantly
✅ **Integrated**: Works with ContentService out of the box
✅ **Production-Ready**: Error handling, logging, cleanup

The AudioProvider is a **first-class citizen** in REM's content processing pipeline!
