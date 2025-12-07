"""
User Service - User account management.

Handles user creation, profile updates, and session linking.
"""

from datetime import datetime
from typing import Optional

from loguru import logger

from ..models.entities.user import User, UserTier
from .postgres.repository import Repository
from .postgres.service import PostgresService


class UserService:
    """
    Service for managing user accounts and sessions.
    """

    def __init__(self, db: PostgresService):
        self.db = db
        self.repo = Repository(User, "users", db=db)

    async def get_or_create_user(
        self,
        email: str,
        tenant_id: str = "default",
        name: str = "New User",
        avatar_url: Optional[str] = None,
    ) -> User:
        """
        Get existing user by email or create a new one.
        """
        users = await self.repo.find(filters={"email": email}, limit=1)
        
        if users:
            user = users[0]
            # Update profile if needed (e.g., name/avatar from OAuth)
            updated = False
            if name and user.name == "New User": # Only update if placeholder
                user.name = name
                updated = True
            
            # Store avatar in metadata if provided
            if avatar_url:
                user.metadata = user.metadata or {}
                if user.metadata.get("avatar_url") != avatar_url:
                    user.metadata["avatar_url"] = avatar_url
                    updated = True
            
            if updated:
                user.updated_at = datetime.utcnow()
                await self.repo.upsert(user)
            
            return user
        
        # Create new user
        user = User(
            tenant_id=tenant_id,
            user_id=email, # Use email as user_id for now? Or UUID?
            # The User model has 'user_id' field but also 'id' UUID.
            # Usually user_id is the external ID or email.
            name=name,
            email=email,
            tier=UserTier.FREE,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            metadata={"avatar_url": avatar_url} if avatar_url else {},
        )
        await self.repo.upsert(user)
        logger.info(f"Created new user: {email}")
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """
        Get a user by their UUID.

        Args:
            user_id: The user's UUID

        Returns:
            User if found, None otherwise
        """
        try:
            return await self.repo.get_by_id(user_id)
        except Exception as e:
            logger.warning(f"Could not find user by id {user_id}: {e}")
            return None

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get a user by their email address.

        Args:
            email: The user's email

        Returns:
            User if found, None otherwise
        """
        users = await self.repo.find(filters={"email": email}, limit=1)
        return users[0] if users else None

    async def link_anonymous_session(self, user: User, anon_id: str) -> None:
        """
        Link an anonymous session ID to a user account.
        
        This allows merging history from the anonymous session into the user's profile.
        """
        if not anon_id:
            return

        # Check if already linked
        if anon_id in user.anonymous_ids:
            return

        # Add to list
        user.anonymous_ids.append(anon_id)
        user.updated_at = datetime.utcnow()
        
        # Save
        await self.repo.upsert(user)
        logger.info(f"Linked anonymous session {anon_id} to user {user.email}")
        
        # TODO: Migrate/Merge actual data (rate limit counts, history) if needed.
        # For now, we just link the IDs so future queries can include data from this anon_id.
