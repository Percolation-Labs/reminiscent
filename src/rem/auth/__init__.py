"""
REM Authentication Module.

OAuth 2.1 compliant authentication with support for:
- Google OAuth
- Microsoft Entra ID (Azure AD) OIDC
- Custom OIDC providers

Design Pattern:
- Provider-agnostic base classes
- PKCE (Proof Key for Code Exchange) for all flows
- State parameter for CSRF protection
- Nonce for ID token replay protection
- Token validation with JWKS
- Clean separation: providers/ for OAuth logic, middleware.py for FastAPI integration
"""

from .providers.base import OAuthProvider
from .providers.google import GoogleOAuthProvider
from .providers.microsoft import MicrosoftOAuthProvider

__all__ = [
    "OAuthProvider",
    "GoogleOAuthProvider",
    "MicrosoftOAuthProvider",
]
