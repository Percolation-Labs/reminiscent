"""
Agent execution context and configuration.

Design pattern for session context that can be constructed from:
- FastAPI Request object (preferred - extracts user from JWT via request.state)
- HTTP headers (X-User-Id, X-Session-Id, X-Model-Name, X-Is-Eval, etc.)
- Direct instantiation for testing/CLI

User ID Sources (in priority order):
1. request.state.user.id - From JWT token validated by auth middleware (SECURE)
2. X-User-Id header - Fallback for backwards compatibility (less secure)

Headers Mapping:
    X-Tenant-Id      → context.tenant_id (default: "default")
    X-Session-Id     → context.session_id
    X-Agent-Schema   → context.agent_schema_uri (default: "rem")
    X-Model-Name     → context.default_model
    X-Is-Eval        → context.is_eval (marks session as evaluation)

Key Design Pattern:
- AgentContext is passed to agent factory, not stored in agents
- Enables session tracking across API, CLI, and test execution
- Supports header-based configuration override (model, schema URI)
- Clean separation: context (who/what) vs agent (how)
"""

from loguru import logger
from pydantic import BaseModel, Field

from ..settings import settings


class AgentContext(BaseModel):
    """
    Session and configuration context for agent execution.

    Provides session identifiers (user_id, tenant_id, session_id) and
    configuration defaults (model) for agent factory and execution.

    Design Pattern 
    - Construct from HTTP headers via from_headers()
    - Pass to agent factory, not stored in agent
    - Enables header-based model/schema override
    - Supports observability (user tracking, session continuity)

    Example:
        # From HTTP request
        context = AgentContext.from_headers(request.headers)
        agent = await create_agent(context)

        # Direct construction for testing
        context = AgentContext(user_id="test-user", tenant_id="test-tenant")
        agent = await create_agent(context)
    """

    user_id: str | None = Field(
        default=None,
        description="User identifier for tracking and personalization",
    )

    tenant_id: str = Field(
        default="default",
        description="Tenant identifier for multi-tenancy isolation (REM requirement)",
    )

    session_id: str | None = Field(
        default=None,
        description="Session/conversation identifier for continuity",
    )

    default_model: str = Field(
        default_factory=lambda: settings.llm.default_model,
        description="Default LLM model (can be overridden via headers)",
    )

    agent_schema_uri: str | None = Field(
        default=None,
        description="Agent schema URI (e.g., 'rem-agents-query-agent')",
    )

    is_eval: bool = Field(
        default=False,
        description="Whether this is an evaluation session (set via X-Is-Eval header)",
    )

    model_config = {"populate_by_name": True}

    @staticmethod
    def get_user_id_or_default(
        user_id: str | None,
        source: str = "context",
        default: str | None = None,
    ) -> str | None:
        """
        Get user_id or return None for anonymous access.

        User ID convention:
        - user_id is a deterministic UUID5 hash of the user's email address
        - Use rem.utils.user_id.email_to_user_id(email) to generate
        - The JWT's `sub` claim is NOT directly used as user_id
        - Authentication middleware extracts email from JWT and hashes it

        When user_id is None, queries return data with user_id IS NULL
        (shared/public data). This is intentional - no fake user IDs.

        Args:
            user_id: User identifier (UUID5 hash of email, may be None for anonymous)
            source: Source of the call (for logging clarity)
            default: Explicit default (only for testing, not auto-generated)

        Returns:
            user_id if provided, explicit default if provided, otherwise None

        Example:
            # Generate user_id from email (done by auth middleware)
            from rem.utils.user_id import email_to_user_id
            user_id = email_to_user_id("alice@example.com")
            # -> "2c5ea4c0-4067-5fef-942d-0a20124e06d8"

            # In MCP tool - anonymous user sees shared data
            user_id = AgentContext.get_user_id_or_default(
                user_id, source="ask_rem_agent"
            )
            # Returns None if not authenticated -> queries WHERE user_id IS NULL
        """
        if user_id is not None:
            return user_id
        if default is not None:
            logger.debug(f"Using explicit default user_id '{default}' from {source}")
            return default
        # No fake user IDs - return None for anonymous/unauthenticated
        logger.debug(f"No user_id from {source}, using None (anonymous/shared data)")
        return None

    @classmethod
    def from_request(cls, request: "Request") -> "AgentContext":
        """
        Construct AgentContext from a FastAPI Request object.

        This is the PREFERRED method for API endpoints. It extracts user_id
        from the authenticated user in request.state (set by auth middleware
        from JWT token), which is more secure than trusting X-User-Id header.

        Priority for user_id:
        1. request.state.user.id - From validated JWT token (SECURE)
        2. X-User-Id header - Fallback for backwards compatibility

        Args:
            request: FastAPI Request object

        Returns:
            AgentContext with user from JWT and other values from headers

        Example:
            @app.post("/api/v1/chat/completions")
            async def chat(request: Request, body: ChatRequest):
                context = AgentContext.from_request(request)
                # context.user_id is from JWT, not header
        """
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from starlette.requests import Request

        # Get headers dict
        headers = dict(request.headers)
        normalized = {k.lower(): v for k, v in headers.items()}

        # Extract user_id from authenticated user (JWT) - this is the source of truth
        user_id = None
        tenant_id = "default"

        if hasattr(request, "state"):
            user = getattr(request.state, "user", None)
            if user and isinstance(user, dict):
                user_id = user.get("id")
                # Also get tenant_id from authenticated user if available
                if user.get("tenant_id"):
                    tenant_id = user.get("tenant_id")
                if user_id:
                    logger.debug(f"User ID from JWT: {user_id}")

        # Fallback to X-User-Id header if no authenticated user
        if not user_id:
            user_id = normalized.get("x-user-id")
            if user_id:
                logger.debug(f"User ID from X-User-Id header (fallback): {user_id}")

        # Override tenant_id from header if provided
        header_tenant = normalized.get("x-tenant-id")
        if header_tenant:
            tenant_id = header_tenant

        # Parse X-Is-Eval header
        is_eval_str = normalized.get("x-is-eval", "").lower()
        is_eval = is_eval_str in ("true", "1", "yes")

        return cls(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=normalized.get("x-session-id"),
            default_model=normalized.get("x-model-name") or settings.llm.default_model,
            agent_schema_uri=normalized.get("x-agent-schema"),
            is_eval=is_eval,
        )

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> "AgentContext":
        """
        Construct AgentContext from HTTP headers dict.

        NOTE: Prefer from_request() for API endpoints as it extracts user_id
        from the validated JWT token in request.state, which is more secure.

        Reads standard headers:
        - X-User-Id: User identifier (fallback - prefer JWT)
        - X-Tenant-Id: Tenant identifier
        - X-Session-Id: Session identifier
        - X-Model-Name: Model override
        - X-Agent-Schema: Agent schema URI
        - X-Is-Eval: Whether this is an evaluation session (true/false)

        Args:
            headers: Dictionary of HTTP headers (case-insensitive)

        Returns:
            AgentContext with values from headers

        Example:
            headers = {
                "X-User-Id": "user123",
                "X-Tenant-Id": "acme-corp",
                "X-Session-Id": "sess-456",
                "X-Model-Name": "anthropic:claude-opus-4-20250514",
                "X-Is-Eval": "true"
            }
            context = AgentContext.from_headers(headers)
        """
        # Normalize header keys to lowercase for case-insensitive lookup
        normalized = {k.lower(): v for k, v in headers.items()}

        # Parse X-Is-Eval header (accepts "true", "1", "yes" as truthy)
        is_eval_str = normalized.get("x-is-eval", "").lower()
        is_eval = is_eval_str in ("true", "1", "yes")

        return cls(
            user_id=normalized.get("x-user-id"),
            tenant_id=normalized.get("x-tenant-id", "default"),
            session_id=normalized.get("x-session-id"),
            default_model=normalized.get("x-model-name") or settings.llm.default_model,
            agent_schema_uri=normalized.get("x-agent-schema"),
            is_eval=is_eval,
        )
