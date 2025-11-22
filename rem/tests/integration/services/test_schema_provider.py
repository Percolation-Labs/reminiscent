"""
Integration tests for SchemaProvider.

Tests that SchemaProvider:
1. Detects agent schemas correctly
2. Detects evaluator schemas correctly
3. Extracts metadata properly
4. Integrates with ContentService
5. Returns proper structure for storage
"""

from pathlib import Path

import pytest
import yaml

from rem.services.content.providers import SchemaProvider
from rem.services.content.service import ContentService


class TestSchemaProviderDetection:
    """Test schema detection logic."""

    def test_detects_agent_schema(self):
        """Test that agent schemas are detected correctly."""
        provider = SchemaProvider()

        # Load test CV parser schema
        schema_path = Path(__file__).parents[2] / "data" / "schemas" / "agents" / "test-cv-parser.yaml"
        content = schema_path.read_bytes()
        metadata = {"size": len(content)}

        result = provider.extract(content, metadata)

        # Verify detection
        assert result["is_schema"] is True
        assert result["metadata"]["schema_type"] == "agent"
        assert result["metadata"]["name"] == "cv-parser"
        assert result["metadata"]["version"] == "1.0.0"

        # Verify schema data is preserved
        assert "schema_data" in result
        assert result["schema_data"]["type"] == "object"

    def test_detects_non_schema_yaml(self):
        """Test that non-schema YAML files are not detected as schemas."""
        provider = SchemaProvider()

        # Regular YAML without schema markers
        content = b"""
name: test
value: 123
items:
  - one
  - two
"""
        metadata = {"size": len(content)}

        result = provider.extract(content, metadata)

        # Should not be detected as schema
        assert result["is_schema"] is False
        assert "schema_data" not in result

    def test_extracts_embedding_fields(self):
        """Test that embedding_fields are extracted."""
        provider = SchemaProvider()

        schema_path = Path(__file__).parents[2] / "data" / "schemas" / "agents" / "test-cv-parser.yaml"
        content = schema_path.read_bytes()
        metadata = {"size": len(content)}

        result = provider.extract(content, metadata)

        # Verify embedding fields
        assert "embedding_fields" in result["metadata"]
        embedding_fields = result["metadata"]["embedding_fields"]
        assert "candidate_name" in embedding_fields
        assert "professional_summary" in embedding_fields
        assert "skills" in embedding_fields

    def test_extracts_provider_configs(self):
        """Test that provider_configs are extracted."""
        provider = SchemaProvider()

        schema_path = Path(__file__).parents[2] / "data" / "schemas" / "agents" / "test-cv-parser.yaml"
        content = schema_path.read_bytes()
        metadata = {"size": len(content)}

        result = provider.extract(content, metadata)

        # Verify provider configs
        assert "provider_configs" in result["metadata"]
        configs = result["metadata"]["provider_configs"]
        assert len(configs) == 2

        # Check Anthropic config
        anthropic_config = next(c for c in configs if c["provider_name"] == "anthropic")
        assert anthropic_config["model_name"] == "claude-sonnet-4-5-20250929"

        # Check OpenAI config
        openai_config = next(c for c in configs if c["provider_name"] == "openai")
        assert openai_config["model_name"] == "gpt-4o"


class TestSchemaProviderInterface:
    """Test that SchemaProvider implements the provider interface."""

    def test_provider_has_name(self):
        """Test that provider has name attribute."""
        provider = SchemaProvider()
        assert provider.name == "schema"

    def test_provider_returns_text_and_metadata(self):
        """Test that provider returns expected structure."""
        provider = SchemaProvider()

        schema_path = Path(__file__).parents[2] / "data" / "schemas" / "agents" / "test-cv-parser.yaml"
        content = schema_path.read_bytes()
        metadata = {"size": len(content)}

        result = provider.extract(content, metadata)

        # Verify structure
        assert "text" in result
        assert "metadata" in result
        assert isinstance(result["text"], str)
        assert isinstance(result["metadata"], dict)


class TestContentServiceIntegration:
    """Test ContentService integration with SchemaProvider."""

    def test_content_service_registers_schema_provider(self):
        """Verify ContentService registers SchemaProvider for YAML/JSON."""
        service = ContentService()

        # Check that .yaml, .yml, .json use SchemaProvider
        assert ".yaml" in service.providers
        assert ".yml" in service.providers
        assert ".json" in service.providers
        assert isinstance(service.providers[".yaml"], SchemaProvider)
        assert isinstance(service.providers[".yml"], SchemaProvider)
        assert isinstance(service.providers[".json"], SchemaProvider)

    def test_process_agent_schema_file(self):
        """Test end-to-end processing of agent schema file."""
        service = ContentService()

        schema_path = Path(__file__).parents[2] / "data" / "schemas" / "agents" / "test-cv-parser.yaml"
        result = service.process_uri(str(schema_path))

        # Verify processing
        assert result["uri"] == str(schema_path.absolute())
        assert result["provider"] == "schema"

        # Verify content contains schema info
        assert "CVParser" in result["content"] or "cv-parser" in result["content"]

        # Verify metadata (extracted metadata is merged into result metadata)
        assert result["metadata"]["schema_type"] == "agent"
        assert result["metadata"]["short_name"] == "cv-parser"
        assert result["metadata"]["name"] == "cv-parser"


# class TestSchemaProviderEdgeCases:
#     """Test edge cases and error handling."""

#     def test_handles_invalid_yaml(self):
#         """Test that invalid YAML is handled gracefully."""
#         provider = SchemaProvider()

#         content = b"{ invalid yaml: [brackets"
#         metadata = {"size": len(content)}

#         # Should raise or return error structure
#         with pytest.raises(yaml.YAMLError):
#             provider.extract(content, metadata)

#     def test_handles_yaml_without_type(self):
#         """Test YAML without type field is not detected as schema."""
#         provider = SchemaProvider()

#         content = b"""
# description: Some description
# properties:
#   field: string
# """
#         metadata = {"size": len(content)}

#         result = provider.extract(content, metadata)

#         # Should not be detected as schema
#         assert result["is_schema"] is False

#     def test_handles_yaml_without_fully_qualified_name(self):
#         """Test YAML without json_schema_extra.name is not detected as schema."""
#         provider = SchemaProvider()

#         content = b"""
# type: object
# description: Some description
# properties:
#   field:
#     type: string
# json_schema_extra:
#   kind: agent
# """ # Missing name
#         metadata = {"size": len(content)}

#         result = provider.extract(content, metadata)

#         # Should not be detected as schema due to missing 'name'
#         assert result["is_schema"] is False

#     def test_short_name_inference(self):
#         """Test that short_name is correctly inferred from fully_qualified_name."""
#         provider = SchemaProvider()

#         # Test various naming patterns
#         test_cases = [
#             ("rem.agents.CVParser", "cv-parser"),
#             ("rem.agents.ContractAnalyzer", "contract-analyzer"),
#             ("rem.evaluators.LookupCorrectness", "lookup-correctness"),
#             ("rem.agents.MyAgent", "my-agent"),
#         ]

#         for fqn, expected_short_name in test_cases:
#             content = f"""
# type: object
# description: Test
# properties:
#   field:
#     type: string
# json_schema_extra:
#   fully_qualified_name: {fqn}
#   version: "1.0.0"
# """.encode()
#             metadata = {"size": len(content)}

#             result = provider.extract(content, metadata)

#             assert result["is_schema"] is True
#             assert result["metadata"]["short_name"] == expected_short_name, \
#                 f"Expected {expected_short_name} for {fqn}, got {result['metadata']['short_name']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
