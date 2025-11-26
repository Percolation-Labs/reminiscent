"""
Tests for the REM extension registry pattern.

This tests the library extension pattern where users:
1. Import rem and get a FastAPI app
2. Extend it like normal FastAPI (routes, middleware)
3. Access app.mcp_server to add MCP tools/resources
4. Register models for schema generation
"""

import pytest
from pydantic import Field

from rem import (
    create_app,
    register_model,
    register_models,
    get_model_registry,
    clear_model_registry,
)
from rem.models.core import CoreModel


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear model registry before and after each test."""
    clear_model_registry()
    yield
    clear_model_registry()


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
