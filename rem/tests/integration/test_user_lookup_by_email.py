"""
Integration test for user LOOKUP by email.

Tests the fix for the bug where users were stored with 'name' as entity_key
but context_builder was using user_id (email) for LOOKUP hints.

Convention:
- Users are stored with email as the 'name' field (entity_key)
- This allows O(1) LOOKUP by email via KV store
- Example: REM LOOKUP "sarah@example.com" returns user profile

Test Flow:
1. Create user with email as entity_key
2. Verify user is stored in KV store with email as key
3. Execute REM LOOKUP by email
4. Verify user profile is returned

Requires:
- Running PostgreSQL instance (docker compose -f docker-compose.test.yml up -d)
- POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5051/rem"
"""

import pytest
from datetime import datetime, timezone

from rem.models.entities.user import User, UserTier
from rem.services.postgres import PostgresService, Repository
from rem.services.user_service import UserService
from rem.services.rem.service import RemService
from rem.models.core import RemQuery, QueryType, LookupParameters
from rem.utils.user_id import email_to_user_id


@pytest.fixture
async def postgres_service() -> PostgresService:
    """Create PostgresService instance."""
    pg = PostgresService()
    await pg.connect()
    yield pg
    await pg.disconnect()


@pytest.fixture
async def user_service(postgres_service) -> UserService:
    """Create UserService instance."""
    return UserService(postgres_service)


@pytest.fixture
async def rem_service(postgres_service) -> RemService:
    """Create RemService instance."""
    return RemService(postgres_service)


class TestUserLookupByEmail:
    """Test LOOKUP operation for users by email."""

    TEST_EMAIL = "test-lookup@example.com"
    TEST_TENANT = "test-tenant"

    @pytest.fixture(autouse=True)
    async def cleanup(self, postgres_service):
        """Clean up test data before and after each test."""
        # Hard delete from users table and kv_store to ensure clean state
        await postgres_service.execute(
            "DELETE FROM kv_store WHERE entity_key = $1",
            (self.TEST_EMAIL,)
        )
        await postgres_service.execute(
            "DELETE FROM users WHERE email = $1",
            (self.TEST_EMAIL,)
        )

        yield

        # Clean up after test - hard delete
        await postgres_service.execute(
            "DELETE FROM kv_store WHERE entity_key = $1",
            (self.TEST_EMAIL,)
        )
        await postgres_service.execute(
            "DELETE FROM users WHERE email = $1",
            (self.TEST_EMAIL,)
        )

    async def test_user_created_with_email_as_name(self, user_service, postgres_service):
        """Test that get_or_create_user sets email as name and user_id as UUID hash."""
        # Create user via service
        user = await user_service.get_or_create_user(
            email=self.TEST_EMAIL,
            tenant_id=self.TEST_TENANT,
        )

        # Verify user was created correctly
        assert user.email == self.TEST_EMAIL
        assert user.name == self.TEST_EMAIL, \
            f"User name should be email for LOOKUP, got: {user.name}"
        # user_id is UUID5 hash of email (bijection)
        expected_user_id = email_to_user_id(self.TEST_EMAIL)
        assert user.user_id == expected_user_id, \
            f"User user_id should be UUID hash of email, got: {user.user_id}"

    async def test_user_in_kv_store_by_email(self, user_service, postgres_service):
        """Test that user is stored in KV store with email as entity_key."""
        # Create user
        user = await user_service.get_or_create_user(
            email=self.TEST_EMAIL,
            tenant_id=self.TEST_TENANT,
        )

        # Query KV store directly
        query = """
            SELECT entity_key, entity_type, entity_id
            FROM kv_store
            WHERE entity_key = $1
        """
        results = await postgres_service.execute(query, (self.TEST_EMAIL,))

        assert len(results) == 1, \
            f"Expected 1 KV entry for email, got {len(results)}"
        assert results[0]["entity_key"] == self.TEST_EMAIL
        assert results[0]["entity_type"] == "users"

    async def test_rem_lookup_by_email(self, user_service, rem_service, postgres_service):
        """Test that REM LOOKUP by email returns user profile."""
        # Create user with summary
        user = await user_service.get_or_create_user(
            email=self.TEST_EMAIL,
            tenant_id=self.TEST_TENANT,
        )

        # Update user with summary (simulating dreaming worker)
        user.summary = "Test user for LOOKUP integration test"
        user.interests = ["testing", "databases"]
        user.preferred_topics = ["rem-queries", "user-management"]

        user_repo = Repository(User, "users", db=postgres_service)
        await user_repo.upsert(user)

        # Execute REM LOOKUP by email
        # user_id is UUID5 hash of email (bijection)
        # KV store entity_key = email (name field)
        hashed_user_id = email_to_user_id(self.TEST_EMAIL)
        query = RemQuery(
            query_type=QueryType.LOOKUP,
            parameters=LookupParameters(key=self.TEST_EMAIL),
            user_id=hashed_user_id,  # Query as the user (UUID hash)
        )
        result = await rem_service.execute_query(query)

        assert result["query_type"] == "LOOKUP"
        assert result["count"] == 1, \
            f"Expected 1 result for LOOKUP by email, got {result['count']}"

        user_data = result["results"][0]["data"]
        assert user_data["email"] == self.TEST_EMAIL
        assert user_data["name"] == self.TEST_EMAIL
        assert user_data["summary"] == "Test user for LOOKUP integration test"

    async def test_context_builder_lookup_format(self, user_service, postgres_service):
        """Test that context_builder generates correct LOOKUP hint in system message."""
        from rem.agentic.context_builder import ContextBuilder

        # First create the user so context_builder can find them
        user = await user_service.get_or_create_user(
            email=self.TEST_EMAIL,
            tenant_id=self.TEST_TENANT,
        )

        # Build context using build_from_headers (on-demand mode)
        # user_id is UUID5 hash of email (what JWT would provide)
        hashed_user_id = email_to_user_id(self.TEST_EMAIL)
        headers = {
            "X-User-Id": hashed_user_id,
            "X-Tenant-Id": self.TEST_TENANT,
        }
        new_messages = [{"role": "user", "content": "Hello"}]

        context, messages = await ContextBuilder.build_from_headers(
            headers=headers,
            new_messages=new_messages,
            db=postgres_service,
            user_id=hashed_user_id,
        )

        # Verify context has hashed user_id
        assert context.user_id == hashed_user_id

        # Find system message
        system_messages = [m for m in messages if m.role == "system"]
        assert len(system_messages) >= 1, "Should have at least one system message"

        system_content = system_messages[0].content

        # Verify system message shows email (more useful than UUID) and LOOKUP hint
        assert f'User: {self.TEST_EMAIL}' in system_content, \
            f"System message should show user email. Got: {system_content}"
        assert f'REM LOOKUP "{self.TEST_EMAIL}"' in system_content, \
            f"System message should contain LOOKUP hint with EMAIL. Got: {system_content}"

        # Verify it does NOT have the old formats
        assert f'users/{self.TEST_EMAIL}' not in system_content, \
            f"System message should NOT have old 'users/' prefix format. Got: {system_content}"
        assert hashed_user_id not in system_content, \
            f"System message should show email, not UUID. Got: {system_content}"

    async def test_user_lookup_with_special_chars_in_email(self, user_service, rem_service, postgres_service):
        """Test LOOKUP works with emails containing special characters."""
        special_email = "test+lookup.special@sub.example.com"

        # Hard delete cleanup
        await postgres_service.execute(
            "DELETE FROM kv_store WHERE entity_key = $1",
            (special_email,)
        )
        await postgres_service.execute(
            "DELETE FROM users WHERE email = $1",
            (special_email,)
        )

        try:
            # Create user
            user = await user_service.get_or_create_user(
                email=special_email,
                tenant_id=self.TEST_TENANT,
            )

            assert user.name == special_email

            # LOOKUP by email with special chars
            # user_id is UUID5 hash of email
            hashed_special_user_id = email_to_user_id(special_email)
            query = RemQuery(
                query_type=QueryType.LOOKUP,
                parameters=LookupParameters(key=special_email),
                user_id=hashed_special_user_id,
            )
            result = await rem_service.execute_query(query)

            assert result["count"] == 1
            assert result["results"][0]["data"]["email"] == special_email

        finally:
            # Hard delete cleanup
            await postgres_service.execute(
                "DELETE FROM kv_store WHERE entity_key = $1",
                (special_email,)
            )
            await postgres_service.execute(
                "DELETE FROM users WHERE email = $1",
                (special_email,)
            )


if __name__ == "__main__":
    """
    Run tests manually for development.

    Usage:
        docker compose -f docker-compose.test.yml up -d
        POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5051/rem" \\
            pytest tests/integration/test_user_lookup_by_email.py -v
    """
    print("Running User LOOKUP by Email integration tests...")
    print("\nPrerequisites:")
    print("  docker compose -f docker-compose.test.yml up -d")
    print("\nTo run with pytest:")
    print('  POSTGRES__CONNECTION_STRING="postgresql://rem:rem@localhost:5051/rem" \\')
    print("      pytest tests/integration/test_user_lookup_by_email.py -v")
