"""
Microsoft Entra ID (Azure AD) OAuth Provider.

Implements OAuth 2.1 / OIDC for Microsoft authentication.

Configuration:
1. Register application at https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps
2. Create client secret under "Certificates & secrets"
3. Add redirect URI: http://localhost:8000/api/auth/callback (dev)
4. Set API permissions:
   - Microsoft Graph: User.Read (delegated)
   - Optional: email, profile, openid (automatically included)
5. Set environment variables:
   - AUTH__MICROSOFT__CLIENT_ID (Application ID)
   - AUTH__MICROSOFT__CLIENT_SECRET
   - AUTH__MICROSOFT__TENANT_ID (or "common" for multi-tenant)
   - AUTH__MICROSOFT__REDIRECT_URI

Microsoft-specific features:
- Multi-tenant support (common, organizations, consumers)
- Azure AD B2C support
- Conditional access policies
- Token caching with MSAL

Tenant options:
- common: Multi-tenant + personal Microsoft accounts
- organizations: Multi-tenant (work/school only)
- consumers: Personal Microsoft accounts only
- {tenant-id}: Single tenant (specific organization)

References:
- Microsoft identity platform: https://learn.microsoft.com/en-us/entra/identity-platform/
- OAuth 2.0 flow: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow
- OIDC: https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc
- Scopes: https://learn.microsoft.com/en-us/graph/permissions-reference
"""

from typing import Any

from .base import OAuthProvider, OAuthUserInfo


class MicrosoftOAuthProvider(OAuthProvider):
    """
    Microsoft Entra ID (Azure AD) OAuth 2.1 / OIDC provider.

    Supports multi-tenant authentication and Microsoft Graph API access.
    Uses Microsoft identity platform v2.0 endpoints.
    """

    # Microsoft identity platform v2.0 endpoints
    # Replace {tenant} with:
    # - "common" for multi-tenant + personal accounts
    # - "organizations" for work/school accounts only
    # - "consumers" for personal Microsoft accounts only
    # - Tenant ID/domain for single-tenant
    AUTHORIZATION_ENDPOINT_TEMPLATE = (
        "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
    )
    TOKEN_ENDPOINT_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    USERINFO_ENDPOINT = "https://graph.microsoft.com/v1.0/me"
    JWKS_URI_TEMPLATE = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"

    # Microsoft Graph scopes
    # openid: Required for OIDC
    # email: User email address
    # profile: User profile information
    # User.Read: Read user profile via Microsoft Graph
    # offline_access: Request refresh token
    DEFAULT_SCOPES = [
        "openid",
        "email",
        "profile",
        "User.Read",  # Microsoft Graph: read user profile
    ]

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        tenant: str = "common",
    ):
        """
        Initialize Microsoft OAuth provider.

        Args:
            client_id: Application (client) ID from Azure portal
            client_secret: Client secret from Azure portal
            redirect_uri: Redirect URI registered in Azure portal
            tenant: Tenant ID or "common"/"organizations"/"consumers"
        """
        super().__init__(client_id, client_secret, redirect_uri)
        self.tenant = tenant

    @property
    def authorization_endpoint(self) -> str:
        """Microsoft authorization endpoint."""
        return self.AUTHORIZATION_ENDPOINT_TEMPLATE.format(tenant=self.tenant)

    @property
    def token_endpoint(self) -> str:
        """Microsoft token endpoint."""
        return self.TOKEN_ENDPOINT_TEMPLATE.format(tenant=self.tenant)

    @property
    def userinfo_endpoint(self) -> str:
        """Microsoft Graph /me endpoint for user info."""
        return self.USERINFO_ENDPOINT

    @property
    def jwks_uri(self) -> str:
        """Microsoft JWKS URI for token validation."""
        return self.JWKS_URI_TEMPLATE.format(tenant=self.tenant)

    @property
    def default_scopes(self) -> list[str]:
        """Default scopes for Microsoft OAuth."""
        return self.DEFAULT_SCOPES.copy()

    def normalize_user_info(self, claims: dict[str, Any]) -> OAuthUserInfo:
        """
        Normalize Microsoft claims to OAuthUserInfo.

        Microsoft Graph /me response:
        - id: Unique user ID (stable identifier)
        - userPrincipalName: User principal name (UPN)
        - mail: Primary email (may be null)
        - displayName: Display name
        - givenName: First name
        - surname: Last name
        - preferredLanguage: User locale

        Microsoft ID token claims:
        - sub: Subject (unique user ID, different from Graph ID)
        - email: User email
        - name: Full name
        - given_name: First name
        - family_name: Last name
        - preferred_username: UPN or email

        Args:
            claims: Raw claims from ID token or Microsoft Graph /me

        Returns:
            Normalized user information
        """
        # Handle both ID token claims and Graph API response
        # Graph API uses different field names than OIDC claims
        if "id" in claims:
            # Microsoft Graph /me response
            sub = claims["id"]
            email = claims.get("mail") or claims.get("userPrincipalName")
            name = claims.get("displayName")
            given_name = claims.get("givenName")
            family_name = claims.get("surname")
            locale = claims.get("preferredLanguage")
        else:
            # OIDC ID token claims
            sub = claims["sub"]
            email = claims.get("email") or claims.get("preferred_username")
            name = claims.get("name")
            given_name = claims.get("given_name")
            family_name = claims.get("family_name")
            locale = claims.get("locale")

        return OAuthUserInfo(
            sub=sub,
            email=email,
            email_verified=True,  # Microsoft verifies emails during account creation
            name=name,
            given_name=given_name,
            family_name=family_name,
            picture=None,  # Microsoft Graph requires separate photo endpoint
            locale=locale,
            provider="microsoft",
            raw_claims=claims,
        )

    def generate_auth_url_with_prompt(
        self,
        state: str,
        code_challenge: str,
        prompt: str | None = None,
        domain_hint: str | None = None,
        login_hint: str | None = None,
        scopes: list[str] | None = None,
        nonce: str | None = None,
    ) -> str:
        """
        Generate authorization URL with Microsoft-specific parameters.

        Args:
            state: CSRF protection state
            code_challenge: PKCE code challenge
            prompt: Authentication behavior (none, login, consent, select_account)
            domain_hint: Domain hint for faster login (e.g., "contoso.com")
            login_hint: Login hint (email) to pre-fill sign-in form
            scopes: OAuth scopes (uses default_scopes if None)
            nonce: OIDC nonce for ID token replay protection

        Returns:
            Authorization URL

        Microsoft-specific parameters:
        - prompt: Authentication behavior
          - none: Silent authentication (fails if interaction required)
          - login: Force user to re-authenticate
          - consent: Force consent screen
          - select_account: Show account picker
        - domain_hint: Domain hint for faster login (skip domain discovery)
        - login_hint: Email to pre-fill sign-in form
        - response_mode: query (default), form_post, fragment
        """
        extra_params: dict[str, str] = {}

        if prompt:
            extra_params["prompt"] = prompt

        if domain_hint:
            extra_params["domain_hint"] = domain_hint

        if login_hint:
            extra_params["login_hint"] = login_hint

        # Add offline_access scope for refresh token
        scopes_with_offline = scopes or self.default_scopes.copy()
        if "offline_access" not in scopes_with_offline:
            scopes_with_offline.append("offline_access")

        return self.generate_auth_url(
            state=state,
            code_challenge=code_challenge,
            scopes=scopes_with_offline,
            nonce=nonce,
            extra_params=extra_params,
        )
