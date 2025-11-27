"""
REM - Resources, Entities, Moments.

A bio-inspired memory system for agentic AI, built on FastAPI.

Usage (API mode):
    from rem import create_app

    # Create REM app (FastAPI with MCP server pre-configured)
    app = create_app()

    # Extend like any FastAPI app
    @app.get("/my-endpoint")
    async def my_endpoint():
        return {"custom": True}

    # Add routers
    app.include_router(my_router)

    # Access MCP server directly (FastMCP instance)
    @app.mcp_server.tool()
    async def my_custom_tool(query: str) -> dict:
        '''Custom MCP tool for my application.'''
        return {"result": "..."}

    @app.mcp_server.resource("custom://config")
    async def get_config() -> str:
        '''Custom resource.'''
        return '{"setting": "value"}'

Usage (model registration - works with or without API):
    import rem
    from rem.models.core import CoreModel

    @rem.register_model
    class CustomEntity(CoreModel):
        name: str
        custom_field: str

    # Or register multiple:
    rem.register_models(ModelA, ModelB)

    # Then schema generation includes your models:
    # rem db schema generate
"""

from .registry import (
    # Model registration
    register_model,
    register_models,
    get_model_registry,
    clear_model_registry,
    # Schema path registration
    register_schema_path,
    register_schema_paths,
    get_schema_paths,
    get_schema_path_registry,
    clear_schema_path_registry,
)


def create_app():
    """
    Create and return a FastAPI application with REM features pre-configured.

    The returned app has:
    - MCP server mounted at /api/v1/mcp
    - Chat completions endpoint at /api/v1/chat/completions
    - Health check at /health
    - OpenAPI docs at /docs

    The app exposes `app.mcp_server` (FastMCP instance) for adding custom
    tools, resources, and prompts.

    Returns:
        FastAPI application with .mcp_server attribute

    Example:
        from rem import create_app

        app = create_app()

        # Add custom endpoint
        @app.get("/custom")
        async def custom():
            return {"custom": True}

        # Add custom MCP tool
        @app.mcp_server.tool()
        async def my_tool(query: str) -> dict:
            return {"result": query}
    """
    from .api.main import create_app as _create_app
    return _create_app()


# Lazy app instance - created on first access
_app = None


def get_app():
    """
    Get or create the default REM app instance.

    For most cases, use create_app() to get a fresh instance.
    This is provided for convenience in simple scripts.
    """
    global _app
    if _app is None:
        _app = create_app()
    return _app


__all__ = [
    # App creation
    "create_app",
    "get_app",
    # Model registration
    "register_model",
    "register_models",
    "get_model_registry",
    "clear_model_registry",
    # Schema path registration
    "register_schema_path",
    "register_schema_paths",
    "get_schema_paths",
    "get_schema_path_registry",
    "clear_schema_path_registry",
]
