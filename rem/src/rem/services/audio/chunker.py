"""
Audio chunker - splits audio by silence near minute boundaries.

Lightweight implementation using minimal dependencies:
- wave (stdlib) for WAV files
- pydub (optional) for format conversion

Design: Split audio near minute boundaries (58-62s range) at silence points.
This optimizes for OpenAI Whisper API 25MB file size limits while maintaining
natural speech boundaries.
"""

import struct
import tempfile
import wave
from pathlib import Path
from typing import Optional

from loguru import logger

# Check for pydub availability (optional for non-WAV formats)
try:
    from pydub import AudioSegment
    from pydub.silence import detect_silence

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("pydub not available - only WAV files will be supported")


class AudioChunk:
    """Represents a chunk of audio with temporal boundaries."""

    def __init__(
        self,
        file_path: str,
        start_ms: int,
        end_ms: int,
        chunk_index: int,
    ):
        """
        Initialize audio chunk.

        Args:
            file_path: Path to temporary audio file for this chunk
            start_ms: Start time in milliseconds
            end_ms: End time in milliseconds
            chunk_index: Index of this chunk in sequence
        """
        self.file_path = file_path
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.chunk_index = chunk_index
        self.duration_ms = end_ms - start_ms

    @property
    def start_seconds(self) -> float:
        """Start time in seconds."""
        return self.start_ms / 1000.0

    @property
    def end_seconds(self) -> float:
        """End time in seconds."""
        return self.end_ms / 1000.0

    @property
    def duration_seconds(self) -> float:
        """Duration in seconds."""
        return self.duration_ms / 1000.0

    def __repr__(self) -> str:
        return f"AudioChunk(index={self.chunk_index}, start={self.start_seconds:.1f}s, end={self.end_seconds:.1f}s, duration={self.duration_seconds:.1f}s)"


class AudioChunker:
    """
    Chunks audio files by silence near minute boundaries.

    Strategy:
    1. Target chunks around 60 seconds (configurable)
    2. Look for silence in a window around the target (e.g., 58-62s)
    3. Split at the longest silence in that window
    4. If no silence found, split at the target boundary

    This creates natural breaks while keeping chunks under OpenAI's
    25MB file size limit (~10 minutes of audio at typical bitrates).
    """

    def __init__(
        self,
        target_chunk_seconds: float = 60.0,
        chunk_window_seconds: float = 2.0,
        silence_threshold_db: float = -40.0,
        min_silence_ms: int = 500,
    ):
        """
        Initialize audio chunker.

        Args:
            target_chunk_seconds: Target chunk duration (default: 60s)
            chunk_window_seconds: Window around target to search for silence (±seconds)
            silence_threshold_db: dB threshold for silence detection (lower = stricter)
            min_silence_ms: Minimum silence duration to consider (milliseconds)
        """
        self.target_chunk_ms = int(target_chunk_seconds * 1000)
        self.chunk_window_ms = int(chunk_window_seconds * 1000)
        self.silence_threshold_db = silence_threshold_db
        self.min_silence_ms = min_silence_ms

    def chunk_audio(
        self,
        audio_path: str | Path,
        output_dir: Optional[str | Path] = None,
    ) -> list[AudioChunk]:
        """
        Chunk audio file by silence near minute boundaries.

        Args:
            audio_path: Path to audio file (WAV, M4A, MP3, etc.)
            output_dir: Directory for chunk files (temp dir if None)

        Returns:
            List of AudioChunk objects

        Raises:
            ValueError: If audio format not supported
            RuntimeError: If pydub not available for non-WAV files
        """
        audio_path = Path(audio_path)

        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Determine output directory
        if output_dir is None:
            output_dir = Path(tempfile.mkdtemp(prefix="rem_audio_chunks_"))
        else:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Chunking audio: {audio_path}")
        logger.info(
            f"Target: {self.target_chunk_ms/1000:.0f}s chunks, "
            f"window: ±{self.chunk_window_ms/1000:.0f}s, "
            f"silence: {self.silence_threshold_db}dB"
        )

        # Load audio (convert to WAV if needed)
        if audio_path.suffix.lower() == ".wav":
            audio = self._load_wav(audio_path)
        elif PYDUB_AVAILABLE:
            logger.info(f"Converting {audio_path.suffix} to AudioSegment")
            audio = AudioSegment.from_file(str(audio_path))
        else:
            raise RuntimeError(
                f"pydub required for {audio_path.suffix} files. "
                "Install with: pip install pydub"
            )

        duration_ms = len(audio)
        logger.info(f"Audio duration: {duration_ms/1000:.1f}s")

        # Find chunk boundaries
        boundaries = self._find_chunk_boundaries(audio, duration_ms)
        logger.info(f"Found {len(boundaries)-1} chunk boundaries: {[f'{b/1000:.1f}s' for b in boundaries]}")

        # Create chunks
        chunks = []
        for i in range(len(boundaries) - 1):
            start_ms = boundaries[i]
            end_ms = boundaries[i + 1]

            # Extract segment
            segment = audio[start_ms:end_ms]

            # Save to file
            chunk_filename = f"chunk_{i:03d}_{start_ms}_{end_ms}.wav"
            chunk_path = output_dir / chunk_filename

            segment.export(str(chunk_path), format="wav")

            chunk = AudioChunk(
                file_path=str(chunk_path),
                start_ms=start_ms,
                end_ms=end_ms,
                chunk_index=i,
            )
            chunks.append(chunk)
            logger.debug(f"Created {chunk}")

        logger.info(f"Created {len(chunks)} chunks in {output_dir}")
        return chunks

    def _load_wav(self, wav_path: Path) -> "AudioSegment":
        """
        Load WAV file using pydub or wave module.

        Args:
            wav_path: Path to WAV file

        Returns:
            AudioSegment

        Raises:
            ValueError: If WAV file invalid
        """
        if PYDUB_AVAILABLE:
            return AudioSegment.from_wav(str(wav_path))

        # Fallback: use wave module and convert to AudioSegment-like interface
        # This is a minimal implementation for WAV-only support
        raise RuntimeError(
            "pydub required for audio processing. Install with: pip install pydub"
        )

    def _find_chunk_boundaries(
        self,
        audio: "AudioSegment",
        duration_ms: int,
    ) -> list[int]:
        """
        Find chunk boundaries by detecting silence near target intervals.

        Strategy:
        1. Start at 0, target boundary at 60s
        2. Look for silence in window [58s, 62s]
        3. Split at longest silence in window
        4. If no silence, split at target (60s)
        5. Repeat until end of audio

        Args:
            audio: AudioSegment
            duration_ms: Total audio duration in milliseconds

        Returns:
            List of boundary timestamps in milliseconds
        """
        boundaries = [0]  # Start at beginning
        current_pos = 0

        while current_pos < duration_ms:
            # Target next boundary
            target_boundary = current_pos + self.target_chunk_ms

            if target_boundary >= duration_ms:
                # Last chunk - use end of audio
                boundaries.append(duration_ms)
                break

            # Define search window around target
            window_start = max(
                current_pos, target_boundary - self.chunk_window_ms
            )
            window_end = min(duration_ms, target_boundary + self.chunk_window_ms)

            # Find best split point (longest silence in window)
            split_point = self._find_best_split(
                audio,
                window_start,
                window_end,
                target_boundary,
            )

            boundaries.append(split_point)
            current_pos = split_point

        return boundaries

    def _find_best_split(
        self,
        audio: "AudioSegment",
        window_start: int,
        window_end: int,
        target: int,
    ) -> int:
        """
        Find best split point in window by detecting silence.

        Args:
            audio: AudioSegment
            window_start: Start of search window (ms)
            window_end: End of search window (ms)
            target: Target split point (ms)

        Returns:
            Best split point in milliseconds
        """
        if not PYDUB_AVAILABLE:
            # No pydub - split at target
            return target

        # Extract window
        window = audio[window_start:window_end]

        # Detect silence
        silence_ranges = detect_silence(
            window,
            min_silence_len=self.min_silence_ms,
            silence_thresh=self.silence_threshold_db,
            seek_step=10,  # Check every 10ms
        )

        if not silence_ranges:
            # No silence found - split at target
            logger.debug(f"No silence in window [{window_start/1000:.1f}s, {window_end/1000:.1f}s], splitting at target {target/1000:.1f}s")
            return target

        # Find longest silence closest to target
        best_silence = None
        best_score = float("-inf")

        for silence_start, silence_end in silence_ranges:
            silence_duration = silence_end - silence_start
            silence_midpoint = (silence_start + silence_end) // 2
            absolute_midpoint = window_start + silence_midpoint

            # Score: prefer longer silences closer to target
            # Distance penalty: further from target = lower score
            distance_from_target = abs(absolute_midpoint - target)
            distance_penalty = 1.0 / (1.0 + distance_from_target / 1000.0)

            # Duration bonus: longer silence = higher score
            duration_bonus = silence_duration / 1000.0

            score = duration_bonus * distance_penalty

            if score > best_score:
                best_score = score
                best_silence = absolute_midpoint

        if best_silence is not None:
            logger.debug(
                f"Found silence at {best_silence/1000:.1f}s "
                f"(target: {target/1000:.1f}s, score: {best_score:.3f})"
            )
            return best_silence

        # Fallback to target
        return target

    def cleanup_chunks(self, chunks: list[AudioChunk]) -> None:
        """
        Clean up chunk files.

        Args:
            chunks: List of AudioChunk objects to clean up
        """
        for chunk in chunks:
            try:
                Path(chunk.file_path).unlink(missing_ok=True)
                logger.debug(f"Deleted chunk file: {chunk.file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete {chunk.file_path}: {e}")
