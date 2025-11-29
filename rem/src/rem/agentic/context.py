"""
Agent execution context and configuration.

Design pattern for session context that can be constructed from:
- HTTP headers (X-User-Id, X-Session-Id, X-Model-Name)
- Direct instantiation for testing/CLI

Key Design Pattern 
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
    def from_headers(cls, headers: dict[str, str]) -> "AgentContext":
        """
        Construct AgentContext from HTTP headers.

        Reads standard headers:
        - X-User-Id: User identifier
        - X-Tenant-Id: Tenant identifier
        - X-Session-Id: Session identifier
        - X-Model-Name: Model override
        - X-Agent-Schema: Agent schema URI

        Args:
            headers: Dictionary of HTTP headers (case-insensitive)

        Returns:
            AgentContext with values from headers

        Example:
            headers = {
                "X-User-Id": "user123",
                "X-Tenant-Id": "acme-corp",
                "X-Session-Id": "sess-456",
                "X-Model-Name": "anthropic:claude-opus-4-20250514"
            }
            context = AgentContext.from_headers(headers)
        """
        # Normalize header keys to lowercase for case-insensitive lookup
        normalized = {k.lower(): v for k, v in headers.items()}

        return cls(
            user_id=normalized.get("x-user-id"),
            tenant_id=normalized.get("x-tenant-id", "default"),
            session_id=normalized.get("x-session-id"),
            default_model=normalized.get("x-model-name") or settings.llm.default_model,
            agent_schema_uri=normalized.get("x-agent-schema"),
        )
