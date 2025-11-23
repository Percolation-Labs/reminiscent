#!/usr/bin/env python3
"""
Generate test audio files for audio provider testing.

Creates realistic WAV files with synthesized tones that simulate speech patterns.
"""

import math
import struct
import wave
from pathlib import Path


def generate_tone_sequence(
    duration_seconds: float,
    sample_rate: int = 16000,
    frequencies: list[float] | None = None,
) -> bytes:
    """
    Generate a sequence of tones to simulate speech-like audio.

    Args:
        duration_seconds: Length of audio in seconds
        sample_rate: Sample rate in Hz (16kHz is standard for speech)
        frequencies: List of frequencies to cycle through (simulates speech formants)

    Returns:
        PCM audio data as bytes
    """
    if frequencies is None:
        # Simulate speech formants (vowel-like sounds)
        frequencies = [300, 500, 700, 1000, 1200, 800, 600, 400]

    num_samples = int(duration_seconds * sample_rate)
    samples = []

    # Generate tone sequence with varying frequencies (simulates speech patterns)
    samples_per_tone = num_samples // len(frequencies)

    for i, freq in enumerate(frequencies):
        start_sample = i * samples_per_tone
        end_sample = start_sample + samples_per_tone

        for n in range(start_sample, min(end_sample, num_samples)):
            # Generate sine wave
            t = n / sample_rate
            amplitude = 0.3  # 30% volume to avoid clipping

            # Add slight amplitude modulation to simulate speech dynamics
            modulation = 1.0 + 0.2 * math.sin(2 * math.pi * 4 * t)  # 4 Hz modulation

            # Combine fundamental frequency with harmonic
            value = amplitude * modulation * (
                math.sin(2 * math.pi * freq * t) +  # Fundamental
                0.3 * math.sin(2 * math.pi * freq * 2 * t)  # Second harmonic
            )

            # Convert to 16-bit PCM
            pcm_value = int(value * 32767)
            samples.append(pcm_value)

    # Pack as 16-bit signed integers (little-endian)
    return struct.pack(f"<{len(samples)}h", *samples)


def generate_wav_file(
    output_path: Path,
    duration_seconds: float,
    sample_rate: int = 16000,
    num_channels: int = 1,
) -> None:
    """
    Generate a WAV file with synthesized speech-like audio.

    Args:
        output_path: Path to output WAV file
        duration_seconds: Length of audio in seconds
        sample_rate: Sample rate in Hz
        num_channels: Number of audio channels (1=mono, 2=stereo)
    """
    # Generate audio data
    audio_data = generate_tone_sequence(duration_seconds, sample_rate)

    # Write WAV file
    with wave.open(str(output_path), "wb") as wav_file:
        wav_file.setnchannels(num_channels)
        wav_file.setsampwidth(2)  # 16-bit = 2 bytes
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)

    file_size_kb = output_path.stat().st_size / 1024
    print(f"Generated {output_path.name}: {duration_seconds}s, {file_size_kb:.1f} KB")


def main():
    """Generate test audio files."""
    output_dir = Path(__file__).parent

    # 1. Short test file (3 seconds) - for quick tests
    generate_wav_file(
        output_path=output_dir / "test_short_3s.wav",
        duration_seconds=3.0,
        sample_rate=16000,
        num_channels=1,
    )

    # 2. Medium test file (10 seconds) - for chunking tests
    generate_wav_file(
        output_path=output_dir / "test_medium_10s.wav",
        duration_seconds=10.0,
        sample_rate=16000,
        num_channels=1,
    )

    # 3. Standard test file (30 seconds) - typical use case
    generate_wav_file(
        output_path=output_dir / "test_standard_30s.wav",
        duration_seconds=30.0,
        sample_rate=16000,
        num_channels=1,
    )

    # 4. Longer test file (90 seconds) - multi-chunk test
    generate_wav_file(
        output_path=output_dir / "test_long_90s.wav",
        duration_seconds=90.0,
        sample_rate=16000,
        num_channels=1,
    )

    # 5. High quality test file (30 seconds, 44.1kHz stereo)
    generate_wav_file(
        output_path=output_dir / "test_hq_30s.wav",
        duration_seconds=30.0,
        sample_rate=44100,
        num_channels=2,
    )

    print("\n✅ All test audio files generated successfully!")
    print(f"📁 Location: {output_dir}")
    print("\nFiles:")
    for wav_file in sorted(output_dir.glob("test_*.wav")):
        size_kb = wav_file.stat().st_size / 1024
        print(f"  - {wav_file.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
