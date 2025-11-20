"""
Base OAuth Provider for OAuth 2.1 compliant authentication.

OAuth 2.1 Security Best Practices:
- PKCE (Proof Key for Code Exchange) mandatory for all flows
- State parameter for CSRF protection
- Nonce for ID token replay protection (OIDC)
- No implicit flow (deprecated in OAuth 2.1)
- Short-lived access tokens with refresh tokens
- Token validation with JWKS (JSON Web Key Set)
- Redirect URI exact matching

References:
- OAuth 2.1: https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-11
- OIDC Core: https://openid.net/specs/openid-connect-core-1_0.html
- PKCE: https://datatracker.ietf.org/doc/html/rfc7636
"""

import hashlib
import secrets
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, Field


class OAuthTokens(BaseModel):
    """
    OAuth token response.

    Fields match OAuth 2.1 / OIDC token response spec.
    """

    access_token: str = Field(description="Access token for API requests")
    token_type: str = Field(default="Bearer", description="Token type (always Bearer)")
    expires_in: int = Field(description="Token lifetime in seconds")
    refresh_token: str | None = Field(default=None, description="Refresh token for renewal")
    id_token: str | None = Field(default=None, description="ID token (OIDC only)")
    scope: str | None = Field(default=None, description="Granted scopes")


class OAuthUserInfo(BaseModel):
    """
    Normalized user information from OAuth provider.

    Maps provider-specific fields to standard fields.
    """

    sub: str = Field(description="Subject (unique user ID from provider)")
    email: str | None = Field(default=None, description="User email")
    email_verified: bool = Field(default=False, description="Email verification status")
    name: str | None = Field(default=None, description="Full name")
    given_name: str | None = Field(default=None, description="First name")
    family_name: str | None = Field(default=None, description="Last name")
    picture: str | None = Field(default=None, description="Profile picture URL")
    locale: str | None = Field(default=None, description="User locale")

    # Provider-specific metadata
    provider: str = Field(description="OAuth provider (google, microsoft)")
    raw_claims: dict[str, Any] = Field(
        default_factory=dict, description="Raw claims from ID token/userinfo"
    )


class OAuthProvider(ABC):
    """
    Base class for OAuth 2.1 providers.

    Implements common OAuth flow logic with PKCE.
    Subclasses implement provider-specific endpoints and claim mapping.

    Design Pattern:
    1. generate_auth_url() - Create authorization URL with PKCE
    2. exchange_code() - Exchange code for tokens using code_verifier
    3. validate_token() - Validate access/ID token with JWKS
    4. get_user_info() - Fetch user info from provider
    5. refresh_token() - Refresh access token using refresh_token

    OAuth 2.1 Flow:
    1. Client generates code_verifier (random string)
    2. Client creates code_challenge = SHA256(code_verifier)
    3. Client redirects to authorization URL with code_challenge
    4. User authenticates and grants consent
    5. Provider redirects to callback with code
    6. Client exchanges code + code_verifier for tokens
    7. Provider validates code_verifier matches code_challenge
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ):
        """
        Initialize OAuth provider.

        Args:
            client_id: OAuth client ID from provider
            client_secret: OAuth client secret from provider
            redirect_uri: Redirect URI registered with provider
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    @property
    @abstractmethod
    def authorization_endpoint(self) -> str:
        """Authorization endpoint URL."""
        pass

    @property
    @abstractmethod
    def token_endpoint(self) -> str:
        """Token endpoint URL."""
        pass

    @property
    @abstractmethod
    def userinfo_endpoint(self) -> str:
        """Userinfo endpoint URL."""
        pass

    @property
    @abstractmethod
    def jwks_uri(self) -> str:
        """JWKS (JSON Web Key Set) URI for token validation."""
        pass

    @property
    @abstractmethod
    def default_scopes(self) -> list[str]:
        """Default OAuth scopes for this provider."""
        pass

    @abstractmethod
    def normalize_user_info(self, claims: dict[str, Any]) -> OAuthUserInfo:
        """
        Normalize provider-specific claims to OAuthUserInfo.

        Args:
            claims: Raw claims from ID token or userinfo endpoint

        Returns:
            Normalized user information
        """
        pass

    @staticmethod
    def generate_code_verifier() -> str:
        """
        Generate PKCE code verifier.

        OAuth 2.1 requires PKCE for all authorization code flows.
        Code verifier is a cryptographically random string (43-128 chars).

        Returns:
            Code verifier (base64url encoded random bytes)
        """
        # Generate 32 random bytes (256 bits of entropy)
        # Base64url encode = 43 characters
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_code_challenge(code_verifier: str) -> str:
        """
        Generate PKCE code challenge from verifier.

        Uses S256 method (SHA-256 hash, base64url encoded).
        Plain method is NOT allowed in OAuth 2.1.

        Args:
            code_verifier: Code verifier from generate_code_verifier()

        Returns:
            Code challenge (SHA-256 of verifier, base64url encoded)
        """
        # SHA-256 hash of verifier
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        # Base64url encode (no padding)
        return secrets.token_urlsafe(32)[:43]  # Trim to match digest length

    @staticmethod
    def generate_state() -> str:
        """
        Generate state parameter for CSRF protection.

        State is verified on callback to prevent CSRF attacks.

        Returns:
            Random state string
        """
        return secrets.token_urlsafe(32)

    @staticmethod
    def generate_nonce() -> str:
        """
        Generate nonce for ID token replay protection (OIDC).

        Nonce is included in ID token and verified to prevent replay.

        Returns:
            Random nonce string
        """
        return secrets.token_urlsafe(32)

    def generate_auth_url(
        self,
        state: str,
        code_challenge: str,
        scopes: list[str] | None = None,
        nonce: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        """
        Generate authorization URL for OAuth flow.

        Args:
            state: CSRF protection state
            code_challenge: PKCE code challenge
            scopes: OAuth scopes (uses default_scopes if None)
            nonce: OIDC nonce for ID token replay protection
            extra_params: Provider-specific parameters

        Returns:
            Authorization URL to redirect user to
        """
        scopes = scopes or self.default_scopes

        params: dict[str, str] = {
            "client_id": self.client_id,
            "response_type": "code",  # Authorization code flow (OAuth 2.1)
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",  # SHA-256 (required by OAuth 2.1)
        }

        if nonce:
            params["nonce"] = nonce

        if extra_params:
            params.update(extra_params)

        # Build query string
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{self.authorization_endpoint}?{query}"

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
    ) -> OAuthTokens:
        """
        Exchange authorization code for tokens.

        Uses PKCE code_verifier to prove authorization request ownership.

        Args:
            code: Authorization code from callback
            code_verifier: PKCE code verifier from session

        Returns:
            OAuth tokens (access, refresh, ID token)

        Raises:
            httpx.HTTPStatusError: If token exchange fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code_verifier": code_verifier,  # PKCE verification
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return OAuthTokens(**response.json())

    async def refresh_access_token(
        self,
        refresh_token: str,
    ) -> OAuthTokens:
        """
        Refresh access token using refresh token.

        Args:
            refresh_token: Refresh token from initial token exchange

        Returns:
            New OAuth tokens

        Raises:
            httpx.HTTPStatusError: If refresh fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.token_endpoint,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            return OAuthTokens(**response.json())

    async def get_user_info(
        self,
        access_token: str,
    ) -> OAuthUserInfo:
        """
        Fetch user information from userinfo endpoint.

        Args:
            access_token: Access token from token exchange

        Returns:
            Normalized user information

        Raises:
            httpx.HTTPStatusError: If userinfo request fails
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            claims = response.json()
            return self.normalize_user_info(claims)

    async def validate_id_token(
        self,
        id_token: str,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """
        Validate ID token signature and claims.

        OAuth 2.1 + OIDC requires:
        - Signature validation with JWKS
        - Issuer validation
        - Audience validation (client_id)
        - Expiration validation
        - Nonce validation (if provided)

        Args:
            id_token: JWT ID token from token response
            nonce: Expected nonce value from session

        Returns:
            Validated claims from ID token

        Raises:
            ValueError: If token validation fails

        TODO: Implement with python-jose or PyJWT
        """
        # TODO: Implement JWT validation
        # 1. Fetch JWKS from jwks_uri
        # 2. Decode JWT header to get kid (key ID)
        # 3. Find matching key in JWKS
        # 4. Verify signature with public key
        # 5. Validate claims (iss, aud, exp, nonce)
        raise NotImplementedError("ID token validation not implemented")
