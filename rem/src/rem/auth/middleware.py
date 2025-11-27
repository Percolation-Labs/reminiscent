"""
OAuth Authentication Middleware for FastAPI.

Protects API endpoints by requiring valid session.
Supports anonymous access with rate limiting when allow_anonymous=True.
MCP endpoints are always protected unless explicitly disabled.

Design Pattern:
- Check session for user on protected paths
- MCP paths always require authentication (protected service)
- If allow_anonymous=True: Allow unauthenticated requests (marked as ANONYMOUS tier)
- If allow_anonymous=False: Return 401 for API calls, redirect browsers to login
- Exclude auth endpoints and public paths

Access Modes (configured in settings.auth):
- enabled=true, allow_anonymous=true: Auth available, anonymous gets rate-limited access
- enabled=true, allow_anonymous=false: Auth required for all requests
- enabled=false: Middleware not loaded, all requests pass through
- mcp_requires_auth=true (default): MCP always requires login regardless of allow_anonymous
- mcp_requires_auth=false: MCP follows normal allow_anonymous rules (dev only)

Usage:
    from rem.auth.middleware import AuthMiddleware

    app.add_middleware(
        AuthMiddleware,
        protected_paths=["/api/v1"],
        excluded_paths=["/api/auth", "/health"],
        allow_anonymous=settings.auth.allow_anonymous,
        mcp_requires_auth=settings.auth.mcp_requires_auth,
    )
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from loguru import logger


class AuthMiddleware(BaseHTTPMiddleware):
    """
    Authentication middleware using session-based auth.

    Checks for valid user session on protected paths.
    Compatible with OAuth flows from auth router.
    Supports anonymous access with rate limiting.
    MCP endpoints are always protected unless explicitly disabled.
    """

    def __init__(
        self,
        app,
        protected_paths: list[str] | None = None,
        excluded_paths: list[str] | None = None,
        allow_anonymous: bool = True,
        mcp_requires_auth: bool = True,
        mcp_path: str = "/api/v1/mcp",
    ):
        """
        Initialize auth middleware.

        Args:
            app: ASGI application
            protected_paths: Paths that require authentication
            excluded_paths: Paths to exclude from auth check
            allow_anonymous: Allow unauthenticated requests (rate-limited)
            mcp_requires_auth: Always require auth for MCP (protected service)
            mcp_path: Path prefix for MCP endpoints
        """
        super().__init__(app)
        self.protected_paths = protected_paths or ["/api/v1"]
        self.excluded_paths = excluded_paths or ["/api/auth", "/health", "/docs", "/openapi.json"]
        self.allow_anonymous = allow_anonymous
        self.mcp_requires_auth = mcp_requires_auth
        self.mcp_path = mcp_path

    async def dispatch(self, request: Request, call_next):
        """
        Check authentication for protected paths.

        Args:
            request: HTTP request
            call_next: Next middleware in chain

        Returns:
            Response (401/redirect if unauthorized, normal response if authorized/anonymous)
        """
        path = request.url.path

        # Check if path is protected
        is_protected = any(path.startswith(p) for p in self.protected_paths)
        is_excluded = any(path.startswith(p) for p in self.excluded_paths)

        # Check if this is an MCP path (paid service, always requires auth)
        is_mcp_path = path.startswith(self.mcp_path)

        # Skip auth check for excluded paths
        if not is_protected or is_excluded:
            return await call_next(request)

        # Check for valid session
        user = request.session.get("user")

        if user:
            # Authenticated user - add to request state
            request.state.user = user
            request.state.is_anonymous = False
            return await call_next(request)

        # No user session - check if MCP path requires auth
        if is_mcp_path and self.mcp_requires_auth:
            # MCP is a protected service - always require authentication
            logger.warning(f"Unauthorized MCP access attempt: {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required for MCP. Please login to use this service.",
                    "code": "MCP_AUTH_REQUIRED",
                },
                headers={
                    "WWW-Authenticate": 'Bearer realm="REM MCP"',
                },
            )

        # No user session - handle anonymous access for non-MCP paths
        if self.allow_anonymous:
            # Allow anonymous access - rate limiting handled downstream
            request.state.user = None
            request.state.is_anonymous = True
            logger.debug(f"Anonymous access: {path}")
            return await call_next(request)

        # Anonymous not allowed - require authentication
        logger.warning(f"Unauthorized access attempt: {path}")

        # Return 401 for API requests (JSON)
        accept = request.headers.get("accept", "")
        if "application/json" in accept or path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
                headers={
                    "WWW-Authenticate": 'Bearer realm="REM API"',
                },
            )

        # Redirect to login for browser requests
        return RedirectResponse(url="/api/auth/google/login", status_code=302)
