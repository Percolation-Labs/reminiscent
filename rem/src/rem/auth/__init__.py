"""
REM Authentication Module.

Authentication with support for:
- Email passwordless login (verification codes)
- Google OAuth
- Microsoft Entra ID (Azure AD) OIDC
- Custom OIDC providers

Design Pattern:
- Provider-agnostic base classes
- PKCE (Proof Key for Code Exchange) for OAuth flows
- State parameter for CSRF protection
- Nonce for ID token replay protection
- Token validation with JWKS
- Clean separation: providers/ for auth logic, middleware.py for FastAPI integration

Email Auth Flow:
1. POST /api/auth/email/send-code with {email}
2. User receives code via email
3. POST /api/auth/email/verify with {email, code}
4. Session created, user authenticated
"""

from .providers.base import OAuthProvider
from .providers.email import EmailAuthProvider, EmailAuthResult
from .providers.google import GoogleOAuthProvider
from .providers.microsoft import MicrosoftOAuthProvider

__all__ = [
    "OAuthProvider",
    "EmailAuthProvider",
    "EmailAuthResult",
    "GoogleOAuthProvider",
    "MicrosoftOAuthProvider",
]
