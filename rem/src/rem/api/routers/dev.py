"""
Development utilities router (non-production only).

Provides testing endpoints that are available in development/staging environments
regardless of auth configuration. These endpoints are NEVER available in production.

Endpoints:
- GET  /api/dev/token    - Get a dev token for test-user
"""

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from .common import ErrorResponse
from ...settings import settings

router = APIRouter(prefix="/api/dev", tags=["dev"])


def generate_dev_token() -> str:
    """
    Generate a dev token for testing.

    Token format: dev_<hmac_signature>
    The signature is based on the session secret to ensure only valid tokens work.
    """
    import hashlib
    import hmac

    # Use session secret as key
    secret = settings.auth.session_secret or "dev-secret"
    message = "test-user:dev-token"

    signature = hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()[:32]

    return f"dev_{signature}"


def verify_dev_token(token: str) -> bool:
    """Verify a dev token is valid."""
    expected = generate_dev_token()
    return token == expected


@router.get(
    "/token",
    responses={
        401: {"model": ErrorResponse, "description": "Dev tokens not available in production"},
    },
)
async def get_dev_token(request: Request):
    """
    Get a development token for testing (non-production only).

    This token can be used as a Bearer token to authenticate as the
    test user (test-user / test@rem.local) without going through OAuth.

    Usage:
        curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/...

    Returns:
        401 if in production environment
        Token and usage instructions otherwise
    """
    if settings.environment == "production":
        raise HTTPException(
            status_code=401,
            detail="Dev tokens are not available in production"
        )

    token = generate_dev_token()

    return {
        "token": token,
        "type": "Bearer",
        "user": {
            "id": "test-user",
            "email": "test@rem.local",
            "name": "Test User",
        },
        "usage": f'curl -H "Authorization: Bearer {token}" http://localhost:8000/api/v1/...',
        "warning": "This token is for development/testing only and will not work in production.",
    }
