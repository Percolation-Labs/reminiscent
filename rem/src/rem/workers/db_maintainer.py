"""
Database Maintainer Worker.

Handles background maintenance tasks for PostgreSQL:
1. Cleaning up expired rate limit counters (UNLOGGED table).
2. Refreshing materialized views (if any).
3. Vacuuming specific tables (if needed).

Usage:
    python -m rem.workers.db_maintainer
    
    # Or via docker-compose:
    # command: python -m rem.workers.db_maintainer
"""

import asyncio
import signal
from loguru import logger

from ..services.postgres.service import PostgresService
from ..services.rate_limit import RateLimitService

class DatabaseMaintainer:
    def __init__(self):
        self.running = False
        self.db = PostgresService()
        self.rate_limiter = RateLimitService(self.db)

    async def start(self):
        """Start maintenance loop."""
        self.running = True
        logger.info("Starting Database Maintainer Worker")
        
        await self.db.connect()
        
        try:
            while self.running:
                await self._run_maintenance_cycle()
                # Sleep for 5 minutes
                await asyncio.sleep(300)
        finally:
            await self.db.disconnect()

    async def _run_maintenance_cycle(self):
        """Execute maintenance tasks."""
        logger.debug("Running maintenance cycle...")
        
        try:
            # 1. Cleanup Rate Limits
            await self.rate_limiter.cleanup_expired()
            
            # 2. (Future) Refresh Views
            # await self.db.execute("REFRESH MATERIALIZED VIEW ...")
            
        except Exception as e:
            logger.error(f"Maintenance cycle failed: {e}")

    def stop(self):
        """Stop worker gracefully."""
        self.running = False
        logger.info("Stopping Database Maintainer Worker...")

async def main():
    worker = DatabaseMaintainer()
    
    # Handle signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop)
        
    await worker.start()

if __name__ == "__main__":
    asyncio.run(main())
