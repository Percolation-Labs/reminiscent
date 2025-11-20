# REM Audio Processing

Lightweight audio processing service with minimal dependencies for chunking and transcribing audio files.

## Design Philosophy

**Minimal Dependencies:**
- `wave` (stdlib) for WAV file handling
- `pydub` for audio format conversion (wraps ffmpeg)
- `requests` for OpenAI Whisper API (already a REM dependency)
- `loguru` for logging (REM standard)

**No Heavy ML Libraries:**
- No `torch`, `torchaudio`, or other heavyweight dependencies
- No `librosa` for audio analysis
- Keep the Docker image lean and fast

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  REM Audio Service                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐         ┌──────────────┐            │
│  │ AudioChunker │────────▶│AudioTranscriber│           │
│  └──────────────┘         └──────────────┘            │
│         │                        │                     │
│         │                        │                     │
│    Split by silence         OpenAI Whisper API         │
│    near minute              ($0.006/minute)            │
│    boundaries                                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. AudioChunker

Splits audio files by detecting silence near minute boundaries.

**Strategy:**
- Target chunks around 60 seconds (configurable)
- Look for silence in window around target (±2 seconds)
- Split at longest silence in window
- If no silence, split at target boundary

**Benefits:**
- Keeps chunks under OpenAI's 25MB limit (~10 minutes)
- Natural breaks at silence points
- Maintains speech context within chunks

**Example:**
```python
from rem.services.audio import AudioChunker

chunker = AudioChunker(
    target_chunk_seconds=60.0,  # 1 minute target
    chunk_window_seconds=2.0,    # ±2 second search window
    silence_threshold_db=-40.0,  # Silence detection threshold
    min_silence_ms=500,          # Minimum 500ms silence
)

# Chunk audio file
chunks = chunker.chunk_audio("recording.m4a")

# Process chunks
for chunk in chunks:
    print(f"Chunk {chunk.chunk_index}: {chunk.start_seconds:.1f}s - {chunk.end_seconds:.1f}s")
    print(f"Duration: {chunk.duration_seconds:.1f}s")
    print(f"File: {chunk.file_path}")

# Cleanup when done
chunker.cleanup_chunks(chunks)
```

### 2. AudioTranscriber

Transcribes audio using OpenAI Whisper API.

**Features:**
- Uses `requests` (no httpx dependency)
- Handles file uploads efficiently
- Automatic cost estimation
- Detailed logging with loguru

**Example:**
```python
from rem.services.audio import AudioTranscriber

transcriber = AudioTranscriber(
    api_key="sk-...",           # Or from OPENAI_API_KEY env
    model="whisper-1",           # OpenAI Whisper model
    language=None,               # Auto-detect language
    temperature=0.0,             # Deterministic transcription
)

# Transcribe single file
result = transcriber.transcribe_file("audio.wav")
print(result.text)

# Transcribe chunks
results = transcriber.transcribe_chunks(chunks)
for result in results:
    print(f"[{result.start_seconds:.1f}s - {result.end_seconds:.1f}s]: {result.text}")
```

### 3. Complete Workflow

```python
from rem.services.audio import AudioChunker, AudioTranscriber

# 1. Chunk audio by silence
chunker = AudioChunker()
chunks = chunker.chunk_audio("meeting_recording.m4a")

print(f"Created {len(chunks)} chunks")

# 2. Transcribe chunks
transcriber = AudioTranscriber()
results = transcriber.transcribe_chunks(chunks)

print(f"Transcribed {len(results)} chunks")

# 3. Combine results
full_transcription = "\n\n".join([
    f"[{r.start_seconds:.1f}s]: {r.text}"
    for r in results
])

print(full_transcription)

# 4. Cleanup
chunker.cleanup_chunks(chunks)
```

## Configuration

### Environment Variables

```bash
# OpenAI API Key (required for transcription)
OPENAI_API_KEY=sk-...

# Chunker Settings (optional)
AUDIO_CHUNK_TARGET_SECONDS=60       # Target chunk duration
AUDIO_CHUNK_WINDOW_SECONDS=2        # Silence search window
AUDIO_SILENCE_THRESHOLD_DB=-40      # Silence detection threshold
AUDIO_MIN_SILENCE_MS=500            # Minimum silence duration
```

### Transcription Costs

OpenAI Whisper API pricing: **$0.006 per minute**

Examples:
- 10 minute recording: $0.06
- 1 hour recording: $0.36
- 10 hour recording: $3.60

## Supported Formats

### With pydub + ffmpeg:
- WAV (uncompressed)
- MP3 (compressed)
- M4A (Apple audio)
- FLAC (lossless)
- OGG (Vorbis)
- WMA (Windows)

### Without pydub:
- Only WAV files (requires pydub for format conversion)

## Docker Setup

The Dockerfile includes ffmpeg for audio processing:

```dockerfile
# Runtime dependencies
RUN apt-get install -y \
    ffmpeg  # Required by pydub for format conversion
```

Install pydub dependency:

```bash
# Install audio extras
pip install rem[audio]

# Or install all extras
pip install rem[all]
```

## Dependencies

### Core (always installed with rem[audio]):
- `pydub>=0.25.0` - Audio manipulation

### System (Docker):
- `ffmpeg` - Audio codec support (installed in Dockerfile)

### External APIs:
- OpenAI Whisper API - Speech-to-text transcription

## Error Handling

### Missing API Key
```python
transcriber = AudioTranscriber()  # No API key

# Raises: ValueError("OpenAI API key required for transcription")
result = transcriber.transcribe_file("audio.wav")
```

### File Too Large
```python
# Whisper API limit: 25 MB
transcriber.transcribe_file("huge_file.wav")

# Raises: ValueError("Audio file too large: 30.5 MB (max 25 MB)")
```

### No pydub
```python
# Without pydub installed
chunker = AudioChunker()
chunker.chunk_audio("audio.m4a")

# Raises: RuntimeError("pydub required for .m4a files")
```

## Best Practices

1. **Chunk Before Transcribing**
   - Don't send entire 2-hour recordings to Whisper
   - Chunk into 1-minute segments for better quality
   - Easier to debug and retry failed segments

2. **Monitor Costs**
   - Log transcription duration and cost
   - Set budgets for long recordings
   - Use `transcriber.transcribe_chunks()` for cost estimation

3. **Handle Failures Gracefully**
   - Chunks can fail independently
   - Retry logic for transient errors
   - Save partial results

4. **Cleanup Temporary Files**
   - Always call `chunker.cleanup_chunks()` when done
   - Or use context manager (future enhancement)

5. **Use Silence Detection**
   - Default settings work well for most speech
   - Adjust `silence_threshold_db` for noisy recordings
   - Increase `min_silence_ms` for natural pauses

## Integration with REM

### File Processing

```python
# rem/workers/file_processor.py
from rem.services.audio import AudioChunker, AudioTranscriber

async def process_audio_file(file_path: Path, user_id: str):
    """Process audio file and create REM resources."""

    # 1. Chunk audio
    chunker = AudioChunker()
    chunks = chunker.chunk_audio(file_path)

    # 2. Transcribe chunks
    transcriber = AudioTranscriber()
    results = transcriber.transcribe_chunks(chunks)

    # 3. Create REM resources
    for i, result in enumerate(results):
        resource = Resource(
            name=f"{file_path.stem} - Part {i+1}",
            uri=f"{file_path.as_uri()}#t={result.start_seconds},{result.end_seconds}",
            content=result.text,
            timestamp=datetime.now(),
            category="transcription",
            user_id=user_id,
        )
        await repository.upsert(resource)

    # 4. Cleanup
    chunker.cleanup_chunks(chunks)
```

### Dreaming Worker

```python
# rem/workers/dreaming.py
from rem.services.audio import AudioChunker, AudioTranscriber

async def extract_moments_from_audio(audio_resource: Resource):
    """Extract moments from audio transcription."""

    # Audio already transcribed and stored as Resource
    # Use transcription content to identify temporal moments

    # Example: Split by speaker changes, topic shifts, etc.
    moments = extract_temporal_segments(audio_resource.content)

    for moment in moments:
        await repository.upsert(moment)
```

## Logging

All logs use loguru (REM standard):

```python
from loguru import logger

# Chunker logs
logger.info("Chunking audio: /path/to/file.m4a")
logger.debug("Found silence at 58.3s (target: 60.0s)")
logger.info("Created 5 chunks in /tmp/rem_audio_chunks_xyz")

# Transcriber logs
logger.info("Transcribing chunk 1/5 (58.0s - 118.0s)")
logger.debug("Sending 2.3 MB to OpenAI Whisper API")
logger.info("✓ Transcription complete: 245 characters")
logger.info("Estimated cost: $0.180 (30.0 minutes)")
```

## Testing

```bash
# Run audio service tests
pytest tests/unit/services/audio/

# Test with real files (requires OpenAI API key)
export OPENAI_API_KEY=sk-...
pytest tests/integration/services/audio/
```

## Future Enhancements

1. **Context Manager for Cleanup**
   ```python
   with AudioChunker() as chunker:
       chunks = chunker.chunk_audio("file.m4a")
       # Auto-cleanup on exit
   ```

2. **Batch Transcription**
   - Parallel API requests
   - Rate limiting
   - Progress tracking

3. **Speaker Diarization**
   - Detect speaker changes
   - Label speakers
   - Split on speaker boundaries

4. **Advanced Silence Detection**
   - Machine learning-based VAD
   - Energy-based fallback
   - Adaptive thresholds

5. **Format Detection**
   - Auto-detect audio format
   - Validate before processing
   - Better error messages

## References

- [OpenAI Whisper API](https://platform.openai.com/docs/guides/speech-to-text)
- [pydub Documentation](https://github.com/jiaaro/pydub)
- [ffmpeg Documentation](https://ffmpeg.org/documentation.html)
