"""
Rate Limit Service - Postgres-backed rate limiting.

Implements tenant-aware, tiered rate limiting using PostgreSQL UNLOGGED tables
for high performance. Supports monthly quotas and short-term burst limits.
"""

import random
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from loguru import logger

from ..models.entities.user import UserTier
from .postgres.service import PostgresService


class RateLimitService:
    """
    Service for tracking and enforcing API rate limits.
    
    Uses an UNLOGGED table `rate_limits` for performance.
    Note: Counts in UNLOGGED tables may be lost on database crash/restart.
    """

    def __init__(self, db: PostgresService):
        self.db = db
        
        # Rate limits configuration
        # Format: (limit, period_seconds)
        # This is a simple implementation. In production, move to settings.
        self.TIER_CONFIG = {
            UserTier.ANONYMOUS: {"limit": 1000, "period": 3600},  # 1000/hour (for testing)
            UserTier.FREE: {"limit": 50, "period": 2592000},      # 50/month (~30 days)
            UserTier.BASIC: {"limit": 10000, "period": 2592000},  # 10k/month
            UserTier.PRO: {"limit": 100000, "period": 2592000},   # 100k/month
        }

    async def check_rate_limit(
        self, 
        tenant_id: str, 
        identifier: str, 
        tier: UserTier
    ) -> tuple[bool, int, int]:
        """
        Check if request is allowed under the rate limit.

        Args:
            tenant_id: Tenant identifier
            identifier: User ID or Anonymous ID
            tier: User subscription tier

        Returns:
            Tuple (is_allowed, current_count, limit)
        """
        config = self.TIER_CONFIG.get(tier, self.TIER_CONFIG[UserTier.FREE])
        limit = config["limit"]
        period = config["period"]
        
        # Construct time-window key
        now = datetime.now(timezone.utc)
        
        if period >= 2592000: # Monthly
            time_key = now.strftime("%Y-%m") 
        elif period >= 86400: # Daily
            time_key = now.strftime("%Y-%m-%d")
        elif period >= 3600: # Hourly
            time_key = now.strftime("%Y-%m-%d-%H")
        else: # Minute/Second (fallback)
            time_key = int(now.timestamp() / period)

        key = f"{tenant_id}:{identifier}:{tier.value}:{time_key}"
        
        # Calculate expiry (for cleanup)
        expires_at = now.timestamp() + period

        # Atomic UPSERT to increment counter
        # Returns the new count
        query = """
            INSERT INTO rate_limits (key, count, expires_at)
            VALUES ($1, 1, to_timestamp($2))
            ON CONFLICT (key) DO UPDATE
            SET count = rate_limits.count + 1
            RETURNING count;
        """
        
        try:
            count = await self.db.fetchval(query, key, expires_at)
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Fail open to avoid blocking users on DB error
            return True, 0, limit

        is_allowed = count <= limit
        
        # Probabilistic cleanup (1% chance)
        if random.random() < 0.01:
            await self.cleanup_expired()
            
        return is_allowed, count, limit

    async def cleanup_expired(self):
        """Remove expired rate limit keys."""
        try:
            # Use a small limit to avoid locking/long queries
            query = """
                DELETE FROM rate_limits 
                WHERE expires_at < NOW()
            """
            await self.db.execute(query)
        except Exception as e:
            logger.warning(f"Rate limit cleanup failed: {e}")
