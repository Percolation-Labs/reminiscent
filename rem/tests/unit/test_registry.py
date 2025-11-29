"""
Tests for the REM extension registry pattern.

This tests the library extension pattern where users:
1. Import rem and get a FastAPI app
2. Extend it like normal FastAPI (routes, middleware)
3. Access app.mcp_server to add MCP tools/resources
4. Register models for schema generation
5. Register schema paths for custom agent/evaluator discovery
"""

import os
import tempfile
from pathlib import Path

import pytest
from pydantic import Field

from rem import (
    create_app,
    register_model,
    register_models,
    get_model_registry,
    clear_model_registry,
    register_schema_path,
    register_schema_paths,
    get_schema_paths,
    clear_schema_path_registry,
)
from rem.models.core import CoreModel


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear model and schema path registries before and after each test."""
    clear_model_registry()
    clear_schema_path_registry()
    yield
    clear_model_registry()
    clear_schema_path_registry()


class TestCreateApp:
    """Test create_app returns a properly configured FastAPI app."""

    def test_create_app_returns_fastapi_instance(self):
        """create_app() returns a FastAPI instance."""
        from fastapi import FastAPI

        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_mcp_server_attribute(self):
        """App exposes mcp_server for extension."""
        app = create_app()
        assert hasattr(app, "mcp_server")
        # Should be a FastMCP instance
        assert app.mcp_server is not None

    def test_app_has_health_endpoint(self):
        """App has /health endpoint."""
        from fastapi.testclient import TestClient

        app = create_app()
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_app_can_add_custom_routes(self):
        """Users can add custom routes like normal FastAPI."""
        from fastapi.testclient import TestClient

        app = create_app()

        @app.get("/custom")
        async def custom_endpoint():
            return {"custom": True}

        client = TestClient(app)
        response = client.get("/custom")
        assert response.status_code == 200
        assert response.json() == {"custom": True}

    def test_app_can_include_router(self):
        """Users can include routers like normal FastAPI."""
        from fastapi import APIRouter
        from fastapi.testclient import TestClient

        app = create_app()
        router = APIRouter(prefix="/v1/custom")

        @router.get("/status")
        async def status():
            return {"status": "ok"}

        app.include_router(router)

        client = TestClient(app)
        response = client.get("/v1/custom/status")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestMCPServerExtension:
    """Test MCP server extension via app.mcp_server."""

    def test_can_add_mcp_tool(self):
        """Users can add MCP tools via app.mcp_server.tool()."""
        app = create_app()

        @app.mcp_server.tool()
        async def custom_tool(query: str) -> dict:
            """A custom MCP tool."""
            return {"query": query, "result": "custom"}

        # Verify tool was registered
        # FastMCP stores tools internally (attribute name may vary by version)
        tool_manager = app.mcp_server._tool_manager
        tools = getattr(tool_manager, "_tools", getattr(tool_manager, "tools", {}))
        assert "custom_tool" in [t.name for t in tools.values()]

    def test_can_add_mcp_resource(self):
        """Users can add MCP resources via app.mcp_server.resource()."""
        app = create_app()

        @app.mcp_server.resource("custom://config")
        async def get_config() -> str:
            """Get custom configuration."""
            return '{"setting": "value"}'

        # Verify resource was registered
        assert any(
            "custom://config" in str(r)
            for r in app.mcp_server._resource_manager._resources.keys()
        )


class TestModelRegistry:
    """Test model registration for schema generation."""

    def test_register_model_decorator(self):
        """@register_model decorator registers a model."""

        @register_model
        class TestEntity(CoreModel):
            name: str = Field(..., json_schema_extra={"entity_key": True})
            value: int

        registry = get_model_registry()
        models = registry.get_models(include_core=False)

        assert "TestEntity" in models
        assert models["TestEntity"].model is TestEntity

    def test_register_model_with_options(self):
        """register_model() accepts table_name and entity_key_field options."""

        @register_model(table_name="custom_table", entity_key_field="name")
        class AnotherEntity(CoreModel):
            name: str
            data: str

        registry = get_model_registry()
        models = registry.get_models(include_core=False)

        assert "AnotherEntity" in models
        assert models["AnotherEntity"].table_name == "custom_table"
        assert models["AnotherEntity"].entity_key_field == "name"

    def test_register_model_direct_call(self):
        """register_model() can be called directly (not as decorator)."""

        class DirectEntity(CoreModel):
            name: str

        register_model(DirectEntity)

        registry = get_model_registry()
        models = registry.get_models(include_core=False)

        assert "DirectEntity" in models

    def test_register_models_multiple(self):
        """register_models() registers multiple models at once."""

        class ModelA(CoreModel):
            name: str

        class ModelB(CoreModel):
            name: str

        class ModelC(CoreModel):
            name: str

        register_models(ModelA, ModelB, ModelC)

        registry = get_model_registry()
        models = registry.get_models(include_core=False)

        assert "ModelA" in models
        assert "ModelB" in models
        assert "ModelC" in models

    def test_get_models_includes_core_by_default(self):
        """get_models() includes core REM models by default."""
        registry = get_model_registry()
        models = registry.get_models(include_core=True)

        # Should include core models
        assert "Resource" in models
        assert "User" in models
        assert "Moment" in models

    def test_get_models_can_exclude_core(self):
        """get_models(include_core=False) excludes core models."""

        @register_model
        class CustomOnly(CoreModel):
            name: str

        registry = get_model_registry()
        models = registry.get_models(include_core=False)

        assert "CustomOnly" in models
        assert "Resource" not in models

    def test_clear_registry(self):
        """clear_model_registry() removes all registered models."""

        @register_model
        class ToClear(CoreModel):
            name: str

        registry = get_model_registry()
        assert "ToClear" in registry.get_models(include_core=False)

        clear_model_registry()

        assert "ToClear" not in registry.get_models(include_core=False)


class TestIntegrationPattern:
    """Test the full extension pattern as documented."""

    def test_full_extension_pattern(self):
        """
        Test the complete extension pattern:
        1. Create app from rem
        2. Add custom routes
        3. Add custom MCP tools
        4. Register custom models
        """
        from fastapi import APIRouter
        from fastapi.testclient import TestClient

        # 1. Create app
        app = create_app()

        # 2. Add custom routes
        @app.get("/my-endpoint")
        async def my_endpoint():
            return {"custom": True}

        router = APIRouter(prefix="/v1/ext")

        @router.get("/data")
        async def get_data():
            return {"data": [1, 2, 3]}

        app.include_router(router)

        # 3. Add custom MCP tool
        @app.mcp_server.tool()
        async def analyze(text: str) -> dict:
            """Analyze text."""
            return {"length": len(text)}

        # 4. Register custom model
        @register_model
        class Analysis(CoreModel):
            name: str = Field(..., json_schema_extra={"entity_key": True})
            result: str
            score: float

        # Verify everything works
        client = TestClient(app)

        # Custom endpoint works
        assert client.get("/my-endpoint").json() == {"custom": True}

        # Router endpoint works
        assert client.get("/v1/ext/data").json() == {"data": [1, 2, 3]}

        # MCP tool registered
        tool_manager = app.mcp_server._tool_manager
        tools = getattr(tool_manager, "_tools", getattr(tool_manager, "tools", {}))
        assert "analyze" in [t.name for t in tools.values()]

        # Model registered
        registry = get_model_registry()
        assert "Analysis" in registry.get_models(include_core=False)


class TestSchemaPathRegistry:
    """Test schema path registration for custom agent/evaluator discovery."""

    def test_register_schema_path(self):
        """register_schema_path() adds a path to the registry."""
        register_schema_path("/app/custom-agents")

        paths = get_schema_paths()
        assert "/app/custom-agents" in paths

    def test_register_schema_paths_multiple(self):
        """register_schema_paths() adds multiple paths at once."""
        register_schema_paths("/app/agents", "/app/evaluators", "/shared/schemas")

        paths = get_schema_paths()
        assert "/app/agents" in paths
        assert "/app/evaluators" in paths
        assert "/shared/schemas" in paths

    def test_paths_maintain_order(self):
        """Paths are returned in registration order."""
        register_schema_path("/first")
        register_schema_path("/second")
        register_schema_path("/third")

        paths = get_schema_paths()
        # First three should be in order (env var paths may follow)
        assert paths.index("/first") < paths.index("/second")
        assert paths.index("/second") < paths.index("/third")

    def test_no_duplicate_paths(self):
        """Registering the same path twice doesn't create duplicates."""
        register_schema_path("/app/agents")
        register_schema_path("/app/agents")
        register_schema_path("/app/agents")

        paths = get_schema_paths()
        assert paths.count("/app/agents") == 1

    def test_clear_schema_path_registry(self):
        """clear_schema_path_registry() removes all registered paths."""
        register_schema_path("/app/agents")
        register_schema_path("/app/evaluators")

        clear_schema_path_registry()

        # After clearing, only env var paths should remain (if any)
        paths = get_schema_paths()
        assert "/app/agents" not in paths
        assert "/app/evaluators" not in paths

    def test_schema_paths_from_env_var(self, monkeypatch):
        """SCHEMA__PATHS env var adds paths to search."""
        # This tests the integration with settings
        # Note: The env var is read at settings initialization time,
        # so we test via the path_list property directly
        from rem.settings import SchemaSettings

        settings = SchemaSettings(paths="/env/path1;/env/path2")
        assert "/env/path1" in settings.path_list
        assert "/env/path2" in settings.path_list

    def test_env_var_empty_paths_filtered(self):
        """Empty paths in SCHEMA__PATHS are filtered out."""
        from rem.settings import SchemaSettings

        settings = SchemaSettings(paths="/valid;;/another;")
        assert "" not in settings.path_list
        assert "/valid" in settings.path_list
        assert "/another" in settings.path_list


class TestSchemaLoaderWithCustomPaths:
    """Test schema loading with custom paths."""

    def test_load_schema_from_custom_path(self):
        """Schema loader finds schemas in registered custom paths."""
        from rem.utils.schema_loader import load_agent_schema

        # Create a temporary directory with a custom schema
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_content = """
type: object
description: Test custom agent
properties:
  result:
    type: string
"""
            schema_path = Path(tmpdir) / "my-custom-agent.yaml"
            schema_path.write_text(schema_content)

            # Register the temp directory
            register_schema_path(tmpdir)

            # Load should find it
            schema = load_agent_schema("my-custom-agent")
            assert schema["description"] == "Test custom agent"
            assert schema["properties"]["result"]["type"] == "string"

    def test_custom_path_takes_precedence_over_package(self):
        """Custom paths are searched before package resources."""
        from rem.utils.schema_loader import load_agent_schema

        # Create a custom schema that shadows a built-in one
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a schema with same name as built-in "rem" agent
            schema_content = """
type: object
description: CUSTOM rem agent (should take precedence)
properties:
  custom_field:
    type: string
"""
            schema_path = Path(tmpdir) / "rem.yaml"
            schema_path.write_text(schema_content)

            # Register BEFORE the test
            register_schema_path(tmpdir)

            # Load should find custom version
            schema = load_agent_schema("rem", use_cache=False)
            assert "CUSTOM" in schema["description"]

    def test_agents_subdirectory_in_custom_path(self):
        """Schema loader checks agents/ subdirectory in custom paths."""
        from rem.utils.schema_loader import load_agent_schema

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create agents subdirectory
            agents_dir = Path(tmpdir) / "agents"
            agents_dir.mkdir()

            schema_content = """
type: object
description: Agent in subdirectory
properties:
  output:
    type: string
"""
            schema_path = agents_dir / "subdir-agent.yaml"
            schema_path.write_text(schema_content)

            register_schema_path(tmpdir)

            schema = load_agent_schema("subdir-agent")
            assert schema["description"] == "Agent in subdirectory"

    def test_evaluators_subdirectory_in_custom_path(self):
        """Schema loader checks evaluators/ subdirectory in custom paths."""
        from rem.utils.schema_loader import load_agent_schema

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create evaluators subdirectory
            evaluators_dir = Path(tmpdir) / "evaluators"
            evaluators_dir.mkdir()

            schema_content = """
type: object
description: Custom evaluator
properties:
  score:
    type: number
"""
            schema_path = evaluators_dir / "custom-eval.yaml"
            schema_path.write_text(schema_content)

            register_schema_path(tmpdir)

            schema = load_agent_schema("custom-eval")
            assert schema["description"] == "Custom evaluator"


class TestModelsSettings:
    """Test MODELS__IMPORT_MODULES settings for downstream model discovery."""

    def test_models_settings_default_empty(self):
        """ModelsSettings defaults to empty import_modules."""
        from rem.settings import ModelsSettings

        settings = ModelsSettings()
        assert settings.import_modules == ""
        assert settings.module_list == []

    def test_models_settings_single_module(self):
        """ModelsSettings parses single module correctly."""
        from rem.settings import ModelsSettings

        settings = ModelsSettings(import_modules="models")
        assert settings.module_list == ["models"]

    def test_models_settings_multiple_modules(self):
        """ModelsSettings parses semicolon-separated modules."""
        from rem.settings import ModelsSettings

        settings = ModelsSettings(import_modules="models;myapp.entities;custom.models")
        assert settings.module_list == ["models", "myapp.entities", "custom.models"]

    def test_models_settings_filters_empty_strings(self):
        """ModelsSettings filters out empty strings from module list."""
        from rem.settings import ModelsSettings

        settings = ModelsSettings(import_modules="models;;another;")
        assert "" not in settings.module_list
        assert settings.module_list == ["models", "another"]

    def test_models_settings_strips_whitespace(self):
        """ModelsSettings strips whitespace from module names."""
        from rem.settings import ModelsSettings

        settings = ModelsSettings(import_modules="  models ; another  ;  third  ")
        assert settings.module_list == ["models", "another", "third"]

    def test_import_model_modules_function(self, monkeypatch):
        """_import_model_modules successfully imports valid modules."""
        from rem.cli.commands.schema import _import_model_modules
        from rem.settings import ModelsSettings

        # Create a settings object with a valid module
        mock_settings = ModelsSettings(import_modules="json")

        # Patch the global settings.models
        import rem.settings
        original_models = rem.settings.settings.models
        try:
            # Need to patch the models attribute at module level
            object.__setattr__(rem.settings.settings, "models", mock_settings)
            imported = _import_model_modules()
            assert "json" in imported
        finally:
            object.__setattr__(rem.settings.settings, "models", original_models)

    def test_import_model_modules_handles_missing_module(self, monkeypatch):
        """_import_model_modules gracefully handles missing modules."""
        from rem.cli.commands.schema import _import_model_modules
        from rem.settings import ModelsSettings

        # Create a settings object with a nonexistent module
        mock_settings = ModelsSettings(import_modules="nonexistent_module_xyz")

        import rem.settings
        original_models = rem.settings.settings.models
        try:
            object.__setattr__(rem.settings.settings, "models", mock_settings)
            imported = _import_model_modules()
            assert "nonexistent_module_xyz" not in imported
        finally:
            object.__setattr__(rem.settings.settings, "models", original_models)
