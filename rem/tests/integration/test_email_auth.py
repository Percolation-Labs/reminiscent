"""
Integration tests for email authentication flow.

Tests the full passwordless email login flow:
1. Send verification code (user created/updated in DB)
2. Verify code and authenticate

Uses repository pattern - no direct SQL.
"""

import pytest
from unittest.mock import patch

from rem.services.email import EmailService
from rem.services.postgres import PostgresService
from rem.services.postgres.repository import Repository
from rem.models.entities import User


@pytest.fixture
async def db():
    """Provide connected PostgresService."""
    db = PostgresService()
    await db.connect()
    yield db
    await db.disconnect()


@pytest.fixture
def user_repo(db):
    """Provide User repository."""
    return Repository(User, db=db)


@pytest.fixture
def email_service():
    """EmailService with mocked SMTP."""
    service = EmailService(
        smtp_host="smtp.test.com",
        smtp_port=587,
        sender_email="test@example.com",
        sender_name="Test",
        app_password="fake-password",
        login_code_expiry_minutes=10,
    )
    return service


class TestEmailAuthFlow:
    """Test email authentication flow with repository pattern."""

    @pytest.mark.asyncio
    async def test_send_code_creates_user(self, db: PostgresService, user_repo: Repository, email_service: EmailService):
        """Test that send_code creates a new user in DB."""
        test_email = "newuser-test@example.com"

        # Mock email sending
        with patch.object(email_service, 'send_email', return_value=True):
            result = await email_service.send_login_code(
                email=test_email,
                db=db,
                tenant_id="default",
            )

        assert result["success"] is True
        assert result["email"] == test_email
        assert result["user_id"] is not None

        # Verify user was created in DB using repository
        user = await user_repo.get_by_id(result["user_id"], tenant_id="default")
        assert user is not None
        assert user.email == test_email
        assert user.metadata.get("login_code") is not None

    @pytest.mark.asyncio
    async def test_send_code_updates_existing_user(self, db: PostgresService, user_repo: Repository, email_service: EmailService):
        """Test that send_code preserves existing user data."""
        test_email = "existinguser-test@example.com"
        user_id = email_service.generate_user_id_from_email(test_email)

        # Create existing user with custom data
        existing_user = User(
            id=user_id,
            tenant_id="default",
            name="Existing User",
            email=test_email,
            tier="pro",
            metadata={"custom_field": "preserved"},
        )
        await user_repo.upsert(existing_user)

        # Send login code
        with patch.object(email_service, 'send_email', return_value=True):
            result = await email_service.send_login_code(
                email=test_email,
                db=db,
                tenant_id="default",
            )

        assert result["success"] is True

        # Verify existing data was preserved
        user = await user_repo.get_by_id(user_id, tenant_id="default")
        assert user.name == "Existing User"
        assert user.tier == "pro"
        assert user.metadata.get("custom_field") == "preserved"
        assert user.metadata.get("login_code") is not None

    @pytest.mark.asyncio
    async def test_verify_code_success(self, db: PostgresService, user_repo: Repository, email_service: EmailService):
        """Test successful code verification."""
        test_email = "verify-test@example.com"

        # Send code first
        with patch.object(email_service, 'send_email', return_value=True):
            send_result = await email_service.send_login_code(
                email=test_email,
                db=db,
                tenant_id="default",
            )

        # Get the code from the user
        user = await user_repo.get_by_id(send_result["user_id"], tenant_id="default")
        code = user.metadata.get("login_code")

        # Verify the code
        verify_result = await email_service.verify_login_code(
            email=test_email,
            code=code,
            db=db,
            tenant_id="default",
        )

        assert verify_result["valid"] is True
        assert verify_result["user_id"] == send_result["user_id"]

        # Verify code was cleared from metadata
        user = await user_repo.get_by_id(send_result["user_id"], tenant_id="default")
        assert user.metadata.get("login_code") is None
        assert user.metadata.get("login_code_expires_at") is None

    @pytest.mark.asyncio
    async def test_verify_code_invalid(self, db: PostgresService, email_service: EmailService):
        """Test verification with wrong code."""
        test_email = "invalid-code-test@example.com"

        # Send code first
        with patch.object(email_service, 'send_email', return_value=True):
            await email_service.send_login_code(
                email=test_email,
                db=db,
                tenant_id="default",
            )

        # Try wrong code
        verify_result = await email_service.verify_login_code(
            email=test_email,
            code="000000",  # Wrong code
            db=db,
            tenant_id="default",
        )

        assert verify_result["valid"] is False
        assert verify_result["error"] == "Invalid login code"

    @pytest.mark.asyncio
    async def test_verify_code_user_not_found(self, db: PostgresService, email_service: EmailService):
        """Test verification for non-existent user."""
        verify_result = await email_service.verify_login_code(
            email="nonexistent@example.com",
            code="123456",
            db=db,
            tenant_id="default",
        )

        assert verify_result["valid"] is False
        assert verify_result["error"] == "User not found"

    @pytest.mark.asyncio
    async def test_deterministic_user_id(self, email_service: EmailService):
        """Test that same email always produces same user ID."""
        email = "deterministic@example.com"

        id1 = email_service.generate_user_id_from_email(email)
        id2 = email_service.generate_user_id_from_email(email)
        id3 = email_service.generate_user_id_from_email(email.upper())  # Case insensitive
        id4 = email_service.generate_user_id_from_email(f"  {email}  ")  # Whitespace trimmed

        assert id1 == id2
        assert id1 == id3
        assert id1 == id4
