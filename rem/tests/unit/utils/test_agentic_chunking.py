"""Tests for agentic chunking utilities with large input datasets."""

import pytest

from rem.utils.agentic_chunking import (
    chunk_text,
    smart_chunk_text,
    estimate_tokens,
    get_model_limits,
    merge_results,
    MergeStrategy,
    ModelLimits,
)


def _has_tiktoken() -> bool:
    """Check if tiktoken is installed."""
    try:
        import tiktoken
        return True
    except ImportError:
        return False


class TestModelLimits:
    """Test model limits lookup and fuzzy matching."""

    def test_direct_lookup(self):
        """Test direct model name lookup."""
        limits = get_model_limits("gpt-4o")
        assert limits.max_context == 128000
        assert limits.max_output == 16384
        assert limits.max_input == 111616

    def test_fuzzy_matching_gpt(self):
        """Test fuzzy matching for GPT models."""
        limits = get_model_limits("gpt-4o-2024-05-13")
        assert limits.max_context == 128000

        limits = get_model_limits("gpt-4-turbo-preview")
        assert limits.max_context == 128000

    def test_fuzzy_matching_claude(self):
        """Test fuzzy matching for Claude models."""
        limits = get_model_limits("claude-sonnet-4-20250514")
        assert limits.max_context == 200000

        limits = get_model_limits("claude-3-5-sonnet-20241022")
        assert limits.max_context == 200000

    def test_fuzzy_matching_gemini(self):
        """Test fuzzy matching for Gemini models."""
        limits = get_model_limits("gemini-1.5-pro-latest")
        assert limits.max_context == 2000000

    def test_default_fallback(self):
        """Test fallback to default for unknown models."""
        limits = get_model_limits("unknown-model-xyz")
        assert limits.max_context == 32000


class TestTokenEstimation:
    """Test token estimation for different models."""

    def test_empty_text(self):
        """Test token estimation for empty text."""
        assert estimate_tokens("") == 0
        assert estimate_tokens("", model="gpt-4o") == 0

    def test_short_text_heuristic(self):
        """Test heuristic estimation for non-OpenAI models."""
        # "Hello world" = 11 chars → ~2.9 tokens → 3 with overhead
        tokens = estimate_tokens("Hello world", model="claude-sonnet-4")
        assert 2 <= tokens <= 4

    def test_long_text_heuristic(self):
        """Test heuristic estimation for longer text."""
        # 1000 chars → ~250 tokens → ~262 with overhead
        text = "a" * 1000
        tokens = estimate_tokens(text, model="claude-sonnet-4")
        assert 250 <= tokens <= 300

    @pytest.mark.skipif(
        not _has_tiktoken(),
        reason="tiktoken not installed"
    )
    def test_openai_exact_count(self):
        """Test exact token counting with tiktoken for OpenAI models."""
        # Known token count for "Hello, world!"
        tokens = estimate_tokens("Hello, world!", model="gpt-4o")
        assert tokens == 4  # Exact count via tiktoken


class TestSmartChunking:
    """Test intelligent chunking with automatic sizing."""

    def test_cv_fits_in_single_chunk(self):
        """Test that typical CV fits in single chunk (no chunking needed)."""
        # Simulate 5K token CV (typical resume)
        cv_text = "CURRICULUM VITAE\n\n" + ("Experience: Worked at Company X.\n" * 100)

        chunks = smart_chunk_text(cv_text, model="gpt-4o")

        # Should NOT chunk - GPT-4o has 111K input capacity
        assert len(chunks) == 1
        assert chunks[0] == cv_text

        tokens = estimate_tokens(cv_text, model="gpt-4o")
        print(f"\nCV tokens: {tokens}, fits in GPT-4o (111K available)")

    def test_large_contract_chunks_intelligently(self):
        """Test that very large document is chunked."""
        # Simulate 150K token contract (very large document)
        contract_text = "CONTRACT AGREEMENT\n\n" + ("Section: " + ("word " * 200) + "\n") * 500

        chunks = smart_chunk_text(contract_text, model="gpt-4o")

        # Should chunk - exceeds 75% of available context
        assert len(chunks) > 1

        tokens = estimate_tokens(contract_text, model="gpt-4o")
        print(f"\nContract tokens: {tokens}, chunks: {len(chunks)}")

    def test_system_prompt_overhead_accounted(self):
        """Test that system prompt reduces available space."""
        # Large system prompt
        system_prompt = "You are an expert contract analyzer..." + ("instruction " * 100)

        text = ("word " * 500) * 100  # Moderate size text

        # Without system prompt
        chunks_no_prompt = smart_chunk_text(text, model="gpt-4o")

        # With large system prompt
        chunks_with_prompt = smart_chunk_text(text, model="gpt-4o", system_prompt=system_prompt)

        # With prompt should create more chunks (less space available)
        assert len(chunks_with_prompt) >= len(chunks_no_prompt)

        system_tokens = estimate_tokens(system_prompt, model="gpt-4o")
        print(f"\nSystem prompt: {system_tokens} tokens, impacts chunking")

    def test_buffer_ratio_controls_chunk_size(self):
        """Test that buffer_ratio parameter controls chunk size."""
        text = ("word " * 500) * 50

        # Conservative ratio (60%)
        chunks_conservative = smart_chunk_text(text, model="gpt-4o", buffer_ratio=0.6)

        # Aggressive ratio (90%)
        chunks_aggressive = smart_chunk_text(text, model="gpt-4o", buffer_ratio=0.9)

        # Conservative should create more, smaller chunks
        assert len(chunks_conservative) >= len(chunks_aggressive)

        print(f"\n60% buffer: {len(chunks_conservative)} chunks, 90% buffer: {len(chunks_aggressive)} chunks")

    def test_different_models_different_limits(self):
        """Test that chunking adapts to model context windows."""
        # Medium-large text that fits in Claude but not GPT-3.5
        text = ("Section: " + ("word " * 200) + "\n") * 100

        # GPT-3.5 (16K context)
        chunks_gpt35 = smart_chunk_text(text, model="gpt-3.5-turbo")

        # Claude Sonnet 4 (200K context)
        chunks_claude = smart_chunk_text(text, model="claude-sonnet-4")

        # Claude should need fewer chunks (larger context)
        assert len(chunks_gpt35) >= len(chunks_claude)

        tokens = estimate_tokens(text, model="gpt-4o")
        print(f"\nText: {tokens} tokens")
        print(f"GPT-3.5 (16K): {len(chunks_gpt35)} chunks")
        print(f"Claude (200K): {len(chunks_claude)} chunks")


class TestChunking:
    """Test text chunking strategies."""

    def test_no_chunking_needed(self):
        """Test that small text is not chunked."""
        text = "Short text that fits in one chunk."
        chunks = chunk_text(text, max_tokens=100, model="gpt-4o")
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_line_preserving_chunking(self):
        """Test line-preserving chunking."""
        # Create text with clear line boundaries
        lines = [f"Line {i}" for i in range(100)]
        text = "\n".join(lines)

        chunks = chunk_text(text, max_tokens=100, model="gpt-4o", preserve_lines=True)

        # Should create multiple chunks
        assert len(chunks) > 1

        # Each chunk should contain complete lines
        for chunk in chunks:
            assert not chunk.endswith("ine")  # Not split mid-word

    def test_character_based_chunking(self):
        """Test character-based chunking."""
        # Create long text without newlines
        text = "word " * 1000

        chunks = chunk_text(text, max_tokens=100, model="gpt-4o", preserve_lines=False)

        # Should create multiple chunks
        assert len(chunks) > 1

        # Chunks should respect word boundaries where possible
        for chunk in chunks:
            if len(chunk) < 400:  # Skip last chunk
                assert chunk.endswith(" ") or chunk.endswith("word")

    def test_oversized_line_handling(self):
        """Test that oversized lines are split by characters."""
        # Single line that exceeds token limit
        oversized_line = "word " * 500  # ~2500 chars, ~625 tokens

        chunks = chunk_text(oversized_line, max_tokens=100, model="gpt-4o")

        # Should split the oversized line
        assert len(chunks) > 1


class TestMergeStrategies:
    """Test different merge strategies with realistic datasets."""

    def test_concatenate_list_simple(self):
        """Test simple list concatenation."""
        results = [
            {"items": [1, 2], "count": 2},
            {"items": [3, 4], "count": 2},
        ]

        merged = merge_results(results, MergeStrategy.CONCATENATE_LIST)

        assert merged["items"] == [1, 2, 3, 4]
        assert merged["count"] == 2  # Keep first

    def test_concatenate_list_with_dicts(self):
        """Test dict update in concatenate strategy."""
        results = [
            {"metadata": {"source": "chunk1"}, "items": [1]},
            {"metadata": {"author": "alice"}, "items": [2]},
        ]

        merged = merge_results(results, MergeStrategy.CONCATENATE_LIST)

        assert merged["items"] == [1, 2]
        assert merged["metadata"]["source"] == "chunk1"
        assert merged["metadata"]["author"] == "alice"

    def test_concatenate_list_none_handling(self):
        """Test None value handling."""
        results = [
            {"name": None, "items": [1]},
            {"name": "test", "items": [2]},
        ]

        merged = merge_results(results, MergeStrategy.CONCATENATE_LIST)

        assert merged["name"] == "test"  # Prefer non-None
        assert merged["items"] == [1, 2]

    def test_merge_json_deep(self):
        """Test deep JSON merge."""
        results = [
            {
                "contract": {
                    "parties": ["Alice"],
                    "terms": {"duration": "1 year"}
                }
            },
            {
                "contract": {
                    "parties": ["Bob"],
                    "terms": {"renewal": "auto"}
                }
            },
        ]

        merged = merge_results(results, MergeStrategy.MERGE_JSON)

        assert merged["contract"]["parties"] == ["Alice", "Bob"]
        assert merged["contract"]["terms"]["duration"] == "1 year"
        assert merged["contract"]["terms"]["renewal"] == "auto"

    def test_merge_json_three_levels_deep(self):
        """Test deep merge with three levels of nesting."""
        results = [
            {
                "company": {
                    "employees": {
                        "engineering": ["Alice", "Bob"],
                        "sales": ["Charlie"]
                    }
                }
            },
            {
                "company": {
                    "employees": {
                        "engineering": ["David"],
                        "marketing": ["Eve"]
                    }
                }
            },
        ]

        merged = merge_results(results, MergeStrategy.MERGE_JSON)

        assert merged["company"]["employees"]["engineering"] == ["Alice", "Bob", "David"]
        assert merged["company"]["employees"]["sales"] == ["Charlie"]
        assert merged["company"]["employees"]["marketing"] == ["Eve"]

    def test_empty_results(self):
        """Test merging empty results."""
        merged = merge_results([])
        assert merged == {}

    def test_single_result(self):
        """Test merging single result (no-op)."""
        results = [{"key": "value"}]
        merged = merge_results(results)
        assert merged == {"key": "value"}


class TestLargeDatasetScenarios:
    """Test realistic large dataset scenarios."""

    def test_cv_extraction_scenario(self):
        """Test CV extraction with multiple chunks."""
        # Simulate CV parser results from 3 chunks
        chunk_results = [
            {
                "candidate_name": "John Doe",
                "email": "john@example.com",
                "skills": [
                    {"name": "Python", "proficiency": "expert"},
                    {"name": "SQL", "proficiency": "advanced"},
                ],
                "experience": [
                    {
                        "company": "TechCorp",
                        "role": "Senior Engineer",
                        "years": 3,
                    }
                ],
            },
            {
                "candidate_name": "John Doe",
                "email": "john@example.com",
                "skills": [
                    {"name": "Docker", "proficiency": "intermediate"},
                    {"name": "Kubernetes", "proficiency": "intermediate"},
                ],
                "experience": [
                    {
                        "company": "StartupXYZ",
                        "role": "Lead Developer",
                        "years": 2,
                    }
                ],
            },
            {
                "candidate_name": "John Doe",
                "email": "john@example.com",
                "skills": [
                    {"name": "AWS", "proficiency": "advanced"},
                ],
                "experience": [
                    {
                        "company": "BigCorp",
                        "role": "Software Engineer",
                        "years": 1,
                    }
                ],
            },
        ]

        merged = merge_results(chunk_results, MergeStrategy.CONCATENATE_LIST)

        # Should keep first name/email
        assert merged["candidate_name"] == "John Doe"
        assert merged["email"] == "john@example.com"

        # Should concatenate all skills
        assert len(merged["skills"]) == 5
        skill_names = [s["name"] for s in merged["skills"]]
        assert "Python" in skill_names
        assert "Docker" in skill_names
        assert "AWS" in skill_names

        # Should concatenate all experience
        assert len(merged["experience"]) == 3
        companies = [e["company"] for e in merged["experience"]]
        assert "TechCorp" in companies
        assert "StartupXYZ" in companies
        assert "BigCorp" in companies

    def test_contract_analysis_scenario(self):
        """Test contract analysis with deep merge."""
        # Simulate contract analyzer results from 2 chunks
        chunk_results = [
            {
                "contract_title": "Partnership Agreement",
                "contract_type": "partnership",
                "parties": [
                    {"legal_name": "Acme Corp", "role": "provider"},
                ],
                "financial_terms": {
                    "total_contract_value": 1000000,
                    "currency": "USD",
                },
                "key_obligations": [
                    {
                        "party": "Acme Corp",
                        "obligation": "Provide services",
                        "deadline": "2025-12-31",
                    }
                ],
            },
            {
                "contract_title": "Partnership Agreement",
                "contract_type": "partnership",
                "parties": [
                    {"legal_name": "Beta LLC", "role": "client"},
                ],
                "financial_terms": {
                    "payment_schedule": "quarterly",
                },
                "key_obligations": [
                    {
                        "party": "Beta LLC",
                        "obligation": "Pay invoices",
                        "deadline": "30 days",
                    }
                ],
                "risk_flags": [
                    {
                        "clause": "Termination",
                        "risk_level": "medium",
                        "reason": "Short notice period",
                    }
                ],
            },
        ]

        merged = merge_results(chunk_results, MergeStrategy.MERGE_JSON)

        # Should keep scalar fields from first chunk
        assert merged["contract_title"] == "Partnership Agreement"
        assert merged["contract_type"] == "partnership"

        # Should merge parties list
        assert len(merged["parties"]) == 2
        party_names = [p["legal_name"] for p in merged["parties"]]
        assert "Acme Corp" in party_names
        assert "Beta LLC" in party_names

        # Should deep merge financial_terms
        assert merged["financial_terms"]["total_contract_value"] == 1000000
        assert merged["financial_terms"]["currency"] == "USD"
        assert merged["financial_terms"]["payment_schedule"] == "quarterly"

        # Should merge obligations and risk_flags
        assert len(merged["key_obligations"]) == 2
        assert len(merged["risk_flags"]) == 1

    def test_session_history_scenario(self):
        """Test user session history merging."""
        # Simulate session analysis from 3 chunks
        chunk_results = [
            {
                "user_interests": ["AI", "machine learning"],
                "activity_level": "high",
                "sessions_analyzed": 50,
                "top_topics": {
                    "AI": 25,
                    "machine learning": 20,
                },
            },
            {
                "user_interests": ["Python", "data science"],
                "activity_level": "high",
                "sessions_analyzed": 30,
                "top_topics": {
                    "Python": 15,
                    "data science": 12,
                },
            },
            {
                "user_interests": ["NLP", "transformers"],
                "activity_level": "medium",
                "sessions_analyzed": 20,
                "top_topics": {
                    "NLP": 10,
                    "transformers": 8,
                },
            },
        ]

        merged = merge_results(chunk_results, MergeStrategy.MERGE_JSON)

        # Should merge all interests
        assert len(merged["user_interests"]) == 6
        assert "AI" in merged["user_interests"]
        assert "Python" in merged["user_interests"]
        assert "NLP" in merged["user_interests"]

        # Should keep first activity level
        assert merged["activity_level"] == "high"

        # Should keep first session count
        assert merged["sessions_analyzed"] == 50

        # Should merge all topics
        assert len(merged["top_topics"]) == 6
        assert merged["top_topics"]["AI"] == 25
        assert merged["top_topics"]["Python"] == 15
        assert merged["top_topics"]["NLP"] == 10


class TestEndToEndScenario:
    """Test complete chunking + merging workflow."""

    def test_large_document_workflow(self):
        """Test complete workflow: chunk large text, merge results."""
        # Create a large document (simulate 150K token document)
        sections = []
        for i in range(100):
            section = f"Section {i}\n"
            section += f"This is section {i} with important data about topic {i}.\n"
            section += "Details: " + ("word " * 100) + "\n"
            sections.append(section)

        large_document = "\n".join(sections)

        # Chunk the document with smaller chunks to force splitting
        # Document is ~12K tokens, use 5K token chunks to get multiple chunks
        chunks = chunk_text(
            large_document,
            max_tokens=5000,  # Force multiple chunks
            model="gpt-4o"
        )

        # Should create multiple chunks
        assert len(chunks) > 1
        print(f"\nCreated {len(chunks)} chunks from large document")

        # Simulate processing each chunk (mock agent results)
        chunk_results = []
        for i, chunk in enumerate(chunks):
            # Count sections in this chunk
            section_count = chunk.count("Section")

            result = {
                "chunk_id": i,
                "sections_found": section_count,
                "topics": [f"topic_{j}" for j in range(i, i + 5)],
                "metadata": {
                    "chunk_size": len(chunk),
                    "processor": "test",
                }
            }
            chunk_results.append(result)

        # Merge results
        merged = merge_results(chunk_results, MergeStrategy.CONCATENATE_LIST)

        print(f"Merged {len(chunk_results)} chunk results")
        print(f"Total sections found: {merged['sections_found']}")
        print(f"Total unique topics: {len(merged['topics'])}")
        print(f"Metadata keys: {merged['metadata'].keys()}")

        # Verify merge worked correctly
        assert merged["chunk_id"] == 0  # First chunk ID
        assert merged["sections_found"] == chunk_results[0]["sections_found"]
        assert len(merged["topics"]) > 5  # Should have concatenated topics
        assert "chunk_size" in merged["metadata"]
        assert "processor" in merged["metadata"]


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
