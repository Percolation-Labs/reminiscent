"""
Tests for the /models endpoint.
"""

import pytest
from fastapi.testclient import TestClient

from rem.api.main import app
from rem.api.routers.models import AVAILABLE_MODELS


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestModelsEndpoint:
    """Tests for GET /api/v1/models endpoint."""

    def test_list_models_returns_all_models(self, client):
        """Should return list of all available models."""
        response = client.get("/api/v1/models")
        assert response.status_code == 200

        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == len(AVAILABLE_MODELS)

    def test_list_models_has_openai_models(self, client):
        """Should include OpenAI GPT-4.1 series."""
        response = client.get("/api/v1/models")
        data = response.json()

        model_ids = [m["id"] for m in data["data"]]
        assert "openai:gpt-4.1" in model_ids
        assert "openai:gpt-4.1-mini" in model_ids
        assert "openai:gpt-4.1-nano" in model_ids

    def test_list_models_has_anthropic_models(self, client):
        """Should include Anthropic Claude 4.5 series."""
        response = client.get("/api/v1/models")
        data = response.json()

        model_ids = [m["id"] for m in data["data"]]
        # Check for latest Claude models
        assert any("claude-opus-4-5" in m for m in model_ids)
        assert any("claude-sonnet-4-5" in m for m in model_ids)
        assert any("claude-haiku-4-5" in m for m in model_ids)

    def test_list_models_has_google_models(self, client):
        """Should include Google Gemini models."""
        response = client.get("/api/v1/models")
        data = response.json()

        model_ids = [m["id"] for m in data["data"]]
        assert any("gemini" in m for m in model_ids)
        assert any("gemma" in m for m in model_ids)

    def test_model_has_required_fields(self, client):
        """Each model should have required fields."""
        response = client.get("/api/v1/models")
        data = response.json()

        for model in data["data"]:
            assert "id" in model
            assert "object" in model
            assert model["object"] == "model"
            assert "created" in model
            assert "owned_by" in model
            # Provider should be extracted from id
            provider = model["id"].split(":")[0]
            assert model["owned_by"] == provider

    def test_model_ids_follow_provider_format(self, client):
        """Model IDs should follow provider:model format."""
        response = client.get("/api/v1/models")
        data = response.json()

        for model in data["data"]:
            model_id = model["id"]
            assert ":" in model_id, f"Model ID '{model_id}' should contain ':'"
            parts = model_id.split(":", 1)
            assert len(parts) == 2
            assert parts[0] in ["openai", "anthropic", "google", "cerebras"]


class TestGetModelEndpoint:
    """Tests for GET /api/v1/models/{model_id} endpoint."""

    def test_get_existing_model(self, client):
        """Should return specific model info."""
        response = client.get("/api/v1/models/openai:gpt-4.1")
        assert response.status_code == 200

        data = response.json()
        assert data["id"] == "openai:gpt-4.1"
        assert data["owned_by"] == "openai"
        assert data["context_window"] == 1047576

    def test_get_nonexistent_model(self, client):
        """Should return 404 for unknown model."""
        response = client.get("/api/v1/models/unknown:fake-model")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_model_with_path_params(self, client):
        """Should handle model IDs with special characters."""
        # Test model with date suffix
        response = client.get("/api/v1/models/anthropic:claude-sonnet-4-5-20250929")
        assert response.status_code == 200
        assert response.json()["id"] == "anthropic:claude-sonnet-4-5-20250929"
