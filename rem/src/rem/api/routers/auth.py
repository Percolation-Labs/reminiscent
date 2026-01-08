"""
Authentication Router.

Supports multiple authentication methods:
1. Email (passwordless): POST /api/auth/email/send-code, POST /api/auth/email/verify
2. Pre-approved codes: POST /api/auth/email/verify (with pre-approved code, no send-code needed)
3. OAuth (Google, Microsoft): GET /api/auth/{provider}/login, GET /api/auth/{provider}/callback

Endpoints:
- POST /api/auth/email/send-code     - Send login code to email
- POST /api/auth/email/verify        - Verify code and create session (supports pre-approved codes)
- GET  /api/auth/{provider}/login    - Initiate OAuth flow
- GET  /api/auth/{provider}/callback - OAuth callback
- POST /api/auth/logout              - Clear session
- GET  /api/auth/me                  - Current user info

Supported providers:
- email: Passwordless email login
- preapproved: Pre-approved codes (bypass email, set via AUTH__PREAPPROVED_CODES)
- google: Google OAuth 2.0 / OIDC
- microsoft: Microsoft Entra ID OIDC

=============================================================================
Pre-Approved Code Authentication
=============================================================================

Pre-approved codes allow login without email verification. Useful for:
- Demo accounts
- Testing
- Beta access codes
- Admin provisioning

Configuration:
    AUTH__PREAPPROVED_CODES=A12345,A67890,B11111,B22222

Code prefixes:
    A = Admin role (e.g., A12345, AADMIN1)
    B = Normal user role (e.g., B11111, BUSER1)

Flow:
    1. User enters email + pre-approved code (no send-code step needed)
    2. POST /api/auth/email/verify with email and code
    3. System validates code against AUTH__PREAPPROVED_CODES
    4. Creates user if not exists, sets role based on prefix
    5. Returns JWT tokens (same as email auth)

Example:
    curl -X POST http://localhost:8000/api/auth/email/verify \
      -H "Content-Type: application/json" \
      -d '{"email": "admin@example.com", "code": "A12345"}'

=============================================================================
Email Authentication Access Control
=============================================================================

The email auth provider implements a tiered access control system:

Access Control Flow (send-code):
    User requests login code
    ├── User exists in database?
    │   ├── Yes → Check user.tier
    │   │   ├── tier == BLOCKED → Reject "Account is blocked"
    │   │   └── tier != BLOCKED → Allow (send code, existing users grandfathered)
    │   └── No (new user) → Check subscriber list first
    │       ├── Email in subscribers table? → Allow (create user & send code)
    │       └── Not a subscriber → Check EMAIL__TRUSTED_EMAIL_DOMAINS
    │           ├── Setting configured → domain in trusted list?
    │           │   ├── Yes → Create user & send code
    │           │   └── No → Reject "Email domain not allowed for signup"
    │           └── Not configured (empty) → Create user & send code (no restrictions)

Key Behaviors:
- Existing users: Always allowed to login (unless tier=BLOCKED)
- Subscribers: Always allowed to login (regardless of email domain)
- New users: Must have email from trusted domain (if EMAIL__TRUSTED_EMAIL_DOMAINS is set)
- No restrictions: Leave EMAIL__TRUSTED_EMAIL_DOMAINS empty to allow all domains

User Tiers (models.entities.UserTier):
- BLOCKED: Cannot login (rejected at send-code)
- ANONYMOUS: Rate-limited anonymous access
- FREE: Standard free tier
- BASIC/PRO: Paid tiers with additional features

Configuration:
    # Allow only specific domains for new signups
    EMAIL__TRUSTED_EMAIL_DOMAINS=siggymd.ai,example.com

    # Allow all domains (no restrictions)
    EMAIL__TRUSTED_EMAIL_DOMAINS=

Example blocking a user:
    user = await user_repo.get_by_id(user_id, tenant_id="default")
    user.tier = UserTier.BLOCKED
    await user_repo.upsert(user)

=============================================================================
OAuth Design Pattern (OAuth 2.1 + PKCE)
=============================================================================

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
    EMAIL__TRUSTED_EMAIL_DOMAINS=example.com  # Optional: restrict new signups

References:
- Authlib: https://docs.authlib.org/en/latest/
- OAuth 2.1: https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-11
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from pydantic import BaseModel, EmailStr
from loguru import logger

from .common import ErrorResponse

from ...settings import settings
from ...services.postgres.service import PostgresService
from ...services.user_service import UserService
from ...auth.providers.email import EmailAuthProvider
from ...auth.jwt import JWTService, get_jwt_service
from ...utils.user_id import email_to_user_id

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


# =============================================================================
# Email Authentication Endpoints
# =============================================================================


class EmailSendCodeRequest(BaseModel):
    """Request to send login code."""
    email: EmailStr


class EmailVerifyRequest(BaseModel):
    """Request to verify login code."""
    email: EmailStr
    code: str


@router.post(
    "/email/send-code",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request or email rejected"},
        500: {"model": ErrorResponse, "description": "Failed to send login code"},
        501: {"model": ErrorResponse, "description": "Email auth or database not configured"},
    },
)
async def send_email_code(request: Request, body: EmailSendCodeRequest):
    """
    Send a login code to an email address.

    Creates user if not exists (using deterministic UUID from email).
    Stores code in user metadata with expiry.

    Args:
        request: FastAPI request
        body: EmailSendCodeRequest with email

    Returns:
        Success status and message
    """
    if not settings.email.is_configured:
        raise HTTPException(
            status_code=501,
            detail="Email authentication is not configured"
        )

    # Get database connection
    if not settings.postgres.enabled:
        raise HTTPException(
            status_code=501,
            detail="Database is required for email authentication"
        )

    db = PostgresService()
    try:
        await db.connect()

        # Initialize email auth provider
        email_auth = EmailAuthProvider()

        # Send code
        result = await email_auth.send_code(
            email=body.email,
            db=db,
        )

        if result.success:
            return {
                "success": True,
                "message": result.message,
                "email": result.email,
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=result.message or result.error
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending login code: {e}")
        raise HTTPException(status_code=500, detail="Failed to send login code")
    finally:
        await db.disconnect()


@router.post(
    "/email/verify",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid or expired code"},
        500: {"model": ErrorResponse, "description": "Failed to verify login code"},
        501: {"model": ErrorResponse, "description": "Email auth or database not configured"},
    },
)
async def verify_email_code(request: Request, body: EmailVerifyRequest):
    """
    Verify login code and create session with JWT tokens.

    Supports two authentication methods:
    1. Pre-approved codes: Codes from AUTH__PREAPPROVED_CODES bypass email verification.
       - A prefix = admin role, B prefix = normal user role
       - Creates user if not exists, logs in directly
    2. Email verification: Standard 6-digit code sent via email

    Args:
        request: FastAPI request
        body: EmailVerifyRequest with email and code

    Returns:
        Success status with user info and JWT tokens
    """
    if not settings.postgres.enabled:
        raise HTTPException(
            status_code=501,
            detail="Database is required for email authentication"
        )

    db = PostgresService()
    try:
        await db.connect()
        user_service = UserService(db)

        # Check for pre-approved code first
        preapproved = settings.auth.check_preapproved_code(body.code)
        if preapproved:
            logger.info(f"Pre-approved code login attempt for {body.email} (role: {preapproved['role']})")

            # Get or create user with pre-approved role
            user_id = email_to_user_id(body.email)
            user_entity = await user_service.get_user_by_id(user_id)

            if not user_entity:
                # Create new user with role from pre-approved code
                user_entity = await user_service.get_or_create_user(
                    email=body.email,
                    name=body.email.split("@")[0],
                    tenant_id="default",
                )
                # Update role based on pre-approved code prefix
                user_entity.role = preapproved["role"]
                from ...services.postgres.repository import Repository
                from ...models.entities.user import User
                user_repo = Repository(User, "users", db=db)
                await user_repo.upsert(user_entity)
                logger.info(f"Created user {body.email} with role={preapproved['role']} via pre-approved code")
            else:
                # Update existing user's role if admin code used
                if preapproved["role"] == "admin" and user_entity.role != "admin":
                    user_entity.role = "admin"
                    from ...services.postgres.repository import Repository
                    from ...models.entities.user import User
                    user_repo = Repository(User, "users", db=db)
                    await user_repo.upsert(user_entity)
                    logger.info(f"Upgraded user {body.email} to admin via pre-approved code")

            # Build user dict for session/JWT
            user_dict = {
                "id": str(user_entity.id),
                "email": body.email,
                "email_verified": True,
                "name": user_entity.name or body.email.split("@")[0],
                "provider": "preapproved",
                "tenant_id": user_entity.tenant_id or "default",
                "tier": user_entity.tier.value if user_entity.tier else "free",
                "role": user_entity.role or preapproved["role"],
                "roles": [user_entity.role or preapproved["role"]],
            }

            # Generate JWT tokens
            jwt_service = get_jwt_service()
            tokens = jwt_service.create_tokens(user_dict)

            # Store user in session
            request.session["user"] = user_dict

            logger.info(f"User authenticated via pre-approved code: {body.email} (role: {user_dict['role']})")

            return {
                "success": True,
                "message": "Successfully authenticated with pre-approved code!",
                "user": user_dict,
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "token_type": tokens["token_type"],
                "expires_in": tokens["expires_in"],
            }

        # Standard email verification flow
        if not settings.email.is_configured:
            raise HTTPException(
                status_code=501,
                detail="Email authentication is not configured"
            )

        # Initialize email auth provider
        email_auth = EmailAuthProvider()

        # Verify code
        result = await email_auth.verify_code(
            email=body.email,
            code=body.code,
            db=db,
        )

        if not result.success:
            raise HTTPException(
                status_code=400,
                detail=result.message or result.error
            )

        # Create session - compatible with OAuth session format
        user_dict = email_auth.get_user_dict(
            email=result.email,
            user_id=result.user_id,
        )

        # Fetch actual user data from database to get role/tier
        try:
            user_entity = await user_service.get_user_by_id(result.user_id)
            if user_entity:
                # Override defaults with actual database values
                user_dict["role"] = user_entity.role or "user"
                user_dict["roles"] = [user_entity.role] if user_entity.role else ["user"]
                user_dict["tier"] = user_entity.tier.value if user_entity.tier else "free"
                user_dict["name"] = user_entity.name or user_dict["name"]
        except Exception as e:
            logger.warning(f"Could not fetch user details: {e}")
            # Continue with defaults from get_user_dict

        # Generate JWT tokens
        jwt_service = get_jwt_service()
        tokens = jwt_service.create_tokens(user_dict)

        # Store user in session (for backward compatibility)
        request.session["user"] = user_dict

        logger.info(f"User authenticated via email: {result.email}")

        return {
            "success": True,
            "message": result.message,
            "user": user_dict,
            # JWT tokens for stateless auth
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "token_type": tokens["token_type"],
            "expires_in": tokens["expires_in"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error verifying login code: {e}")
        raise HTTPException(status_code=500, detail="Failed to verify login code")
    finally:
        await db.disconnect()


# =============================================================================
# OAuth Authentication Endpoints
# =============================================================================


@router.get(
    "/{provider}/login",
    responses={
        400: {"model": ErrorResponse, "description": "Unknown OAuth provider"},
        501: {"model": ErrorResponse, "description": "Authentication is disabled"},
    },
)
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


@router.get(
    "/{provider}/callback",
    responses={
        400: {"model": ErrorResponse, "description": "Authentication failed or unknown provider"},
        501: {"model": ErrorResponse, "description": "Authentication is disabled"},
    },
)
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
                # user_id = UUID5 hash of email (deterministic, bijection)
                db_info = {
                    "id": email_to_user_id(user_info.get("email")),
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


@router.get(
    "/me",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def me(request: Request):
    """
    Get current user information from session or JWT.

    Args:
        request: FastAPI request

    Returns:
        User information or 401 if not authenticated
    """
    # First check for JWT in Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        jwt_service = get_jwt_service()
        user = jwt_service.verify_token(token)
        if user:
            return user

    # Fall back to session
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return user


# =============================================================================
# JWT Token Endpoints
# =============================================================================


class TokenRefreshRequest(BaseModel):
    """Request to refresh access token."""
    refresh_token: str


@router.post(
    "/token/refresh",
    responses={
        401: {"model": ErrorResponse, "description": "Invalid or expired refresh token"},
    },
)
async def refresh_token(body: TokenRefreshRequest):
    """
    Refresh access token using refresh token.

    Fetches the user's current role/tier from the database to ensure
    the new access token reflects their actual permissions.

    Args:
        body: TokenRefreshRequest with refresh_token

    Returns:
        New access token or 401 if refresh token is invalid
    """
    jwt_service = get_jwt_service()

    # First decode the refresh token to get user_id (without full verification yet)
    payload = jwt_service.decode_without_verification(body.refresh_token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token format"
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token: missing user ID"
        )

    # Fetch user from database to get current role/tier
    user_override = None
    if settings.postgres.enabled:
        db = PostgresService()
        try:
            await db.connect()
            user_service = UserService(db)
            user_entity = await user_service.get_user_by_id(user_id)
            if user_entity:
                user_override = {
                    "role": user_entity.role or "user",
                    "roles": [user_entity.role] if user_entity.role else ["user"],
                    "tier": user_entity.tier.value if user_entity.tier else "free",
                    "name": user_entity.name,
                }
                logger.debug(f"Refresh token: fetched user {user_id} with role={user_override['role']}, tier={user_override['tier']}")
        except Exception as e:
            logger.warning(f"Could not fetch user for token refresh: {e}")
            # Continue without override - will use defaults
        finally:
            await db.disconnect()

    # Now do the actual refresh with proper verification
    result = jwt_service.refresh_access_token(body.refresh_token, user_override=user_override)

    if not result:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )

    return result


@router.post(
    "/token/verify",
    responses={
        401: {"model": ErrorResponse, "description": "Missing, invalid, or expired token"},
    },
)
async def verify_token(request: Request):
    """
    Verify an access token is valid.

    Pass the token in the Authorization header: Bearer <token>

    Returns:
        User info if valid, 401 if invalid
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header"
        )

    token = auth_header[7:]
    jwt_service = get_jwt_service()
    user = jwt_service.verify_token(token)

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    return {"valid": True, "user": user}


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


@router.get(
    "/dev/token",
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


@router.get(
    "/dev/mock-code/{email}",
    responses={
        401: {"model": ErrorResponse, "description": "Mock codes not available in production"},
        404: {"model": ErrorResponse, "description": "No code found for email"},
    },
)
async def get_mock_code(email: str, request: Request):
    """
    Get the mock login code for testing (non-production only).

    This endpoint retrieves the code that was "sent" via email in mock mode.
    Use this for automated testing without real email delivery.

    Usage:
        1. POST /api/auth/email/send-code with email
        2. GET /api/auth/dev/mock-code/{email} to retrieve the code
        3. POST /api/auth/email/verify with email and code

    Returns:
        401 if in production environment
        404 if no code found for the email
        The code and email otherwise
    """
    if settings.environment == "production":
        raise HTTPException(
            status_code=401,
            detail="Mock codes are not available in production"
        )

    from ...services.email import EmailService

    code = EmailService.get_mock_code(email)
    if not code:
        raise HTTPException(
            status_code=404,
            detail=f"No mock code found for {email}. Send a code first."
        )

    return {
        "email": email,
        "code": code,
        "warning": "This endpoint is for testing only and will not work in production.",
    }
