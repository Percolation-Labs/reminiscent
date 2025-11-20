"""
REM API Server - FastAPI application with integrated MCP server.

Design Pattern:
1. Create FastMCP server with create_mcp_server()
2. Get HTTP app with mcp.http_app(path="/", transport="http", stateless_http=True)
3. Mount on FastAPI at /api/v1/mcp
4. Add middleware in specific order (sessions, logging, auth, CORS)
5. Register API routers for v1 endpoints

Key Architecture Decisions 
- MCP mounted at /api/v1/mcp (not /mcp) for consistency
- Stateless HTTP prevents stale session errors across pod restarts
- Auth middleware excludes /api/auth and /api/v1/mcp/auth paths
- CORS added LAST so it runs FIRST (middleware runs in reverse)
- Combined lifespan for proper initialization order

Middleware Order (runs in reverse):
1. CORS (runs first - adds headers to all responses)
2. Auth (protects /api/v1/* paths)
3. Logging (logs all requests)
4. Sessions (OAuth state management)

Endpoints:
- /                          : API information
- /health                    : Health check
- /api/v1/mcp                : MCP endpoint (HTTP transport)
- /api/v1/chat/completions   : OpenAI-compatible chat completions (streaming & non-streaming)
- /api/v1/query              : REM query execution (TODO)
- /api/v1/resources          : Resource CRUD (TODO)
- /api/v1/moments            : Moment CRUD (TODO)
- /api/auth/*                : OAuth/OIDC authentication (TODO)
- /docs                      : OpenAPI documentation

Headers → AgentContext Mapping:
The following HTTP headers are automatically mapped to AgentContext fields:
- X-User-Id       → context.user_id          (user identifier)
- X-Tenant-Id     → context.tenant_id        (tenant identifier, required for REM)
- X-Session-Id    → context.session_id       (session/conversation identifier)
- X-Agent-Schema  → context.agent_schema_uri (agent schema to use)

Example:
    POST /api/v1/chat/completions
    X-Tenant-Id: acme-corp
    X-User-Id: user123
    X-Agent-Schema: rem-agents-query-agent

    {
      "model": "anthropic:claude-sonnet-4-5-20250929",
      "messages": [{"role": "user", "content": "Find Sarah's documents"}],
      "stream": true
    }

Running:
    # Development (auto-reload)
    uv run python -m rem.api.main

    # Production (Docker with hypercorn)
    hypercorn rem.api.main:app --bind 0.0.0.0:8000
"""

import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .mcp_router.server import create_mcp_server
from ..settings import settings


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Log all incoming HTTP requests and responses.

    Design Pattern:
    - Logs request method, path, client, user-agent
    - Logs response status, content-type, duration
    - Essential for debugging OAuth flow and MCP sessions
    """

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # Log incoming request
        client_host = request.client.host if request.client else "unknown"
        logger.info(
            f"→ REQUEST: {request.method} {request.url.path} | "
            f"Client: {client_host} | "
            f"User-Agent: {request.headers.get('user-agent', 'unknown')[:100]}"
        )

        # Process request
        response = await call_next(request)

        # Log response
        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"← RESPONSE: {request.method} {request.url.path} | "
            f"Status: {response.status_code} | "
            f"Duration: {duration_ms:.2f}ms"
        )

        return response


class SSEBufferingMiddleware(BaseHTTPMiddleware):
    """
    Disable proxy buffering for SSE responses.

    Adds X-Accel-Buffering: no header to prevent Nginx/Traefik
    from buffering Server-Sent Events (critical for MCP SSE transport).
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Disable buffering for SSE responses
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            response.headers["X-Accel-Buffering"] = "no"
            response.headers["Cache-Control"] = "no-cache"

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown tasks.
    OTEL instrumentation is initialized in agent factory when needed.
    """
    logger.info(f"Starting REM API ({settings.environment})")

    yield

    logger.info("Shutting down REM API")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.

    Design Pattern:
    1. Create MCP server
    2. Get HTTP app with stateless_http=True
    3. Combine lifespans (app + MCP)
    4. Create FastAPI with combined lifespan
    5. Add middleware (sessions, logging, auth, CORS) in specific order
    6. Define health endpoints
    7. Register API routers
    8. Mount MCP app

    Returns:
        Configured FastAPI application
    """
    # Create MCP server and get HTTP app
    # path="/" creates routes at root, then mount at /api/v1/mcp
    # transport="http" for MCP HTTP protocol
    # stateless_http=True prevents stale session errors (pods can restart)
    mcp_server = create_mcp_server()
    mcp_app = mcp_server.http_app(path="/", transport="http", stateless_http=True)

    # Disable trailing slash redirects (prevents 307 redirects that strip auth headers)
    if hasattr(mcp_app, "router"):
        mcp_app.router.redirect_slashes = False

    # Combine MCP and API lifespans
    # Explicit nesting ensures proper initialization order
    @asynccontextmanager
    async def combined_lifespan(app: FastAPI):
        async with lifespan(app):
            async with mcp_app.lifespan(app):
                yield

    app = FastAPI(
        title="REM API",
        description="Reactive Event-driven Model system for agentic AI",
        version="0.1.0",
        lifespan=combined_lifespan,
        root_path=settings.root_path if settings.root_path else "",
        redirect_slashes=False,  # Don't redirect /mcp/ -> /mcp
    )

    # Add session middleware for OAuth state management
    session_secret = settings.auth.session_secret or secrets.token_hex(32)
    if not settings.auth.session_secret:
        logger.warning(
            "AUTH__SESSION_SECRET not set - using generated key "
            "(sessions won't persist across restarts)"
        )

    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="rem_session",
        max_age=3600,  # 1 hour
        same_site="lax",
        https_only=settings.environment == "production",
    )

    # Add request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Add SSE buffering middleware (for MCP SSE transport)
    app.add_middleware(SSEBufferingMiddleware)

    # Add authentication middleware (if enabled)
    if settings.auth.enabled:
        from ..auth.middleware import AuthMiddleware

        app.add_middleware(
            AuthMiddleware,
            protected_paths=["/api/v1"],
            excluded_paths=["/api/auth", "/api/v1/mcp/auth"],
        )

    # Add CORS middleware LAST (runs first in middleware chain)
    # Must expose mcp-session-id header for MCP session management
    CORS_ORIGIN_WHITELIST = [
        "http://localhost:5173",  # Local development (Vite)
        "http://localhost:3000",  # Local development (React)
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGIN_WHITELIST,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*", "mcp-protocol-version", "mcp-session-id", "authorization"],
        expose_headers=["mcp-session-id"],
    )

    # Root endpoint
    @app.get("/")
    async def root():
        """API information endpoint."""
        # TODO: If auth enabled and no user, return 401 with WWW-Authenticate
        return {
            "name": "REM API",
            "version": "0.1.0",
            "mcp_endpoint": "/api/v1/mcp",
            "docs": "/docs",
        }

    # Health check endpoint
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy", "version": "0.1.0"}

    # Register API routers
    from .routers.chat import router as chat_router

    app.include_router(chat_router)

    # Register auth router (if enabled)
    if settings.auth.enabled:
        from .routers.auth import router as auth_router

        app.include_router(auth_router)

    # TODO: Register additional routers
    # from .routers.query import router as query_router
    # from .routers.resources import router as resources_router
    # from .routers.moments import router as moments_router
    #
    # app.include_router(query_router)
    # app.include_router(resources_router)
    # app.include_router(moments_router)

    # Add middleware to rewrite /api/v1/mcp to /api/v1/mcp/
    @app.middleware("http")
    async def mcp_path_rewrite_middleware(request: Request, call_next):
        """Rewrite /api/v1/mcp to /api/v1/mcp/ to handle Claude Desktop requests."""
        if request.url.path == "/api/v1/mcp":
            request.scope["path"] = "/api/v1/mcp/"
            request.scope["raw_path"] = b"/api/v1/mcp/"
        return await call_next(request)

    # Mount MCP app at /api/v1/mcp
    app.mount("/api/v1/mcp", mcp_app)

    return app


# Create application instance
app = create_app()


# Main entry point for uvicorn
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "rem.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
