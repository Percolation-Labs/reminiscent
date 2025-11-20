# OAuth 2.1 Authentication

OAuth 2.1 compliant authentication with Google and Microsoft Entra ID.

## Features

- **OAuth 2.1 Security Best Practices**
  - PKCE (Proof Key for Code Exchange) - mandatory for all flows
  - State parameter for CSRF protection
  - Nonce for ID token replay protection
  - Token validation with JWKS

- **Supported Providers**
  - Google OAuth 2.0 / OIDC
  - Microsoft Entra ID (Azure AD) OIDC

- **Minimal Code**
  - Leverages Authlib for standards compliance
  - Authlib handles PKCE, token exchange, JWKS validation
  - Clean integration with FastAPI

## Installation

```bash
pip install authlib httpx
```

## Configuration

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 credentials
3. Add authorized redirect URI: `http://localhost:8000/api/auth/google/callback`
4. Set environment variables:

```bash
AUTH__ENABLED=true
AUTH__SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

AUTH__GOOGLE__CLIENT_ID=your-client-id.apps.googleusercontent.com
AUTH__GOOGLE__CLIENT_SECRET=your-client-secret
AUTH__GOOGLE__REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

### Microsoft Entra ID Setup

1. Go to [Azure Portal](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps)
2. Register new application
3. Create client secret under "Certificates & secrets"
4. Add redirect URI: `http://localhost:8000/api/auth/microsoft/callback`
5. Add API permissions: Microsoft Graph > User.Read (delegated)
6. Set environment variables:

```bash
AUTH__ENABLED=true
AUTH__SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

AUTH__MICROSOFT__CLIENT_ID=your-application-id
AUTH__MICROSOFT__CLIENT_SECRET=your-client-secret
AUTH__MICROSOFT__REDIRECT_URI=http://localhost:8000/api/auth/microsoft/callback
AUTH__MICROSOFT__TENANT=common  # or your tenant ID
```

**Tenant options:**
- `common` - Multi-tenant + personal Microsoft accounts
- `organizations` - Work/school accounts only
- `consumers` - Personal Microsoft accounts only
- `{tenant-id}` - Single tenant (specific organization)

## Usage

### 1. Start the API server

```bash
cd rem
uv run python -m rem.api.main
```

### 2. Initiate login

Navigate to:
- Google: `http://localhost:8000/api/auth/google/login`
- Microsoft: `http://localhost:8000/api/auth/microsoft/login`

### 3. OAuth Flow

```
User                Browser                API Server              OAuth Provider
  |                    |                       |                         |
  |-- Click Login ---->|                       |                         |
  |                    |-- GET /auth/google/login -->                    |
  |                    |                       |-- Generate PKCE ------->|
  |                    |                       |   (code_verifier)       |
  |                    |<-- Redirect to Google --|                       |
  |<-- Show Google login --|                   |                         |
  |                    |                       |                         |
  |-- Enter credentials -->                    |                         |
  |                    |-- Authorize ----------------------->|            |
  |                    |<-- Redirect with code ----------------|          |
  |                    |                       |                         |
  |                    |-- GET /auth/google/callback?code=xyz ---------->|
  |                    |                       |-- Exchange code ------->|
  |                    |                       |   + code_verifier       |
  |                    |                       |<-- Tokens --------------|
  |                    |                       |-- Validate ID token --->|
  |                    |                       |   (JWKS)                |
  |                    |<-- Set session cookie --|                       |
  |<-- Redirect to app ---|                   |                         |
```

### 4. Access protected endpoints

After login, session cookie is set automatically:

```bash
# Get current user
curl http://localhost:8000/api/auth/me \
  -H "Cookie: rem_session=..."

# Protected API endpoint
curl http://localhost:8000/api/v1/chat/completions \
  -H "Cookie: rem_session=..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic:claude-sonnet-4-5-20250929",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### 5. Logout

```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -H "Cookie: rem_session=..."
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/auth/google/login` | Initiate Google OAuth flow |
| GET | `/api/auth/google/callback` | Google OAuth callback |
| GET | `/api/auth/microsoft/login` | Initiate Microsoft OAuth flow |
| GET | `/api/auth/microsoft/callback` | Microsoft OAuth callback |
| POST | `/api/auth/logout` | Clear session |
| GET | `/api/auth/me` | Get current user info |

## Security Features

### OAuth 2.1 Compliance

- **PKCE**: All flows use code_challenge (S256 method)
- **State**: CSRF protection on all authorization requests
- **Nonce**: ID token replay protection
- **No implicit flow**: Only authorization code flow supported
- **JWKS validation**: ID tokens validated with provider's public keys

### Session Security

- **HTTPOnly cookies**: Session cookies not accessible to JavaScript
- **SameSite=Lax**: CSRF protection for cookie-based auth
- **Secure flag**: HTTPS-only cookies in production
- **Short expiration**: 1 hour session lifetime (configurable)

### Middleware Protection

- Protects `/api/v1/*` endpoints
- Excludes `/api/auth/*` and public endpoints
- Returns 401 for API requests (JSON)
- Redirects to login for browser requests

## Provider-Specific Features

### Google

- **Hosted domain restriction**: Limit to Google Workspace domain
- **Offline access**: Request refresh tokens
- **Incremental authorization**: Add scopes incrementally

```bash
AUTH__GOOGLE__HOSTED_DOMAIN=example.com  # Google Workspace only
```

### Microsoft

- **Multi-tenant support**: common/organizations/consumers
- **Conditional access**: Honors Entra ID policies
- **Microsoft Graph**: Access user profile via Graph API

```bash
AUTH__MICROSOFT__TENANT=common           # Multi-tenant
AUTH__MICROSOFT__TENANT=organizations    # Work/school only
AUTH__MICROSOFT__TENANT=consumers        # Personal accounts
AUTH__MICROSOFT__TENANT=contoso.com      # Single tenant
```

## Architecture

```
rem/src/rem/auth/
├── __init__.py              # Module exports
├── README.md                # This file
├── middleware.py            # FastAPI auth middleware
├── providers/               # OAuth provider implementations
│   ├── __init__.py
│   ├── base.py             # Base OAuth provider (kept for reference)
│   ├── google.py           # Google provider (kept for reference)
│   └── microsoft.py        # Microsoft provider (kept for reference)
```

**Note**: Provider classes in `providers/` are kept for reference but not used.
The implementation uses Authlib's built-in provider support via `server_metadata_url`.

## Testing

```bash
# Test Google login flow
open http://localhost:8000/api/auth/google/login

# Test Microsoft login flow
open http://localhost:8000/api/auth/microsoft/login

# Check current user
curl http://localhost:8000/api/auth/me
```

## Troubleshooting

### "Authentication is disabled"

Set `AUTH__ENABLED=true` in environment or `.env` file.

### "Unknown provider: google"

Check that `AUTH__GOOGLE__CLIENT_ID` is set. The router only registers providers with valid credentials.

### Redirect URI mismatch

Ensure redirect URI in environment matches exactly what's registered with provider:
- Google: Check Google Cloud Console > Credentials
- Microsoft: Check Azure Portal > App registrations > Authentication

### PKCE errors

Authlib handles PKCE automatically. If you see PKCE errors:
1. Clear browser cookies and sessions
2. Ensure session middleware is registered before auth router
3. Check that `AUTH__SESSION_SECRET` is set

## References

- [OAuth 2.1 Draft](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-v2-1-11)
- [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html)
- [PKCE RFC](https://datatracker.ietf.org/doc/html/rfc7636)
- [Authlib Documentation](https://docs.authlib.org/en/latest/)
- [Google OAuth](https://developers.google.com/identity/protocols/oauth2)
- [Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/)
