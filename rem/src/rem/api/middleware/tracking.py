"""
Anonymous User Tracking & Rate Limiting Middleware.

Handles:
1. Anonymous Identity: Generates/Validates 'rem_anon_id' cookie.
2. Context Injection: Sets request.state.anon_id.
3. Rate Limiting: Enforces tenant-aware tiered limits via RateLimitService.
"""

import hmac
import hashlib
import uuid
import secrets
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ...services.postgres.service import PostgresService
from ...services.rate_limit import RateLimitService
from ...models.entities.user import UserTier
from ...settings import settings


class AnonymousTrackingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for anonymous user tracking and rate limiting.
    
    Design Pattern:
    - Uses a secure, signed cookie for anonymous ID.
    - Enforces rate limits before request processing.
    - Injects anon_id into request state.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        # Secret for signing cookies (should be in settings, fallback for safety)
        self.secret_key = settings.auth.session_secret or "fallback-secret-change-me"
        self.cookie_name = "rem_anon_id"
        
        # Dedicated DB service for this middleware (one pool per app instance)
        self.db = PostgresService()
        self.rate_limiter = RateLimitService(self.db)
        
        # Excluded paths (health checks, static assets, auth callbacks)
        self.excluded_paths = {
            "/health", 
            "/docs", 
            "/openapi.json", 
            "/favicon.ico",
            "/api/auth", # Don't rate limit auth flow heavily
        }

    async def dispatch(self, request: Request, call_next):
        # 0. Skip excluded paths
        if any(request.url.path.startswith(p) for p in self.excluded_paths):
            return await call_next(request)

        # 1. Lazy DB Connection
        if not self.db.pool:
            # Note: simple lazy init. In high concurrency startup, might trigger multiple connects
            # followed by disconnects, but asyncpg pool handles this gracefully usually.
            # Ideally hook into lifespan, but middleware is separate.
            if settings.postgres.enabled:
                await self.db.connect()

        # 2. Identification (Cookie Strategy)
        anon_id = request.cookies.get(self.cookie_name)
        is_new_anon = False
        
        if not anon_id or not self._validate_signature(anon_id):
            anon_id = self._generate_signed_id()
            is_new_anon = True
            
        # Strip signature for internal use
        raw_anon_id = anon_id.split(".")[0]
        request.state.anon_id = raw_anon_id
        
        # 3. Determine User Tier & ID for Rate Limiting
        # Check if user is authenticated (set by AuthMiddleware usually, but that runs AFTER?)
        # Actually middleware runs in reverse order of addition. 
        # If AuthMiddleware adds user to request.session, we might need to access session directly.
        # request.user is standard.
        
        user = getattr(request.state, "user", None)
        if user:
            # Authenticated User
            identifier = user.get("id") # Assuming user dict or object
            # Determine tier from user object
            tier_str = user.get("tier", UserTier.FREE.value)
            try:
                tier = UserTier(tier_str)
            except ValueError:
                tier = UserTier.FREE
            tenant_id = user.get("tenant_id", "default")
        else:
            # Anonymous User
            identifier = raw_anon_id
            tier = UserTier.ANONYMOUS
            # Tenant ID from header or default
            tenant_id = request.headers.get("X-Tenant-Id", "default")

        # 4. Rate Limiting (skip if disabled via settings)
        if settings.postgres.enabled and settings.api.rate_limit_enabled:
            is_allowed, current, limit = await self.rate_limiter.check_rate_limit(
                tenant_id=tenant_id,
                identifier=identifier,
                tier=tier
            )

            if not is_allowed:
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": "You have exceeded your rate limit. Please sign in or upgrade to continue.",
                            "details": {
                                "limit": limit,
                                "tier": tier.value,
                                "retry_after": 60
                            }
                        }
                    },
                    headers={"Retry-After": "60"}
                )
        
        # 5. Process Request
        response = await call_next(request)
        
        # 6. Set Cookie if new
        if is_new_anon:
            response.set_cookie(
                key=self.cookie_name,
                value=anon_id,
                max_age=31536000, # 1 year
                httponly=True,
                samesite="lax",
                secure=settings.environment == "production"
            )
            
        # Add Rate Limit headers (only if rate limiting is enabled)
        if settings.postgres.enabled and settings.api.rate_limit_enabled and 'limit' in locals():
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
            
        return response

    def _generate_signed_id(self) -> str:
        """Generate a UUID4 signed with HMAC."""
        val = str(uuid.uuid4())
        sig = hmac.new(
            self.secret_key.encode(), 
            val.encode(), 
            hashlib.sha256
        ).hexdigest()[:12] # Short signature
        return f"{val}.{sig}"

    def _validate_signature(self, signed_val: str) -> bool:
        """Validate the HMAC signature."""
        try:
            val, sig = signed_val.split(".")
            expected_sig = hmac.new(
                self.secret_key.encode(), 
                val.encode(), 
                hashlib.sha256
            ).hexdigest()[:12]
            return secrets.compare_digest(sig, expected_sig)
        except ValueError:
            return False
