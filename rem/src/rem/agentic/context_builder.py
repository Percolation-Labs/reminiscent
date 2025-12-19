"""
Centralized context builder for agent execution.

Session History (ALWAYS loaded with compression):
- Each chat request is a single message, so session history MUST be recovered
- Uses SessionMessageStore with compression to keep context efficient
- Long assistant responses include REM LOOKUP hints: "... [REM LOOKUP session-{id}-msg-{index}] ..."
- Agent can retrieve full content on-demand using REM LOOKUP
- Prevents context window bloat while maintaining conversation continuity

User Context (on-demand by default):
- System message includes REM LOOKUP hint for user profile
- Agent decides whether to load profile based on query
- More efficient for queries that don't need personalization
- Example: "User: sarah@example.com. To load user profile: Use REM LOOKUP \"sarah@example.com\""

User Context (auto-inject when enabled):
- Set CHAT__AUTO_INJECT_USER_CONTEXT=true
- User profile automatically loaded from database and injected into system message
- Simpler for basic chatbots that always need context

Design Pattern:
1. Extract AgentContext from headers (user_id, tenant_id, session_id)
2. If auto-inject enabled: Load User/Session from database
3. If auto-inject disabled: Provide REM LOOKUP hints in system message
4. Construct system message with date + context (injected or hints)
5. Return complete context ready for agent execution

Integration Points:
- API endpoints: build_from_headers() extracts user context from JWT/session headers
- Tests: build_from_test() creates minimal test context without DB
- Settings: CHAT__AUTO_INJECT_* controls auto-inject vs on-demand behavior

Usage (on-demand, default):
    # From FastAPI endpoint
    context, messages = await ContextBuilder.build_from_headers(
        headers=request.headers,
        new_messages=[{"role": "user", "content": "What's next for the API migration?"}]
    )

    # Messages list structure (on-demand):
    # [
    #   {"role": "system", "content": "Today's date: 2025-11-22\nUser: sarah@example.com\nTo load user profile: Use REM LOOKUP \"sarah@example.com\"\nSession ID: sess-123\nTo load session history: Use REM LOOKUP messages?session_id=sess-123"},
    #   {"role": "user", "content": "What's next for the API migration?"}
    # ]

    # Agent receives hints and can decide to load context if needed
    agent = await create_agent(context=context, ...)
    prompt = "\n".join(msg.content for msg in messages)
    result = await agent.run(prompt)

Usage (auto-inject, CHAT__AUTO_INJECT_USER_CONTEXT=true):
    # Messages list structure (auto-inject):
    # [
    #   {"role": "system", "content": "Today's date: 2025-11-22\n\nUser Context (auto-injected):\nSummary: ...\nInterests: ...\n\nSession History (auto-injected, 5 messages):"},
    #   {"role": "user", "content": "Previous message"},
    #   {"role": "assistant", "content": "Previous response"},
    #   {"role": "user", "content": "What's next for the API migration?"}
    # ]

Testing:
    # From CLI/test (no database)
    context, messages = await ContextBuilder.build_from_test(
        user_id="test@rem.ai",
        tenant_id="test-tenant",
        message="Hello"
    )
"""

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from pydantic import BaseModel

from .context import AgentContext
from ..models.entities.user import User
from ..models.entities.message import Message
from ..services.postgres.repository import Repository
from ..services.postgres.service import PostgresService


class ContextMessage(BaseModel):
    """Standard message format for LLM conversations."""

    role: str  # "system", "user", "assistant"
    content: str


class ContextBuilder:
    """
    Centralized builder for agent execution context.

    Handles:
    - User profile loading from database
    - Session history recovery
    - Context message construction
    - Test context generation
    """

    @staticmethod
    async def build_from_headers(
        headers: dict[str, str],
        new_messages: list[dict[str, str]] | None = None,
        db: PostgresService | None = None,
        user_id: str | None = None,
    ) -> tuple[AgentContext, list[ContextMessage]]:
        """
        Build complete context from HTTP headers.

        Session History (ALWAYS loaded with compression):
        - If session_id provided, session history is ALWAYS loaded using SessionMessageStore
        - Compression keeps it efficient with REM LOOKUP hints for long messages
        - Example: "... [Message truncated - REM LOOKUP session-{id}-msg-{index}] ..."
        - Agent can retrieve full content on-demand using REM LOOKUP

        User Context (on-demand by default):
        - System message includes REM LOOKUP hint: "User: {email}. To load user profile: Use REM LOOKUP \"{email}\""
        - Agent decides whether to load profile based on query

        User Context (auto-inject when enabled):
        - Set CHAT__AUTO_INJECT_USER_CONTEXT=true
        - User profile automatically loaded and injected into system message

        Args:
            headers: HTTP request headers (case-insensitive)
            new_messages: New messages from current request
            db: Optional PostgresService (creates if None)
            user_id: Override user_id from JWT token (takes precedence over X-User-Id header)

        Returns:
            Tuple of (AgentContext, messages list)

        Example:
            headers = {"X-User-Id": "sarah@example.com", "X-Session-Id": "sess-123"}
            context, messages = await ContextBuilder.build_from_headers(headers, new_messages)

            # messages structure:
            # [
            #   {"role": "system", "content": "Today's date: 2025-11-22\nUser: sarah@example.com\nTo load user profile: Use REM LOOKUP \"sarah@example.com\""},
            #   {"role": "user", "content": "Previous message"},
            #   {"role": "assistant", "content": "Start of long response... [REM LOOKUP session-123-msg-1] ...end"},
            #   {"role": "user", "content": "New message"}
            # ]
        """
        from ..settings import settings
        from ..services.session.compression import SessionMessageStore

        # Extract AgentContext from headers
        context = AgentContext.from_headers(headers)

        # Override user_id if provided (from JWT token - takes precedence over header)
        if user_id is not None:
            context = AgentContext(
                user_id=user_id,
                tenant_id=context.tenant_id,
                session_id=context.session_id,
                default_model=context.default_model,
                agent_schema_uri=context.agent_schema_uri,
                is_eval=context.is_eval,
            )

        # Initialize DB if not provided and needed (for user context or session history)
        close_db = False
        if db is None and (settings.chat.auto_inject_user_context or context.session_id):
            from ..services.postgres import get_postgres_service
            db = get_postgres_service()
            if db:
                await db.connect()
                close_db = True

        try:
            # Build messages list
            messages: list[ContextMessage] = []

            # Build context hint message
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            context_hint = f"Today's date: {today}."

            # Add user context (auto-inject or on-demand hint)
            if settings.chat.auto_inject_user_context and context.user_id and db:
                # Auto-inject: Load and include user profile
                user_context_content = await ContextBuilder._load_user_context(
                    user_id=context.user_id,
                    tenant_id=context.tenant_id,
                    db=db,
                )
                if user_context_content:
                    context_hint += f"\n\nUser Context (auto-injected):\n{user_context_content}"
                else:
                    context_hint += "\n\nNo user context available (anonymous or new user)."
            elif context.user_id:
                # On-demand: Provide hint to use REM LOOKUP
                # user_id is UUID5 hash of email - load user to get email for display and LOOKUP
                user_repo = Repository(User, "users", db=db)
                user = await user_repo.get_by_id(context.user_id, context.tenant_id)
                if user and user.email:
                    # Show email (more useful than UUID) and LOOKUP hint
                    context_hint += f"\n\nUser: {user.email}"
                    context_hint += f"\nTo load user profile: Use REM LOOKUP \"{user.email}\""
                else:
                    context_hint += f"\n\nUser ID: {context.user_id}"
                    context_hint += "\nUser profile not available."

            # Add system context hint
            messages.append(ContextMessage(role="system", content=context_hint))

            # ALWAYS load session history (if session_id provided)
            # - Long assistant messages are compressed on load with REM LOOKUP hints
            # - Tool messages are never compressed (contain structured metadata)
            if context.session_id and settings.postgres.enabled:
                store = SessionMessageStore(user_id=context.user_id or "default")
                session_history = await store.load_session_messages(
                    session_id=context.session_id,
                    user_id=context.user_id,
                    compress_on_load=True,  # Compress long assistant messages
                )

                # Convert to ContextMessage format
                # For tool messages, wrap content with clear markers so the agent
                # can see previous tool results when the prompt is concatenated
                for msg_dict in session_history:
                    role = msg_dict["role"]
                    content = msg_dict["content"]

                    if role == "tool":
                        # Wrap tool results with clear markers for visibility
                        tool_name = msg_dict.get("tool_name", "unknown")
                        content = f"[TOOL RESULT: {tool_name}]\n{content}\n[/TOOL RESULT]"

                    messages.append(
                        ContextMessage(
                            role=role,
                            content=content,
                        )
                    )

                logger.debug(f"Loaded {len(session_history)} messages for session {context.session_id}")

            # Add new messages from request
            if new_messages:
                for msg in new_messages:
                    messages.append(ContextMessage(**msg))

            return context, messages

        finally:
            if close_db and db:
                await db.disconnect()

    @staticmethod
    async def _load_user_context(
        user_id: str | None,
        tenant_id: str,
        db: PostgresService,
    ) -> str | None:
        """
        Load user profile from database and format as context.

        user_id is always a UUID5 hash of email (bijection).
        Looks up user by their id field in the database.

        Returns formatted string with:
        - User summary (generated by dreaming worker)
        - Current projects
        - Technical interests
        - Preferred topics

        Returns None if user_id not provided or user not found.
        """
        if not user_id:
            return None

        try:
            user_repo = Repository(User, "users", db=db)
            # user_id is UUID5 hash of email - look up by database id
            user = await user_repo.get_by_id(user_id, tenant_id)

            if not user:
                logger.debug(f"User {user_id} not found in tenant {tenant_id}")
                return None

            # Build user context string
            parts = []

            if user.summary:
                parts.append(f"Summary: {user.summary}")

            if user.interests:
                parts.append(f"Interests: {', '.join(user.interests[:5])}")

            if user.preferred_topics:
                parts.append(f"Topics: {', '.join(user.preferred_topics[:5])}")

            # Add full profile from metadata if available
            if user.metadata and "profile" in user.metadata:
                profile = user.metadata["profile"]

                if profile.get("current_projects"):
                    projects = profile["current_projects"]
                    project_names = [p.get("name", "Unnamed") for p in projects[:3]]
                    parts.append(f"Current Projects: {', '.join(project_names)}")

            if not parts:
                return None

            return "\n".join(parts)

        except Exception as e:
            logger.error(f"Failed to load user context: {e}")
            return None


    @staticmethod
    async def build_from_test(
        user_id: str = "test@rem.ai",
        tenant_id: str = "test-tenant",
        session_id: str | None = None,
        message: str = "Hello",
        model: str | None = None,
    ) -> tuple[AgentContext, list[ContextMessage]]:
        """
        Build context for testing (no database lookup).

        Creates minimal context with:
        - Test user (test@rem.ai)
        - Test tenant
        - Context hint with date
        - Single user message

        Args:
            user_id: Test user identifier (default: test@rem.ai)
            tenant_id: Test tenant identifier
            session_id: Optional session ID
            message: User message content
            model: Optional model override

        Returns:
            Tuple of (AgentContext, messages list)

        Example:
            context, messages = await ContextBuilder.build_from_test(
                user_id="test@rem.ai",
                message="What's the weather like?"
            )
        """
        from ..settings import settings

        # Create test context
        context = AgentContext(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            default_model=model or settings.llm.default_model,
        )

        # Build minimal messages
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        context_hint = f"Today's date: {today}.\n\nTest user context: {user_id} (test mode, no profile loaded)."

        messages = [
            ContextMessage(role="system", content=context_hint),
            ContextMessage(role="user", content=message),
        ]

        return context, messages
