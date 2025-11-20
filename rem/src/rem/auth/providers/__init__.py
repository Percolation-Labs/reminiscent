"""OAuth provider implementations."""

from .base import OAuthProvider, OAuthTokens, OAuthUserInfo
from .google import GoogleOAuthProvider
from .microsoft import MicrosoftOAuthProvider

__all__ = [
    "OAuthProvider",
    "OAuthTokens",
    "OAuthUserInfo",
    "GoogleOAuthProvider",
    "MicrosoftOAuthProvider",
]
