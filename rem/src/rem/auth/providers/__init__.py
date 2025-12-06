"""Authentication provider implementations."""

from .base import OAuthProvider, OAuthTokens, OAuthUserInfo
from .email import EmailAuthProvider, EmailAuthResult
from .google import GoogleOAuthProvider
from .microsoft import MicrosoftOAuthProvider

__all__ = [
    "OAuthProvider",
    "OAuthTokens",
    "OAuthUserInfo",
    "EmailAuthProvider",
    "EmailAuthResult",
    "GoogleOAuthProvider",
    "MicrosoftOAuthProvider",
]
