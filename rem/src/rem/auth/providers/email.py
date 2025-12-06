"""
Email Authentication Provider.

Passwordless authentication using email verification codes.
Unlike OAuth providers, this handles the full flow internally.

Flow:
1. User requests login with email address
2. System generates code, upserts user, sends email
3. User enters code
4. System verifies code and creates session

Design:
- Uses EmailService for sending codes
- Creates users with deterministic UUID from email hash
- Stores challenge in user metadata
- No external OAuth dependencies
"""

from typing import TYPE_CHECKING
from pydantic import BaseModel, Field
from loguru import logger

from ...services.email import EmailService

if TYPE_CHECKING:
    from ...services.postgres import PostgresService


class EmailAuthResult(BaseModel):
    """Result of email authentication operations."""

    success: bool = Field(description="Whether operation succeeded")
    email: str = Field(description="Email address")
    user_id: str | None = Field(default=None, description="User ID if authenticated")
    error: str | None = Field(default=None, description="Error message if failed")
    message: str | None = Field(default=None, description="User-friendly message")


class EmailAuthProvider:
    """
    Email-based passwordless authentication provider.

    Handles the complete email login flow:
    1. send_code() - Generate and send verification code
    2. verify_code() - Verify code and return user info
    """

    def __init__(
        self,
        email_service: EmailService | None = None,
        template_kwargs: dict | None = None,
    ):
        """
        Initialize EmailAuthProvider.

        Args:
            email_service: EmailService instance (creates new one if not provided)
            template_kwargs: Customization for email templates (colors, branding, etc.)
        """
        self._email_service = email_service or EmailService()
        self._template_kwargs = template_kwargs or {}

    @property
    def is_configured(self) -> bool:
        """Check if email auth is properly configured."""
        return self._email_service.is_configured

    async def send_code(
        self,
        email: str,
        db: "PostgresService",
        tenant_id: str = "default",
    ) -> EmailAuthResult:
        """
        Send a verification code to an email address.

        Creates user if not exists (using deterministic UUID from email).
        Stores code in user metadata.

        Args:
            email: Email address to send code to
            db: PostgresService instance
            tenant_id: Tenant identifier

        Returns:
            EmailAuthResult with success status
        """
        if not self.is_configured:
            return EmailAuthResult(
                success=False,
                email=email,
                error="Email service not configured",
                message="Email login is not available. Please try another method.",
            )

        try:
            result = await self._email_service.send_login_code(
                email=email,
                db=db,
                tenant_id=tenant_id,
                template_kwargs=self._template_kwargs,
            )

            if result["success"]:
                return EmailAuthResult(
                    success=True,
                    email=email,
                    user_id=result["user_id"],
                    message=f"Verification code sent to {email}. Check your inbox.",
                )
            else:
                return EmailAuthResult(
                    success=False,
                    email=email,
                    error=result.get("error", "Failed to send code"),
                    message="Failed to send verification code. Please try again.",
                )

        except Exception as e:
            logger.error(f"Error sending login code: {e}")
            return EmailAuthResult(
                success=False,
                email=email,
                error=str(e),
                message="An error occurred. Please try again.",
            )

    async def verify_code(
        self,
        email: str,
        code: str,
        db: "PostgresService",
        tenant_id: str = "default",
    ) -> EmailAuthResult:
        """
        Verify a login code and authenticate user.

        Args:
            email: Email address
            code: 6-digit verification code
            db: PostgresService instance
            tenant_id: Tenant identifier

        Returns:
            EmailAuthResult with user_id if successful
        """
        try:
            result = await self._email_service.verify_login_code(
                email=email,
                code=code,
                db=db,
                tenant_id=tenant_id,
            )

            if result["valid"]:
                return EmailAuthResult(
                    success=True,
                    email=email,
                    user_id=result["user_id"],
                    message="Successfully authenticated!",
                )
            else:
                error = result.get("error", "Invalid code")
                # User-friendly error messages
                if error == "Login code expired":
                    message = "Your code has expired. Please request a new one."
                elif error == "Invalid login code":
                    message = "Invalid code. Please check and try again."
                elif error == "No login code requested":
                    message = "No code was requested for this email. Please request a new code."
                elif error == "User not found":
                    message = "Email not found. Please request a login code first."
                else:
                    message = "Verification failed. Please try again."

                return EmailAuthResult(
                    success=False,
                    email=email,
                    error=error,
                    message=message,
                )

        except Exception as e:
            logger.error(f"Error verifying login code: {e}")
            return EmailAuthResult(
                success=False,
                email=email,
                error=str(e),
                message="An error occurred. Please try again.",
            )

    def get_user_dict(self, email: str, user_id: str) -> dict:
        """
        Create a user dict for session storage.

        Compatible with OAuth user format for consistent session handling.

        Args:
            email: User's email
            user_id: User's UUID

        Returns:
            User dict for session
        """
        return {
            "id": user_id,
            "email": email,
            "email_verified": True,  # Email is verified through code
            "name": email.split("@")[0],  # Use email prefix as name
            "provider": "email",
            "tenant_id": "default",
            "tier": "free",  # Email users start at free tier
            "roles": ["user"],
        }
