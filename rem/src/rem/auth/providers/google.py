"""
Google OAuth Provider.

Implements OAuth 2.1 / OIDC for Google Sign-In.

Configuration:
1. Create OAuth 2.0 credentials at https://console.cloud.google.com/apis/credentials
2. Set authorized redirect URI: http://localhost:8000/api/auth/callback (dev)
3. Enable Google+ API for userinfo access
4. Set environment variables:
   - AUTH__GOOGLE__CLIENT_ID
   - AUTH__GOOGLE__CLIENT_SECRET
   - AUTH__GOOGLE__REDIRECT_URI

Google-specific features:
- Hosted domain restriction (hd parameter for Google Workspace)
- Incremental authorization
- Offline access for refresh tokens

References:
- Google OAuth 2.0: https://developers.google.com/identity/protocols/oauth2
- Google OIDC: https://developers.google.com/identity/openid-connect/openid-connect
- Scopes: https://developers.google.com/identity/protocols/oauth2/scopes
"""

from typing import Any

from .base import OAuthProvider, OAuthUserInfo


class GoogleOAuthProvider(OAuthProvider):
    """
    Google OAuth 2.1 / OIDC provider.

    Uses Google's OIDC endpoints for authentication.
    Supports both online (access token only) and offline (refresh token) access.
    """

    # Google OIDC discovery endpoint:
    # https://accounts.google.com/.well-known/openid-configuration
    AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
    USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
    JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"

    # Google OAuth scopes
    # openid: Required for OIDC
    # email: User email address
    # profile: User profile information (name, picture)
    DEFAULT_SCOPES = [
        "openid",
        "email",
        "profile",
    ]

    @property
    def authorization_endpoint(self) -> str:
        """Google authorization endpoint."""
        return self.AUTHORIZATION_ENDPOINT

    @property
    def token_endpoint(self) -> str:
        """Google token endpoint."""
        return self.TOKEN_ENDPOINT

    @property
    def userinfo_endpoint(self) -> str:
        """Google userinfo endpoint."""
        return self.USERINFO_ENDPOINT

    @property
    def jwks_uri(self) -> str:
        """Google JWKS URI for token validation."""
        return self.JWKS_URI

    @property
    def default_scopes(self) -> list[str]:
        """Default scopes for Google OAuth."""
        return self.DEFAULT_SCOPES.copy()

    def normalize_user_info(self, claims: dict[str, Any]) -> OAuthUserInfo:
        """
        Normalize Google OIDC claims to OAuthUserInfo.

        Google OIDC claims:
        - sub: Unique user ID (stable identifier)
        - email: User email address
        - email_verified: Email verification status
        - name: Full name
        - given_name: First name
        - family_name: Last name
        - picture: Profile picture URL
        - locale: User locale (e.g., "en")
        - hd: Hosted domain (for Google Workspace accounts)

        Args:
            claims: Raw claims from ID token or userinfo endpoint

        Returns:
            Normalized user information
        """
        return OAuthUserInfo(
            sub=claims["sub"],
            email=claims.get("email"),
            email_verified=claims.get("email_verified", False),
            name=claims.get("name"),
            given_name=claims.get("given_name"),
            family_name=claims.get("family_name"),
            picture=claims.get("picture"),
            locale=claims.get("locale"),
            provider="google",
            raw_claims=claims,
        )

    def generate_auth_url_with_hosted_domain(
        self,
        state: str,
        code_challenge: str,
        hosted_domain: str | None = None,
        access_type: str = "online",
        scopes: list[str] | None = None,
        nonce: str | None = None,
    ) -> str:
        """
        Generate authorization URL with Google-specific parameters.

        Args:
            state: CSRF protection state
            code_challenge: PKCE code challenge
            hosted_domain: Restrict to Google Workspace domain (e.g., "example.com")
            access_type: "online" (access token only) or "offline" (refresh token)
            scopes: OAuth scopes (uses default_scopes if None)
            nonce: OIDC nonce for ID token replay protection

        Returns:
            Authorization URL

        Google-specific parameters:
        - hd: Hosted domain restriction (Google Workspace only)
        - access_type: online (default) or offline (for refresh tokens)
        - prompt: consent (force consent screen), select_account (account picker)
        - include_granted_scopes: true (incremental authorization)
        """
        extra_params: dict[str, str] = {
            "access_type": access_type,
            "include_granted_scopes": "true",  # Incremental authorization
        }

        # Hosted domain restriction (Google Workspace)
        if hosted_domain:
            extra_params["hd"] = hosted_domain

        # Force consent screen to get refresh token
        if access_type == "offline":
            extra_params["prompt"] = "consent"

        return self.generate_auth_url(
            state=state,
            code_challenge=code_challenge,
            scopes=scopes,
            nonce=nonce,
            extra_params=extra_params,
        )
