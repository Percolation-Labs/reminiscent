"""
Audio processing service for REM.

Lightweight audio processing with minimal dependencies:
- wav module (stdlib) for WAV file handling
- pydub (optional) for format conversion (M4A, MP3, etc.)
- requests (already a dependency) for OpenAI Whisper API

No torch, torchaudio, or other heavy ML dependencies.
"""

from .chunker import AudioChunker
from .transcriber import AudioTranscriber

__all__ = ["AudioChunker", "AudioTranscriber"]
