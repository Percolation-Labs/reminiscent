"""
Authentication Middleware for FastAPI.

Protects API endpoints by requiring valid authentication.
Supports multiple auth methods: JWT, API Key, Session, Dev Token.
Anonymous access with rate limiting when allow_anonymous=True.
MCP endpoints are always protected unless explicitly disabled.

Design Pattern:
- API Key (X-API-Key): Access control guardrail, NOT user identity
- JWT (Authorization: Bearer): Primary method for user identity
- Dev token: Non-production testing (starts with "dev_")
- Session: Backward compatibility for browser-based auth
- MCP paths always require authentication (protected service)

Authentication Flow:
1. If API key enabled: Validate X-API-Key header (access gate)
2. Check JWT token for user identity (primary)
3. Check dev token for testing (non-production only)
4. Check session for user (backward compatibility)
5. If allow_anonymous=True: Allow as anonymous (rate-limited)
6. If allow_anonymous=False: Return 401 / redirect to login

IMPORTANT: API key validates ACCESS, JWT identifies USER.
Both can be required: API key for access + JWT for user identity.

Access Modes (configured in settings.auth):
- enabled=true, allow_anonymous=true: Auth available, anonymous gets rate-limited access
- enabled=true, allow_anonymous=false: Auth required for all requests
- enabled=false: Middleware not loaded, all requests pass through
- mcp_requires_auth=true (default): MCP always requires login regardless of allow_anonymous
- mcp_requires_auth=false: MCP follows normal allow_anonymous rules (dev only)

API Key Authentication (configured in settings.api):
- api_key_enabled=true: Require X-API-Key header for access
- api_key: The secret key to validate against
- API key is an ACCESS GATE, not user identity - JWT still needed for user

Dev Token Support (non-production only):
- GET /api/auth/dev/token returns a Bearer token for test-user
- Include as: Authorization: Bearer dev_<signature>
- Only works when ENVIRONMENT != "production"

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

from ..settings import settings


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

    def _check_api_key(self, request: Request) -> dict | None:
        """
        Check for valid X-API-Key header.

        Returns:
            API key user dict if valid, None otherwise
        """
        # Only check if API key auth is enabled
        if not settings.api.api_key_enabled:
            return None

        # Check for X-API-Key header
        api_key = request.headers.get("x-api-key")
        if not api_key:
            return None

        # Validate against configured API key
        if settings.api.api_key and api_key == settings.api.api_key:
            logger.debug("X-API-Key authenticated")
            return {
                "id": "api-key-user",
                "email": "api@rem.local",
                "name": "API Key User",
                "provider": "api-key",
                "tenant_id": "default",
                "tier": "pro",  # API key users get full access
                "roles": ["user"],
            }

        # Invalid API key
        logger.warning("Invalid X-API-Key provided")
        return None

    def _check_jwt_token(self, request: Request) -> dict | None:
        """
        Check for valid JWT in Authorization header.

        Returns:
            User dict if valid JWT, None otherwise
        """
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Strip "Bearer "

        # Skip dev tokens (handled separately)
        if token.startswith("dev_"):
            return None

        # Verify JWT token
        from .jwt import get_jwt_service
        jwt_service = get_jwt_service()
        user = jwt_service.verify_token(token)

        if user:
            logger.debug(f"JWT authenticated: {user.get('email')}")
            return user

        return None

    def _check_dev_token(self, request: Request) -> dict | None:
        """
        Check for valid dev token in Authorization header (non-production only).

        Returns:
            Test user dict if valid dev token, None otherwise
        """
        if settings.environment == "production":
            return None

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]  # Strip "Bearer "

        # Only check dev tokens (start with "dev_")
        if not token.startswith("dev_"):
            return None

        # Verify dev token
        from ..api.routers.dev import verify_dev_token
        if verify_dev_token(token):
            logger.debug("Dev token authenticated as test-user")
            return {
                "id": "test-user",
                "email": "test@rem.local",
                "name": "Test User",
                "provider": "dev",
                "tenant_id": "default",
                "tier": "pro",  # Give test user pro tier for full access
                "roles": ["admin"],
            }

        return None

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

        # API key validation (access control, not user identity)
        # API key is a guardrail for access - JWT identifies the actual user
        if settings.api.api_key_enabled:
            api_key = request.headers.get("x-api-key")
            if not api_key:
                logger.debug(f"Missing X-API-Key for: {path}")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "API key required. Include X-API-Key header."},
                    headers={"WWW-Authenticate": 'ApiKey realm="REM API"'},
                )
            if api_key != settings.api.api_key:
                logger.warning(f"Invalid X-API-Key for: {path}")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid API key"},
                    headers={"WWW-Authenticate": 'ApiKey realm="REM API"'},
                )
            logger.debug("X-API-Key validated for access")
            # API key valid - continue to check JWT for user identity

        # Check for JWT token in Authorization header (primary user identity)
        jwt_user = self._check_jwt_token(request)
        if jwt_user:
            request.state.user = jwt_user
            request.state.is_anonymous = False
            return await call_next(request)

        # Check for dev token (non-production only)
        dev_user = self._check_dev_token(request)
        if dev_user:
            request.state.user = dev_user
            request.state.is_anonymous = False
            return await call_next(request)

        # Check for valid session (backward compatibility)
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
