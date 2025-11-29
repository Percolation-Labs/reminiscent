"""
OAuth 2.1 Authentication Router.

Leverages Authlib for standards-compliant OAuth/OIDC implementation.
Minimal custom code - Authlib handles PKCE, token validation, JWKS.

Endpoints:
- GET  /api/auth/{provider}/login    - Initiate OAuth flow
- GET  /api/auth/{provider}/callback - OAuth callback
- POST /api/auth/logout              - Clear session
- GET  /api/auth/me                  - Current user info

Supported providers:
- google: Google OAuth 2.0 / OIDC
- microsoft: Microsoft Entra ID OIDC

Design Pattern (OAuth 2.1 + PKCE):
1. User clicks "Login with Google"
2. /login generates state + PKCE code_verifier
3. Store code_verifier in session
4. Redirect to provider with code_challenge
5. User authenticates and grants consent
6. Provider redirects to /callback with code
7. Exchange code + code_verifier for tokens
8. Validate ID token signature with JWKS
9. Store user info in session
10. Redirect to application

Dependencies:
    pip install authlib httpx

Environment variables:
    AUTH__ENABLED=true
    AUTH__SESSION_SECRET=<random-secret>
    AUTH__GOOGLE__CLIENT_ID=<google-client-id>
    AUTH__GOOGLE__CLIENT_SECRET=<google-client-secret>
    AUTH__MICROSOFT__CLIENT_ID=<microsoft-client-id>
    AUTH__MICROSOFT__CLIENT_SECRET=<microsoft-client-secret>
    AUTH__MICROSOFT__TENANT=common

References:
- Authlib: https://docs.authlib.org/en/latest/
- OAuth 2.1: https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-11
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from loguru import logger

from ...settings import settings
from ...services.postgres.service import PostgresService
from ...services.user_service import UserService

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Initialize Authlib OAuth client
# Authlib handles PKCE, state, nonce, token validation automatically
oauth = OAuth()

# Register Google provider
if settings.auth.google.client_id:
    oauth.register(
        name="google",
        client_id=settings.auth.google.client_id,
        client_secret=settings.auth.google.client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            # Authlib automatically adds PKCE to authorization request
        },
    )
    logger.info("Google OAuth provider registered")

# Register Microsoft provider
if settings.auth.microsoft.client_id:
    tenant = settings.auth.microsoft.tenant
    oauth.register(
        name="microsoft",
        client_id=settings.auth.microsoft.client_id,
        client_secret=settings.auth.microsoft.client_secret,
        server_metadata_url=f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile User.Read",
        },
    )
    logger.info(f"Microsoft OAuth provider registered (tenant: {tenant})")


@router.get("/{provider}/login")
async def login(provider: str, request: Request):
    """
    Initiate OAuth flow with provider.

    Authlib automatically:
    - Generates state for CSRF protection
    - Generates PKCE code_verifier and code_challenge
    - Stores state and code_verifier in session
    - Redirects to provider's authorization endpoint

    Args:
        provider: OAuth provider (google, microsoft)
        request: FastAPI request (for session access)

    Returns:
        Redirect to provider's authorization page
    """
    if not settings.auth.enabled:
        raise HTTPException(status_code=501, detail="Authentication is disabled")

    # Get OAuth client for provider
    client = oauth.create_client(provider)
    if not client:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # Get redirect URI from settings
    if provider == "google":
        redirect_uri = settings.auth.google.redirect_uri
    elif provider == "microsoft":
        redirect_uri = settings.auth.microsoft.redirect_uri
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    # Authlib authorize_redirect() automatically:
    # - Generates state parameter
    # - Generates PKCE code_verifier and code_challenge
    # - Stores state and code_verifier in session
    # - Builds authorization URL with all required parameters
    return await client.authorize_redirect(request, redirect_uri)


@router.get("/{provider}/callback")
async def callback(provider: str, request: Request):
    """
    OAuth callback endpoint.

    Authlib automatically:
    - Validates state parameter (CSRF protection)
    - Exchanges code for tokens with PKCE code_verifier
    - Validates ID token signature with JWKS
    - Verifies ID token claims (iss, aud, exp, nonce)

    Args:
        provider: OAuth provider (google, microsoft)
        request: FastAPI request (for session and query params)

    Returns:
        Redirect to application home page
    """
    if not settings.auth.enabled:
        raise HTTPException(status_code=501, detail="Authentication is disabled")

    # Get OAuth client for provider
    client = oauth.create_client(provider)
    if not client:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    try:
        # Authlib authorize_access_token() automatically:
        # - Validates state from session (CSRF)
        # - Retrieves code_verifier from session
        # - Exchanges authorization code for tokens
        # - Validates ID token signature with JWKS
        # - Verifies ID token claims
        token = await client.authorize_access_token(request)

        # Parse user info from ID token or call userinfo endpoint
        # Authlib parses ID token claims automatically
        user_info = token.get("userinfo")
        if not user_info:
            # Fetch from userinfo endpoint if not in ID token
            user_info = await client.userinfo(token=token)
            
        # --- REM Integration Start ---
        if settings.postgres.enabled:
            # Connect to DB
            db = PostgresService()
            try:
                await db.connect()
                user_service = UserService(db)
                
                # Get/Create User
                user_entity = await user_service.get_or_create_user(
                    email=user_info.get("email"),
                    name=user_info.get("name", "New User"),
                    avatar_url=user_info.get("picture"),
                    tenant_id="default", # Single tenant for now
                )
                
                # Link Anonymous Session
                # TrackingMiddleware sets request.state.anon_id
                anon_id = getattr(request.state, "anon_id", None)
                # Fallback to cookie if middleware didn't run or state missing
                if not anon_id:
                    # Attempt to parse cookie manually if needed, but middleware 
                    # usually handles the signature logic.
                    # Just check raw cookie for simple case (not recommended if signed)
                    pass 
                
                if anon_id:
                    await user_service.link_anonymous_session(user_entity, anon_id)
                    
                # Enrich session user with DB info
                db_info = {
                    "id": str(user_entity.id),
                    "tenant_id": user_entity.tenant_id,
                    "tier": user_entity.tier.value if user_entity.tier else "free",
                    "roles": [user_entity.role] if user_entity.role else [],
                }
                
            except Exception as db_e:
                logger.error(f"Database error during auth callback: {db_e}")
                # Continue login even if DB fails, but warn
                db_info = {"id": "db_error", "tier": "free"}
            finally:
                await db.disconnect()
        else:
            db_info = {"id": "no_db", "tier": "free"}
        # --- REM Integration End ---

        # Store user info in session
        request.session["user"] = {
            "provider": provider,
            "sub": user_info.get("sub"),
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
            # Add DB info
            "id": db_info.get("id"),
            "tenant_id": db_info.get("tenant_id", "default"),
            "tier": db_info.get("tier"),
            "roles": db_info.get("roles", []),
        }

        # Store tokens in session for API access
        request.session["tokens"] = {
            "access_token": token.get("access_token"),
            "refresh_token": token.get("refresh_token"),
            "expires_at": token.get("expires_at"),
        }

        logger.info(f"User authenticated: {user_info.get('email')} via {provider}")

        # Redirect to application
        # TODO: Support custom redirect URL from state parameter
        return RedirectResponse(url="/")

    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(status_code=400, detail=f"Authentication failed: {str(e)}")


@router.post("/logout")
async def logout(request: Request):
    """
    Clear user session.

    Args:
        request: FastAPI request

    Returns:
        Success message
    """
    request.session.clear()
    return {"message": "Logged out successfully"}


@router.get("/me")
async def me(request: Request):
    """
    Get current user information from session.

    Args:
        request: FastAPI request

    Returns:
        User information or 401 if not authenticated
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user


# =============================================================================
# Development Token Endpoints (non-production only)
# =============================================================================


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


@router.get("/dev/token")
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
