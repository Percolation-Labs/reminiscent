"""
Email Service.

Provides methods for sending transactional emails via SMTP.
Supports passwordless login via email codes.
"""

import uuid
import random
import string
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TYPE_CHECKING

from .templates import EmailTemplate, login_code_template, welcome_template

if TYPE_CHECKING:
    from ..postgres import PostgresService

logger = logging.getLogger(__name__)


class EmailService:
    """Service for sending transactional emails and passwordless login."""

    # Store last login code for mock mode testing
    _last_login_code: dict[str, str] = {}

    def __init__(
        self,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        app_password: str | None = None,
        use_tls: bool = True,
        login_code_expiry_minutes: int = 10,
        mock_mode: bool | None = None,
    ):
        """
        Initialize EmailService.

        If no arguments provided, uses settings from rem.settings.
        This allows no-arg construction for simple usage.

        Args:
            smtp_host: SMTP server host
            smtp_port: SMTP server port
            sender_email: Sender email address
            sender_name: Sender display name
            app_password: SMTP app password
            use_tls: Use TLS encryption
            login_code_expiry_minutes: Login code expiry in minutes
            mock_mode: If True, don't send real emails (log code instead)
        """
        # Import settings lazily to avoid circular imports
        from ...settings import settings

        self._smtp_host = smtp_host or settings.email.smtp_host
        self._smtp_port = smtp_port or settings.email.smtp_port
        self._sender_email = sender_email or settings.email.sender_email
        self._sender_name = sender_name or settings.email.sender_name
        self._app_password = app_password or settings.email.app_password
        self._use_tls = use_tls
        self._login_code_expiry_minutes = (
            login_code_expiry_minutes
            or settings.email.login_code_expiry_minutes
        )

        # Mock mode: enabled via setting or if not configured
        if mock_mode is not None:
            self._mock_mode = mock_mode
        elif hasattr(settings.email, 'mock_mode'):
            self._mock_mode = settings.email.mock_mode
        else:
            # Auto-enable mock mode if email is not configured
            self._mock_mode = not self._app_password

        if not self._app_password and not self._mock_mode:
            logger.warning(
                "Email app password not configured. "
                "Set EMAIL__APP_PASSWORD to enable email sending."
            )

        if self._mock_mode:
            logger.info(
                "Email service running in MOCK MODE. "
                "Codes will be logged but not emailed."
            )

    @property
    def is_configured(self) -> bool:
        """Check if email service is properly configured (or in mock mode)."""
        return self._mock_mode or bool(self._sender_email and self._app_password)

    def _create_smtp_connection(self) -> smtplib.SMTP:
        """Create and authenticate SMTP connection."""
        server = smtplib.SMTP(self._smtp_host, self._smtp_port)

        if self._use_tls:
            server.starttls()

        server.login(self._sender_email, self._app_password)
        return server

    def send_email(
        self,
        to_email: str,
        template: EmailTemplate,
        reply_to: Optional[str] = None,
    ) -> bool:
        """
        Send an email using a template.

        Args:
            to_email: Recipient email address
            template: EmailTemplate with subject and HTML body
            reply_to: Optional reply-to address

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.is_configured:
            logger.error("Email service not configured. Cannot send email.")
            return False

        # Mock mode - log but don't send
        if self._mock_mode:
            logger.info(
                f"[MOCK EMAIL] To: {to_email}, Subject: {template.subject}"
            )
            return True

        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = template.subject
            msg["From"] = f"{self._sender_name} <{self._sender_email}>"
            msg["To"] = to_email

            if reply_to:
                msg["Reply-To"] = reply_to

            # Attach HTML body
            html_part = MIMEText(template.html_body, "html", "utf-8")
            msg.attach(html_part)

            # Send email
            with self._create_smtp_connection() as server:
                server.sendmail(
                    self._sender_email,
                    to_email,
                    msg.as_string(),
                )

            logger.info(f"Email sent successfully to {to_email}: {template.subject}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"SMTP authentication failed: {e}")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"SMTP error sending email to {to_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending email to {to_email}: {e}")
            return False

    @staticmethod
    def generate_login_code() -> str:
        """
        Generate a 6-digit login code.

        Returns:
            6-digit numeric string
        """
        return "".join(random.choices(string.digits, k=6))

    @classmethod
    def get_mock_code(cls, email: str) -> str | None:
        """
        Get the last login code sent to an email (mock mode only).

        For testing purposes - retrieves the code that would have been
        sent in mock mode.

        Args:
            email: Email address to look up

        Returns:
            The login code or None if not found
        """
        return cls._last_login_code.get(email.lower().strip())

    @staticmethod
    def generate_user_id_from_email(email: str) -> str:
        """
        Generate a deterministic UUID from email address.

        Uses the centralized email_to_user_id() for consistency.
        Same email always produces same UUID (bijection).

        Args:
            email: Email address

        Returns:
            UUID string
        """
        from rem.utils.user_id import email_to_user_id
        return email_to_user_id(email)

    async def send_login_code(
        self,
        email: str,
        db: "PostgresService | None" = None,
        tenant_id: str = "default",
        template_kwargs: dict | None = None,
    ) -> dict:
        """
        Send a login code to an email address.

        Access control logic:
        1. If user exists and tier is BLOCKED -> reject with "Account blocked"
        2. If user exists and tier is not BLOCKED -> allow (send code)
        3. If user doesn't exist -> check trusted_email_domains setting:
           - If domain is trusted (or no restrictions) -> create user and send code
           - If domain is not trusted -> reject with "Domain not allowed"

        This method:
        1. Generates a 6-digit login code
        2. Checks user existence and access permissions
        3. Upserts the user with login code in metadata
        4. Sends the code via email

        Args:
            email: User's email address
            db: PostgresService instance for repository operations
            tenant_id: Tenant identifier for multi-tenancy
            template_kwargs: Additional arguments for template customization

        Returns:
            Dict with status and details:
            {
                "success": bool,
                "email": str,
                "user_id": str,
                "code_sent": bool,
                "expires_at": str (ISO format),
                "error": str (if failed)
            }
        """
        from ...settings import settings

        email = email.lower().strip()
        code = self.generate_login_code()
        user_id = self.generate_user_id_from_email(email)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self._login_code_expiry_minutes
        )

        result = {
            "success": False,
            "email": email,
            "user_id": user_id,
            "code_sent": False,
            "expires_at": expires_at.isoformat(),
        }

        # Check user access and upsert login code using repository
        if db:
            try:
                access_result = await self._check_and_upsert_user_login_code(
                    db=db,
                    email=email,
                    user_id=user_id,
                    code=code,
                    expires_at=expires_at,
                    tenant_id=tenant_id,
                    settings=settings,
                )
                if not access_result["allowed"]:
                    result["error"] = access_result["error"]
                    return result
            except Exception as e:
                logger.error(f"Failed to upsert user login code: {e}")
                result["error"] = "Failed to store login code"
                return result

        # Send the email with branding from settings
        # Merge settings.email.template_kwargs with any explicit overrides
        kwargs = {**settings.email.template_kwargs, **(template_kwargs or {})}
        template = login_code_template(code=code, email=email, **kwargs)
        sent = self.send_email(to_email=email, template=template)

        if sent:
            result["success"] = True
            result["code_sent"] = True

            # Store code for mock mode retrieval
            if self._mock_mode:
                EmailService._last_login_code[email] = code
                logger.info(
                    f"[MOCK MODE] Login code for {email}: {code} "
                    f"(expires at {expires_at.isoformat()})"
                )

            logger.info(
                f"Login code sent to {email}, "
                f"user_id={user_id}, expires at {expires_at.isoformat()}"
            )
        else:
            result["error"] = "Failed to send email"

        return result

    async def _check_and_upsert_user_login_code(
        self,
        db: "PostgresService",
        email: str,
        user_id: str,
        code: str,
        expires_at: datetime,
        tenant_id: str = "default",
        settings: Any = None,
    ) -> dict:
        """
        Check user access and upsert login code in metadata using repository pattern.

        Access control logic:
        1. If user exists and tier is BLOCKED -> reject
        2. If user exists and tier is not BLOCKED -> allow and update
        3. If user doesn't exist -> check trusted_email_domains:
           - If domain is trusted -> create user
           - If domain is not trusted -> reject

        Args:
            db: PostgresService instance
            email: User's email
            user_id: Deterministic UUID from email
            code: Generated login code
            expires_at: Code expiration datetime
            tenant_id: Tenant identifier
            settings: Settings instance for domain checking

        Returns:
            Dict with {"allowed": bool, "error": str | None}
        """
        from ...models.entities import User, UserTier
        from ..postgres.repository import Repository

        now = datetime.now(timezone.utc)
        login_metadata = {
            "login_code": code,
            "login_code_expires_at": expires_at.isoformat(),
            "login_code_sent_at": now.isoformat(),
        }

        # Use repository pattern for User operations
        user_repo = Repository(User, db=db)

        # Try to get existing user first
        existing_user = await user_repo.get_by_id(user_id, tenant_id=tenant_id)

        if existing_user:
            # Check if user is blocked
            if existing_user.tier == UserTier.BLOCKED:
                logger.warning(f"Blocked user attempted login: {email}")
                return {"allowed": False, "error": "Account is blocked"}

            # User exists and is not blocked - merge login code into existing metadata
            existing_user.metadata = {**(existing_user.metadata or {}), **login_metadata}
            existing_user.email = email  # Ensure email is current
            await user_repo.upsert(existing_user)
            return {"allowed": True, "error": None}
        else:
            # New user - first check if they're a subscriber (by email lookup)
            from ...models.entities import Subscriber
            subscriber_repo = Repository(Subscriber, db=db)
            existing_subscriber = await subscriber_repo.find_one({"email": email})

            if existing_subscriber:
                # Subscriber exists - allow them to create account
                # (approved field may not exist in older schemas, so just check existence)
                logger.info(f"Subscriber {email} creating user account")
            elif settings and hasattr(settings, 'email') and settings.email.trusted_domain_list:
                # Not an approved subscriber - check if domain is trusted
                if not settings.email.is_domain_trusted(email):
                    email_domain = email.split("@")[-1]
                    logger.warning(f"Untrusted domain attempted signup: {email_domain}")
                    return {"allowed": False, "error": "Email domain not allowed for signup"}

            # Domain is trusted (or no restrictions) - create new user
            # Users from trusted domains get admin role
            user_role = None
            if settings and hasattr(settings, 'email') and settings.email.trusted_domain_list:
                if settings.email.is_domain_trusted(email):
                    user_role = "admin"
                    logger.info(f"New user {email} assigned admin role (trusted domain)")

            new_user = User(
                id=uuid.UUID(user_id),
                tenant_id=tenant_id,
                user_id=user_id,  # UUID5 hash of email (same as id)
                name=email,  # Full email as entity_key for LOOKUP
                email=email,
                role=user_role,
                metadata=login_metadata,
            )
            await user_repo.upsert(new_user)
            return {"allowed": True, "error": None}

    async def verify_login_code(
        self,
        email: str,
        code: str,
        db: "PostgresService",
        tenant_id: str = "default",
    ) -> dict:
        """
        Verify a login code for an email address.

        On success, clears the code from metadata and returns user info.

        Args:
            email: User's email address
            code: The login code to verify
            db: PostgresService instance
            tenant_id: Tenant identifier

        Returns:
            Dict with verification result:
            {
                "valid": bool,
                "user_id": str (if valid),
                "email": str,
                "error": str (if invalid)
            }
        """
        from ...models.entities import User
        from ..postgres.repository import Repository

        email = email.lower().strip()
        user_id = self.generate_user_id_from_email(email)

        result = {
            "valid": False,
            "email": email,
        }

        try:
            # Use repository pattern for User operations
            user_repo = Repository(User, db=db)

            # Get user by deterministic ID
            user = await user_repo.get_by_id(user_id, tenant_id=tenant_id)

            if not user:
                result["error"] = "User not found"
                return result

            metadata = user.metadata or {}
            stored_code = metadata.get("login_code")
            expires_at_str = metadata.get("login_code_expires_at")

            if not stored_code or not expires_at_str:
                result["error"] = "No login code requested"
                return result

            # Check expiration
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now(timezone.utc) > expires_at:
                result["error"] = "Login code expired"
                return result

            # Check code match
            if stored_code != code:
                result["error"] = "Invalid login code"
                return result

            # Code is valid - clear it from metadata
            user.metadata = {
                k: v for k, v in metadata.items()
                if k not in ("login_code", "login_code_expires_at", "login_code_sent_at")
            }
            await user_repo.upsert(user)

            result["valid"] = True
            result["user_id"] = str(user.id)
            logger.info(f"Login code verified for {email}, user_id={result['user_id']}")

        except Exception as e:
            logger.error(f"Error verifying login code: {e}")
            result["error"] = "Verification failed"

        return result

    async def send_welcome_email(
        self,
        email: str,
        name: Optional[str] = None,
        template_kwargs: dict | None = None,
    ) -> bool:
        """
        Send a welcome email to a new user.

        Args:
            email: User's email address
            name: Optional user's name
            template_kwargs: Additional arguments for template customization

        Returns:
            True if sent successfully
        """
        from ...settings import settings

        # Merge settings.email.template_kwargs with any explicit overrides
        kwargs = {**settings.email.template_kwargs, **(template_kwargs or {})}
        template = welcome_template(name=name, **kwargs)
        return self.send_email(to_email=email, template=template)
