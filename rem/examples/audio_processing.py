"""
Example: Audio processing with REM.

Demonstrates chunking and transcription of audio files using
lightweight AudioChunker and AudioTranscriber services.

Usage:
    python examples/audio_processing.py path/to/audio.m4a

Requirements:
    - OPENAI_API_KEY environment variable
    - pydub installed: pip install rem[audio]
    - ffmpeg installed (included in Docker)
"""

import sys
from pathlib import Path

from loguru import logger

from rem.services.audio import AudioChunker, AudioTranscriber


def process_audio_file(audio_path: str | Path) -> None:
    """
    Process audio file: chunk by silence, transcribe with Whisper.

    Args:
        audio_path: Path to audio file (WAV, M4A, MP3, etc.)
    """
    audio_path = Path(audio_path)

    if not audio_path.exists():
        logger.error(f"File not found: {audio_path}")
        sys.exit(1)

    logger.info(f"Processing audio file: {audio_path}")
    logger.info(f"File size: {audio_path.stat().st_size / (1024*1024):.1f} MB")

    # Step 1: Chunk audio by silence near minute boundaries
    logger.info("\n=== Step 1: Chunking Audio ===")
    chunker = AudioChunker(
        target_chunk_seconds=60.0,  # 1 minute chunks
        chunk_window_seconds=2.0,  # ±2 second window for silence search
        silence_threshold_db=-40.0,  # Silence detection threshold
        min_silence_ms=500,  # Minimum 500ms silence
    )

    try:
        chunks = chunker.chunk_audio(audio_path)
        logger.success(f"Created {len(chunks)} chunks")

        for chunk in chunks:
            logger.info(
                f"  Chunk {chunk.chunk_index + 1}: "
                f"{chunk.start_seconds:.1f}s - {chunk.end_seconds:.1f}s "
                f"(duration: {chunk.duration_seconds:.1f}s)"
            )

    except Exception as e:
        logger.error(f"Chunking failed: {e}")
        sys.exit(1)

    # Step 2: Transcribe chunks with OpenAI Whisper
    logger.info("\n=== Step 2: Transcribing Chunks ===")
    transcriber = AudioTranscriber(
        model="whisper-1",
        temperature=0.0,  # Deterministic
    )

    try:
        results = transcriber.transcribe_chunks(chunks)
        logger.success(f"Transcribed {len(results)} chunks")

        # Step 3: Display results
        logger.info("\n=== Step 3: Transcription Results ===")
        full_text = []

        for result in results:
            timestamp = f"[{result.start_seconds:.1f}s - {result.end_seconds:.1f}s]"
            logger.info(f"\n{timestamp}")
            logger.info(f"  Text: {result.text[:100]}...")  # First 100 chars
            logger.info(f"  Duration: {result.duration_seconds:.1f}s")
            logger.info(f"  Confidence: {result.confidence:.2f}")

            full_text.append(f"{timestamp} {result.text}")

        # Save to file
        output_path = audio_path.with_suffix(".txt")
        output_path.write_text("\n\n".join(full_text))
        logger.success(f"\nFull transcription saved to: {output_path}")

        # Calculate total cost
        total_duration_minutes = sum(r.duration_seconds for r in results) / 60
        total_cost = total_duration_minutes * 0.006
        logger.info(f"\nTranscription cost: ${total_cost:.3f} ({total_duration_minutes:.1f} minutes)")

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        sys.exit(1)

    finally:
        # Step 4: Cleanup temporary files
        logger.info("\n=== Step 4: Cleanup ===")
        chunker.cleanup_chunks(chunks)
        logger.success("Temporary chunk files cleaned up")


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        logger.error("Usage: python examples/audio_processing.py path/to/audio.m4a")
        sys.exit(1)

    audio_path = sys.argv[1]
    process_audio_file(audio_path)


if __name__ == "__main__":
    main()
