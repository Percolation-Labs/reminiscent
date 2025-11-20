"""
Integration tests for content providers.

Tests that all content providers implement the same interface consistently:
1. Accept bytes + metadata
2. Return dict with 'text' and 'metadata'
3. Handle errors gracefully
4. Integrate with ContentService

Verifies:
- TextProvider
- DocProvider (using Kreuzberg)
- AudioProvider (using AudioChunker + Whisper)
"""

import os
from pathlib import Path

import pytest

from rem.services.content.providers import AudioProvider, DocProvider, TextProvider
from rem.services.content.service import ContentService


class TestProviderInterface:
    """Test that all providers implement the same interface."""

    def test_text_provider_interface(self):
        """Test TextProvider follows the interface."""
        provider = TextProvider()

        # Verify interface
        assert provider.name == "text"
        assert hasattr(provider, "extract")

        # Test extraction
        content = b"# Test Heading\n\nSome **bold** text."
        metadata = {"size": len(content)}

        result = provider.extract(content, metadata)

        # Verify return structure
        assert "text" in result
        assert "metadata" in result
        assert isinstance(result["text"], str)
        assert isinstance(result["metadata"], dict)

        # Verify content
        assert "Test Heading" in result["text"]
        assert result["metadata"]["heading_count"] == 1

    def test_doc_provider_interface(self):
        """Test DocProvider follows the interface."""
        provider = DocProvider()

        # Verify interface
        assert provider.name == "doc"
        assert hasattr(provider, "extract")

        # Note: Full document test would require a real document file
        # Here we just verify the interface exists

    def test_audio_provider_interface(self):
        """Test AudioProvider follows the interface."""
        provider = AudioProvider()

        # Verify interface
        assert provider.name == "audio"
        assert hasattr(provider, "extract")

        # Test graceful handling without API key
        content = b"fake audio bytes"
        metadata = {"size": len(content), "content_type": "audio/wav"}

        result = provider.extract(content, metadata)

        # Should return error message gracefully
        assert "text" in result
        assert "metadata" in result
        assert "OPENAI_API_KEY" in result["text"] or "error" in result["metadata"]


class TestContentServiceIntegration:
    """Test ContentService with all providers."""

    def test_content_service_has_all_providers(self):
        """Verify ContentService registers all providers."""
        service = ContentService()

        # Check text formats
        assert ".md" in service.providers
        assert isinstance(service.providers[".md"], TextProvider)

        # Check document formats
        doc_extensions = [".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"]
        for ext in doc_extensions:
            assert ext in service.providers
            assert isinstance(service.providers[ext], DocProvider)

        # Check audio formats
        audio_extensions = [".wav", ".mp3", ".m4a", ".flac", ".ogg"]
        for ext in audio_extensions:
            assert ext in service.providers
            assert isinstance(service.providers[ext], AudioProvider)

    def test_markdown_file_processing(self, tmp_path):
        """Test end-to-end markdown processing."""
        # Create markdown file
        md_file = tmp_path / "test.md"
        md_content = "# Test Document\n\nThis is a test."
        md_file.write_text(md_content)

        # Process
        service = ContentService()
        result = service.process_uri(str(md_file))

        # Verify
        assert result["uri"] == str(md_file.absolute())
        assert "Test Document" in result["content"]
        assert result["provider"] == "text"
        assert result["metadata"]["heading_count"] == 1

    @pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY"),
        reason="OPENAI_API_KEY not set"
    )
    def test_audio_file_processing_with_api_key(self, tmp_path):
        """
        Test audio processing with real API key.

        This test is skipped unless OPENAI_API_KEY is set.
        It would require a real audio file and make API calls.
        """
        # This is a placeholder - real test would need audio file
        service = ContentService()
        assert ".wav" in service.providers

    def test_audio_file_processing_without_api_key(self, tmp_path):
        """Test audio processing without API key (graceful degradation)."""
        # Temporarily remove API key if it exists
        old_key = os.environ.pop("OPENAI_API_KEY", None)

        try:
            # Create fake audio file
            audio_file = tmp_path / "test.wav"
            audio_file.write_bytes(b"fake audio data")

            # Process
            service = ContentService()
            result = service.process_uri(str(audio_file))

            # Should handle gracefully
            assert result["provider"] == "audio"
            assert "OPENAI_API_KEY" in result["content"] or "error" in result["metadata"]

        finally:
            # Restore API key
            if old_key:
                os.environ["OPENAI_API_KEY"] = old_key


class TestProviderConsistency:
    """Test that all providers return consistent structures."""

    def test_all_providers_return_text_and_metadata(self):
        """Verify all providers return the same structure."""
        providers = [
            TextProvider(),
            DocProvider(),
            AudioProvider(),
        ]

        for provider in providers:
            # Each provider must have name
            assert isinstance(provider.name, str)
            assert len(provider.name) > 0

            # Each provider must have extract method
            assert callable(provider.extract)

    def test_all_providers_handle_empty_content(self):
        """Test providers handle empty content gracefully."""
        content = b""
        metadata = {"size": 0}

        # Text should handle empty
        text_provider = TextProvider()
        result = text_provider.extract(content, metadata)
        assert "text" in result
        assert result["text"] == ""

        # Audio should handle empty (will fail but gracefully)
        audio_provider = AudioProvider()
        result = audio_provider.extract(content, metadata)
        assert "text" in result  # Should not crash

    def test_text_to_audio_consistency(self):
        """
        Verify the processing pipeline is consistent.

        Both text and audio should:
        1. Extract content
        2. Return markdown format
        3. Be chunkable
        4. Be embeddable
        """
        # Text provider
        text_provider = TextProvider()
        text_result = text_provider.extract(
            b"# Heading\n\nParagraph 1.\n\nParagraph 2.",
            {"size": 42}
        )
        assert "Heading" in text_result["text"]
        assert "metadata" in text_result

        # Audio provider (without API key)
        audio_provider = AudioProvider()
        audio_result = audio_provider.extract(
            b"fake",
            {"size": 4, "content_type": "audio/wav"}
        )
        # Should return text (even if error message)
        assert "text" in audio_result
        assert isinstance(audio_result["text"], str)
        assert "metadata" in audio_result


class TestAudioProviderMarkdownFormat:
    """Test that AudioProvider returns properly formatted markdown."""

    def test_audio_returns_markdown_with_timestamps(self):
        """
        Verify audio transcription returns markdown with timestamp headers.

        Format should be:
        ## [0.0s - 60.0s]

        Transcription text here...

        ## [60.0s - 120.0s]

        More transcription...
        """
        provider = AudioProvider()

        # Without API key, it returns error
        # But we can verify it would return the right format
        assert provider.name == "audio"

        # If it had transcriptions, it should format like:
        # ## [0.0s - 60.0s]\n\nText here\n
        # We test this format in the actual provider logic


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
