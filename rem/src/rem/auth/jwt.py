"""
JWT Token Service for REM Authentication.

Provides JWT token generation and validation for stateless authentication.
Uses HS256 algorithm with the session secret for signing.

Token Types:
- Access Token: Short-lived (default 1 hour), used for API authentication
- Refresh Token: Long-lived (default 7 days), used to obtain new access tokens

Token Claims:
- sub: User ID (UUID string)
- email: User email
- name: User display name
- role: User role (user, admin)
- tier: User subscription tier
- roles: List of roles for authorization
- provider: Auth provider (email, google, microsoft)
- tenant_id: Tenant identifier for multi-tenancy
- exp: Expiration timestamp
- iat: Issued at timestamp
- type: Token type (access, refresh)

Usage:
    from rem.auth.jwt import JWTService

    jwt_service = JWTService()

    # Generate tokens after successful authentication
    tokens = jwt_service.create_tokens(user_dict)
    # Returns: {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 3600}

    # Validate token from Authorization header
    user = jwt_service.verify_token(token)
    # Returns user dict or None if invalid

    # Refresh access token
    new_tokens = jwt_service.refresh_access_token(refresh_token)
"""

import time
import hmac
import hashlib
import base64
import json
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


class JWTService:
    """
    JWT token service for authentication.

    Uses HMAC-SHA256 for signing - simple and secure for single-service deployment.
    For multi-service deployments, consider switching to RS256 with public/private keys.
    """

    def __init__(
        self,
        secret: str | None = None,
        access_token_expiry_seconds: int = 3600,  # 1 hour
        refresh_token_expiry_seconds: int = 604800,  # 7 days
        issuer: str = "rem",
    ):
        """
        Initialize JWT service.

        Args:
            secret: Secret key for signing (uses settings.auth.session_secret if not provided)
            access_token_expiry_seconds: Access token lifetime in seconds
            refresh_token_expiry_seconds: Refresh token lifetime in seconds
            issuer: Token issuer identifier
        """
        if secret:
            self._secret = secret
        else:
            from ..settings import settings
            self._secret = settings.auth.session_secret

        self._access_expiry = access_token_expiry_seconds
        self._refresh_expiry = refresh_token_expiry_seconds
        self._issuer = issuer

    def _base64url_encode(self, data: bytes) -> str:
        """Base64url encode without padding."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    def _base64url_decode(self, data: str) -> bytes:
        """Base64url decode with padding restoration."""
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    def _sign(self, message: str) -> str:
        """Create HMAC-SHA256 signature."""
        signature = hmac.new(
            self._secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return self._base64url_encode(signature)

    def _create_token(self, payload: dict) -> str:
        """
        Create a JWT token.

        Args:
            payload: Token claims

        Returns:
            Encoded JWT string
        """
        header = {"alg": "HS256", "typ": "JWT"}

        header_encoded = self._base64url_encode(json.dumps(header, separators=(",", ":")).encode())
        payload_encoded = self._base64url_encode(json.dumps(payload, separators=(",", ":")).encode())

        message = f"{header_encoded}.{payload_encoded}"
        signature = self._sign(message)

        return f"{message}.{signature}"

    def _verify_signature(self, token: str) -> dict | None:
        """
        Verify token signature and decode payload.

        Args:
            token: JWT token string

        Returns:
            Decoded payload dict or None if invalid
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            header_encoded, payload_encoded, signature = parts

            # Verify signature
            message = f"{header_encoded}.{payload_encoded}"
            expected_signature = self._sign(message)

            if not hmac.compare_digest(signature, expected_signature):
                logger.debug("JWT signature verification failed")
                return None

            # Decode payload
            payload = json.loads(self._base64url_decode(payload_encoded))
            return payload

        except Exception as e:
            logger.debug(f"JWT decode error: {e}")
            return None

    def create_tokens(
        self,
        user: dict,
        access_expiry: int | None = None,
        refresh_expiry: int | None = None,
    ) -> dict:
        """
        Create access and refresh tokens for a user.

        Args:
            user: User dict with id, email, name, role, tier, roles, provider, tenant_id
            access_expiry: Override access token expiry (seconds)
            refresh_expiry: Override refresh token expiry (seconds)

        Returns:
            Dict with access_token, refresh_token, token_type, expires_in
        """
        now = int(time.time())
        access_exp = access_expiry or self._access_expiry
        refresh_exp = refresh_expiry or self._refresh_expiry

        # Common claims
        base_claims = {
            "sub": user.get("id", ""),
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "role": user.get("role"),
            "tier": user.get("tier", "free"),
            "roles": user.get("roles", ["user"]),
            "provider": user.get("provider", "email"),
            "tenant_id": user.get("tenant_id", "default"),
            "iss": self._issuer,
            "iat": now,
        }

        # Access token
        access_payload = {
            **base_claims,
            "type": "access",
            "exp": now + access_exp,
        }
        access_token = self._create_token(access_payload)

        # Refresh token (minimal claims for security)
        refresh_payload = {
            "sub": user.get("id", ""),
            "email": user.get("email", ""),
            "type": "refresh",
            "iss": self._issuer,
            "iat": now,
            "exp": now + refresh_exp,
        }
        refresh_token = self._create_token(refresh_payload)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": access_exp,
        }

    def verify_token(self, token: str, token_type: str = "access") -> dict | None:
        """
        Verify a token and return user claims.

        Args:
            token: JWT token string
            token_type: Expected token type ("access" or "refresh")

        Returns:
            User dict with claims or None if invalid/expired
        """
        payload = self._verify_signature(token)
        if not payload:
            return None

        # Check token type
        if payload.get("type") != token_type:
            logger.debug(f"Token type mismatch: expected {token_type}, got {payload.get('type')}")
            return None

        # Check expiration
        exp = payload.get("exp", 0)
        if exp < time.time():
            logger.debug("Token expired")
            return None

        # Check issuer
        if payload.get("iss") != self._issuer:
            logger.debug(f"Token issuer mismatch: expected {self._issuer}, got {payload.get('iss')}")
            return None

        # Return user dict (compatible with session user format)
        return {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("name"),
            "role": payload.get("role"),
            "tier": payload.get("tier", "free"),
            "roles": payload.get("roles", ["user"]),
            "provider": payload.get("provider", "email"),
            "tenant_id": payload.get("tenant_id", "default"),
        }

    def refresh_access_token(
        self, refresh_token: str, user_override: dict | None = None
    ) -> dict | None:
        """
        Create new access token using refresh token.

        Args:
            refresh_token: Valid refresh token
            user_override: Optional dict with user fields to override defaults
                           (e.g., role, roles, tier, name from database lookup)

        Returns:
            New token dict or None if refresh token is invalid
        """
        # Verify refresh token
        payload = self._verify_signature(refresh_token)
        if not payload:
            return None

        if payload.get("type") != "refresh":
            logger.debug("Not a refresh token")
            return None

        # Check expiration
        exp = payload.get("exp", 0)
        if exp < time.time():
            logger.debug("Refresh token expired")
            return None

        # Build user dict with defaults
        user = {
            "id": payload.get("sub"),
            "email": payload.get("email"),
            "name": payload.get("email", "").split("@")[0],
            "provider": "email",
            "tenant_id": "default",
            "tier": "free",
            "role": "user",
            "roles": ["user"],
        }

        # Apply overrides from database lookup if provided
        if user_override:
            if user_override.get("role"):
                user["role"] = user_override["role"]
            if user_override.get("roles"):
                user["roles"] = user_override["roles"]
            if user_override.get("tier"):
                user["tier"] = user_override["tier"]
            if user_override.get("name"):
                user["name"] = user_override["name"]

        # Only return new access token, keep same refresh token
        now = int(time.time())
        access_payload = {
            "sub": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
            "tier": user["tier"],
            "roles": user["roles"],
            "provider": user["provider"],
            "tenant_id": user["tenant_id"],
            "type": "access",
            "iss": self._issuer,
            "iat": now,
            "exp": now + self._access_expiry,
        }

        return {
            "access_token": self._create_token(access_payload),
            "token_type": "bearer",
            "expires_in": self._access_expiry,
        }

    def decode_without_verification(self, token: str) -> dict | None:
        """
        Decode token without verification (for debugging only).

        Args:
            token: JWT token string

        Returns:
            Decoded payload or None
        """
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload = json.loads(self._base64url_decode(parts[1]))
            return payload
        except Exception:
            return None


# Singleton instance for convenience
_jwt_service: Optional[JWTService] = None


def get_jwt_service() -> JWTService:
    """Get or create the JWT service singleton."""
    global _jwt_service
    if _jwt_service is None:
        _jwt_service = JWTService()
    return _jwt_service
