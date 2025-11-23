# Test Audio Files

This directory contains WAV files for testing the AudioProvider.

## Generated Test Files

These files are synthesized using tone sequences that simulate speech patterns:

- **test_short_3s.wav** (94 KB) - 3 second file for quick tests
- **test_medium_10s.wav** (313 KB) - 10 second file for basic chunking tests
- **test_standard_30s.wav** (938 KB) - 30 second file for typical use cases
- **test_long_90s.wav** (2.8 MB) - 90 second file for multi-chunk tests
- **test_hq_30s.wav** (2.6 MB) - 30 second stereo file at 44.1kHz

All files use 16-bit PCM encoding, mono (except test_hq_30s.wav which is stereo).

## Regenerating Test Files

To regenerate the test files:

```bash
python generate_test_audio.py
```

## Real Audio Samples

For testing with real speech, you can download samples from:

- **Mozilla Common Voice**: https://commonvoice.mozilla.org/en/datasets
- **LibriSpeech**: https://www.openslr.org/12
- **VoxForge**: http://www.voxforge.org/

Example download (requires manual download due to licensing):

```bash
# Download a short clip from Mozilla Common Voice (requires account)
# Or use any short WAV file < 1MB for testing
```

## Usage in Tests

```python
from pathlib import Path

# Get test audio file
test_audio_dir = Path(__file__).parent / "data" / "audio"
short_audio = test_audio_dir / "test_short_3s.wav"

# Read bytes for testing
audio_bytes = short_audio.read_bytes()
```
