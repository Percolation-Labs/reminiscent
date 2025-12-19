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
- /api/v1/query              : REM query execution (rem-dialect or natural-language)
- /api/v1/resources          : Resource CRUD (TODO)
- /api/v1/moments            : Moment CRUD (TODO)
- /api/auth/*                : OAuth/OIDC authentication
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

import importlib.metadata
import secrets
import sys
import time

# Get package version for API responses
try:
    __version__ = importlib.metadata.version("remdb")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0-dev"
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .mcp_router.server import create_mcp_server
from ..settings import settings

# Configure loguru based on settings
# Remove default handler and add one with configured level
logger.remove()

# Configure level icons - only warnings and errors get visual indicators
logger.level("DEBUG", icon=" ")
logger.level("INFO", icon=" ")
logger.level("WARNING", icon="🟠")
logger.level("ERROR", icon="🔴")
logger.level("CRITICAL", icon="🔴")

logger.add(
    sys.stderr,
    level=settings.api.log_level.upper(),
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | {level.icon} <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Log all incoming HTTP requests and responses.

    Design Pattern:
    - Logs request method, path, client, user-agent
    - Logs response status, content-type, duration
    - Essential for debugging OAuth flow and MCP sessions
    - Health checks and 404s logged at DEBUG level to reduce noise
    - Scanner/exploit attempts (common vulnerability probes) logged at DEBUG
    """

    # Paths to log at DEBUG level (health checks, probes)
    DEBUG_PATHS = {"/health", "/healthz", "/ready", "/readyz", "/livez"}

    # Path patterns that indicate vulnerability scanners (log at DEBUG)
    SCANNER_PATTERNS = (
        "/vendor/",      # PHP composer exploits
        "/.git/",        # Git config exposure
        "/.env",         # Environment file exposure
        "/wp-",          # WordPress exploits
        "/phpunit/",     # PHPUnit RCE
        "/eval-stdin",   # PHP eval exploits
        "/console/",     # Console exposure
        "/actuator/",    # Spring Boot actuator
        "/debug/",       # Debug endpoints
        "/admin/",       # Admin panel probes (when we don't have one)
    )

    def _should_log_at_debug(self, path: str, status_code: int) -> bool:
        """Determine if request should be logged at DEBUG level."""
        # Health checks
        if path in self.DEBUG_PATHS:
            return True
        # 404 responses (not found - includes scanner probes)
        if status_code == 404:
            return True
        # Known scanner patterns
        if any(pattern in path for pattern in self.SCANNER_PATTERNS):
            return True
        return False

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        path = request.url.path

        # Log incoming request (preliminary - may adjust after response)
        client_host = request.client.host if request.client else "unknown"
        user_agent = request.headers.get('user-agent', 'unknown')[:100]

        # Extract auth info for logging (first 8 chars of token for debugging)
        auth_header = request.headers.get('authorization', '')
        auth_preview = ""
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            auth_preview = f"Bearer {token[:8]}..." if len(token) > 8 else f"Bearer {token}"

        # Process request
        response = await call_next(request)

        # Extract user info set by auth middleware (after processing)
        user = getattr(request.state, "user", None)
        user_id = user.get("id", "none")[:12] if user else "anon"
        user_email = user.get("email", "") if user else ""

        # Determine log level based on path AND response status
        duration_ms = (time.time() - start_time) * 1000
        use_debug = self._should_log_at_debug(path, response.status_code)
        log_fn = logger.debug if use_debug else logger.info

        # Build user info string
        user_info = f"user={user_id}"
        if user_email:
            user_info += f" ({user_email})"
        if auth_preview:
            user_info += f" | auth={auth_preview}"

        # Log request and response together with auth info
        log_fn(
            f"→ REQUEST: {request.method} {path} | "
            f"Client: {client_host} | "
            f"{user_info}"
        )
        log_fn(
            f"← RESPONSE: {request.method} {path} | "
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
    OTEL instrumentation must be initialized at startup before any agents are created.
    """
    logger.info(f"Starting REM API ({settings.environment})")

    # Initialize OTEL instrumentation if enabled
    # Must be done at startup to instrument Pydantic AI before any agents are created
    if settings.otel.enabled:
        from ..agentic.otel.setup import setup_instrumentation

        setup_instrumentation()

    # Check database configuration
    if not settings.postgres.enabled:
        logger.warning(
            "Running in NO-DATABASE mode - database connection disabled. "
            "Agent execution works with file-based schemas, but session storage "
            "and history lookups are unavailable. Enable database with POSTGRES__ENABLED=true"
        )
    else:
        # Log database host only - never log credentials
        logger.info(f"Database enabled: {settings.postgres.host}:{settings.postgres.port}/{settings.postgres.database}")

    yield

    logger.info("Shutting down REM API")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application with MCP server.

    The returned app exposes `app.mcp_server` (FastMCP instance) for adding
    custom tools, resources, and prompts:

        app = create_app()

        @app.mcp_server.tool()
        async def my_tool(query: str) -> dict:
            '''Custom MCP tool.'''
            return {"result": query}

        @app.mcp_server.resource("custom://data")
        async def my_resource() -> str:
            '''Custom resource.'''
            return '{"data": "value"}'

    Design Pattern:
    1. Create MCP server
    2. Get HTTP app with stateless_http=True
    3. Combine lifespans (app + MCP)
    4. Create FastAPI with combined lifespan
    5. Add middleware (sessions, logging, auth, CORS) in specific order
    6. Define health endpoints
    7. Register API routers
    8. Mount MCP app
    9. Expose mcp_server on app for extension

    Returns:
        Configured FastAPI application with .mcp_server attribute
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
        title=f"{settings.app_name} API",
        description=f"{settings.app_name} - Resources Entities Moments system for agentic AI",
        version=__version__,
        lifespan=combined_lifespan,
        root_path=settings.root_path if settings.root_path else "",
        redirect_slashes=False,  # Don't redirect /mcp/ -> /mcp
    )

    # Add request logging middleware
    app.add_middleware(RequestLoggingMiddleware)

    # Add SSE buffering middleware (for MCP SSE transport)
    app.add_middleware(SSEBufferingMiddleware)

    # Add Anonymous Tracking & Rate Limiting (Runs AFTER Auth if Auth is enabled)
    # Must be added BEFORE AuthMiddleware in code to be INNER in the stack
    from .middleware.tracking import AnonymousTrackingMiddleware
    app.add_middleware(AnonymousTrackingMiddleware)

    # Add authentication middleware
    # Always load middleware for dev token support, but allow anonymous when auth disabled
    from ..auth.middleware import AuthMiddleware

    app.add_middleware(
        AuthMiddleware,
        protected_paths=["/api/v1", "/api/admin"],
        excluded_paths=["/api/auth", "/api/dev", "/api/v1/mcp/auth", "/api/v1/slack"],
        # Allow anonymous when auth is disabled, otherwise use setting
        allow_anonymous=(not settings.auth.enabled) or settings.auth.allow_anonymous,
        # MCP requires auth only when auth is fully enabled
        mcp_requires_auth=settings.auth.enabled and settings.auth.mcp_requires_auth,
    )

    # Add session middleware for OAuth state management
    # Must be added AFTER AuthMiddleware in code so it runs BEFORE (middleware runs in reverse)
    # AuthMiddleware needs request.session to be available
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

    # Add CORS middleware LAST (runs first in middleware chain)
    # Must expose mcp-session-id header for MCP session management
    CORS_ORIGIN_WHITELIST = [
        "http://localhost:3000",  # Local development (React)
        "http://localhost:5000",  # Local development (Flask/other)
        "http://localhost:5173",  # Local development (Vite)
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
            "name": f"{settings.app_name} API",
            "version": __version__,
            "mcp_endpoint": "/api/v1/mcp",
            "docs": "/docs",
        }

    # Health check endpoint
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy", "version": __version__}

    # Register API routers
    from .routers.chat import router as chat_router
    from .routers.models import router as models_router
    from .routers.messages import router as messages_router
    from .routers.feedback import router as feedback_router
    from .routers.admin import router as admin_router
    from .routers.shared_sessions import router as shared_sessions_router
    from .routers.query import router as query_router

    app.include_router(chat_router)
    app.include_router(models_router)
    # shared_sessions_router MUST be before messages_router
    # because messages_router has /sessions/{session_id} which would match
    # before the more specific /sessions/shared-with-me routes
    app.include_router(shared_sessions_router)
    app.include_router(messages_router)
    app.include_router(feedback_router)
    app.include_router(admin_router)
    app.include_router(query_router)

    # Register auth router (if enabled)
    if settings.auth.enabled:
        from .routers.auth import router as auth_router

        app.include_router(auth_router)

    # Register dev router (non-production only)
    if settings.environment != "production":
        from .routers.dev import router as dev_router

        app.include_router(dev_router)

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

    # Expose MCP server on app for extension
    # Users can add tools/resources/prompts via app.mcp_server
    app.mcp_server = mcp_server  # type: ignore[attr-defined]

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
