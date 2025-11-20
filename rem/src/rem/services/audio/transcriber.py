"""
Audio transcriber using OpenAI Whisper API.

Lightweight implementation using only requests (no httpx dependency).
Handles file uploads and response parsing for OpenAI's Whisper API.
"""

import os
from pathlib import Path
from typing import Optional

import requests
from loguru import logger


class TranscriptionResult:
    """Result from audio transcription."""

    def __init__(
        self,
        text: str,
        start_seconds: float,
        end_seconds: float,
        duration_seconds: float,
        language: Optional[str] = None,
        confidence: float = 0.9,
    ):
        """
        Initialize transcription result.

        Args:
            text: Transcribed text
            start_seconds: Start time of segment
            end_seconds: End time of segment
            duration_seconds: Duration of segment
            language: Detected language (if available)
            confidence: Confidence score (0.0-1.0)
        """
        self.text = text
        self.start_seconds = start_seconds
        self.end_seconds = end_seconds
        self.duration_seconds = duration_seconds
        self.language = language
        self.confidence = confidence

    def __repr__(self) -> str:
        return f"TranscriptionResult(start={self.start_seconds:.1f}s, end={self.end_seconds:.1f}s, chars={len(self.text)})"


class AudioTranscriber:
    """
    Transcribe audio using OpenAI Whisper API.

    Uses only requests library (no httpx) for minimal dependencies.
    Supports all Whisper-compatible audio formats.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        language: Optional[str] = None,
        temperature: float = 0.0,
    ):
        """
        Initialize audio transcriber.

        Args:
            api_key: OpenAI API key (from env if None)
            model: Whisper model name (default: whisper-1)
            language: ISO-639-1 language code (auto-detect if None)
            temperature: Sampling temperature 0.0-1.0 (0 = deterministic)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.warning("No OpenAI API key found - transcription will fail")

        self.model = model
        self.language = language
        self.temperature = temperature
        self.api_url = "https://api.openai.com/v1/audio/transcriptions"

    def transcribe_file(
        self,
        audio_path: str | Path,
        start_seconds: float = 0.0,
        end_seconds: Optional[float] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio file using OpenAI Whisper API.

        Args:
            audio_path: Path to audio file
            start_seconds: Start time (for metadata only)
            end_seconds: End time (for metadata, auto-detect if None)

        Returns:
            TranscriptionResult with text and metadata

        Raises:
            ValueError: If API key missing or file invalid
            RuntimeError: If API request fails
        """
        if not self.api_key:
            raise ValueError("OpenAI API key required for transcription")

        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info(
            f"Transcribing {audio_path.name} ({file_size_mb:.1f} MB) "
            f"with Whisper API"
        )

        # Check file size (Whisper API limit: 25 MB)
        if file_size_mb > 25:
            raise ValueError(
                f"Audio file too large: {file_size_mb:.1f} MB "
                "(max 25 MB for Whisper API)"
            )

        # Prepare request
        headers = {"Authorization": f"Bearer {self.api_key}"}

        # Build form data
        data = {
            "model": self.model,
            "response_format": "text",  # Simple text response
            "temperature": self.temperature,
        }

        if self.language:
            data["language"] = self.language

        # Open file and make request
        try:
            with open(audio_path, "rb") as audio_file:
                files = {"file": (audio_path.name, audio_file, "audio/wav")}

                logger.debug(f"Sending request to {self.api_url}")
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=120.0,  # 2 minute timeout
                )

            # Check response
            if response.status_code != 200:
                error_detail = response.text
                logger.error(
                    f"Whisper API error: {response.status_code} - {error_detail}"
                )
                raise RuntimeError(
                    f"Transcription failed: {response.status_code} - {error_detail}"
                )

            # Extract text
            transcription_text = response.text.strip()
            logger.info(
                f"✓ Transcription complete: {len(transcription_text)} characters"
            )

            # Calculate duration (use provided or estimate)
            if end_seconds is None:
                # Estimate from file size (rough approximation)
                # WAV: ~10KB per second at 16kHz mono
                # This is very rough, but better than nothing
                end_seconds = start_seconds + (file_size_mb * 1024 * 10)

            duration = end_seconds - start_seconds

            return TranscriptionResult(
                text=transcription_text,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                duration_seconds=duration,
                language=self.language,
                confidence=0.9,  # Whisper doesn't provide confidence
            )

        except requests.exceptions.Timeout:
            logger.error("Whisper API request timed out")
            raise RuntimeError("Transcription timed out after 120 seconds")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise RuntimeError(f"Transcription request failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during transcription: {e}")
            raise

    def transcribe_chunks(
        self,
        chunks: list,  # List of AudioChunk objects from AudioChunker
    ) -> list[TranscriptionResult]:
        """
        Transcribe multiple audio chunks.

        Args:
            chunks: List of AudioChunk objects from AudioChunker

        Returns:
            List of TranscriptionResult objects

        Raises:
            ValueError: If API key missing
            RuntimeError: If any transcription fails
        """
        if not self.api_key:
            raise ValueError("OpenAI API key required for transcription")

        logger.info(f"Transcribing {len(chunks)} audio chunks")

        results = []
        total_duration = sum(c.duration_seconds for c in chunks)
        estimated_cost = (total_duration / 60) * 0.006  # $0.006 per minute

        logger.info(
            f"Estimated cost: ${estimated_cost:.3f} "
            f"(${total_duration / 60:.1f} minutes)"
        )

        for i, chunk in enumerate(chunks, 1):
            logger.info(
                f"Processing chunk {i}/{len(chunks)} "
                f"({chunk.start_seconds:.1f}s - {chunk.end_seconds:.1f}s)"
            )

            try:
                result = self.transcribe_file(
                    chunk.file_path,
                    start_seconds=chunk.start_seconds,
                    end_seconds=chunk.end_seconds,
                )
                results.append(result)
                logger.debug(f"✓ Chunk {i} transcribed: {len(result.text)} chars")

            except Exception as e:
                logger.error(f"Failed to transcribe chunk {i}: {e}")
                # Add error result
                results.append(
                    TranscriptionResult(
                        text=f"[Transcription failed: {e}]",
                        start_seconds=chunk.start_seconds,
                        end_seconds=chunk.end_seconds,
                        duration_seconds=chunk.duration_seconds,
                        confidence=0.0,
                    )
                )

        successful = sum(1 for r in results if r.confidence > 0)
        logger.info(
            f"Transcription complete: {successful}/{len(chunks)} chunks successful"
        )

        return results
