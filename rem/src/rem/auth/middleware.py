"""
OAuth Authentication Middleware for FastAPI.

Protects API endpoints by requiring valid session.
Redirects unauthenticated requests to login page.

Design Pattern:
- Check session for user on protected paths
- Return 401 for API calls (JSON)
- Redirect to login for browser requests (HTML)
- Exclude auth endpoints and public paths

Usage:
    from rem.auth.middleware import AuthMiddleware

    app.add_middleware(
        AuthMiddleware,
        protected_paths=["/api/v1"],
        excluded_paths=["/api/auth", "/health"],
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
    """

    def __init__(
        self,
        app,
        protected_paths: list[str] | None = None,
        excluded_paths: list[str] | None = None,
    ):
        """
        Initialize auth middleware.

        Args:
            app: ASGI application
            protected_paths: Paths that require authentication
            excluded_paths: Paths to exclude from auth check
        """
        super().__init__(app)
        self.protected_paths = protected_paths or ["/api/v1"]
        self.excluded_paths = excluded_paths or ["/api/auth", "/health", "/docs", "/openapi.json"]

    async def dispatch(self, request: Request, call_next):
        """
        Check authentication for protected paths.

        Args:
            request: HTTP request
            call_next: Next middleware in chain

        Returns:
            Response (401/redirect if unauthorized, normal response if authorized)
        """
        path = request.url.path

        # Check if path is protected
        is_protected = any(path.startswith(p) for p in self.protected_paths)
        is_excluded = any(path.startswith(p) for p in self.excluded_paths)

        # Skip auth check for excluded paths
        if not is_protected or is_excluded:
            return await call_next(request)

        # Check for valid session
        user = request.session.get("user")
        if not user:
            logger.warning(f"Unauthorized access attempt: {path}")

            # Return 401 for API requests (JSON)
            # Check Accept header to determine if client expects JSON
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
            # TODO: Store original URL for post-login redirect
            return RedirectResponse(url="/api/auth/google/login", status_code=302)

        # Add user to request state for downstream handlers
        request.state.user = user

        return await call_next(request)
