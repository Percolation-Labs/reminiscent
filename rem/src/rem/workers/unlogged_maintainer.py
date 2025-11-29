"""
UNLOGGED Table Maintainer.

Handles backup (snapshot) and restore of PostgreSQL UNLOGGED tables:
- kv_store: O(1) entity lookups, graph edges for REM queries
- rate_limits: Rate limiting counters

UNLOGGED tables are NOT replicated to standby servers and are truncated
on crash/restart. This worker ensures they are rebuilt after:
1. Primary pod restart
2. Failover to a replica (replica has empty UNLOGGED tables)
3. Crash recovery

Modes:
    --snapshot           Push current state to S3 watermark
    --restore            Force rebuild kv_store from entity tables
    --check-and-restore  Check if rebuild needed, restore if so (idempotent)

Triggers:
    1. Argo Events: Watches CNPG Cluster CR for status.currentPrimary changes
    2. CronJob: Periodic check every 5 minutes (belt & suspenders)
    3. Manual: python -m rem.workers.unlogged_maintainer --restore

Usage:
    python -m rem.workers.unlogged_maintainer --check-and-restore
    python -m rem.workers.unlogged_maintainer --snapshot
    python -m rem.workers.unlogged_maintainer --restore

    # Kubernetes Job (triggered by Argo Events or CronJob):
    # command: ["python", "-m", "rem.workers.unlogged_maintainer", "--check-and-restore"]
"""

import asyncio
import json
import time
from typing import Any

import click
from loguru import logger

from ..services.postgres import get_postgres_service
from ..registry import get_model_registry
from ..utils.date_utils import utc_now


# Advisory lock ID for preventing concurrent rebuilds
# Using a fixed large integer that's unlikely to collide
REBUILD_LOCK_ID = 2147483647


class UnloggedMaintainer:
    """
    Maintains UNLOGGED tables across PostgreSQL restarts and failovers.

    UNLOGGED tables (kv_store, rate_limits) provide high-performance caching
    but are not persisted to WAL and not replicated. They are truncated:
    - On primary crash/restart
    - On failover (replicas have empty UNLOGGED tables by design)

    This class provides:
    - Detection: Check if rebuild is needed (kv_store empty but entities exist)
    - Restore: Rebuild kv_store from entity tables using rebuild_kv_store()
    - Snapshot: Push watermark to S3 for observability and future delta rebuilds
    """

    def __init__(self):
        self.db = get_postgres_service()
        self._s3 = None  # Lazy load

    @property
    def s3(self):
        """Lazy load S3 provider."""
        if self._s3 is None:
            from ..services.fs.s3_provider import S3Provider
            self._s3 = S3Provider()
        return self._s3

    def _get_watermark_uri(self) -> str:
        """Get S3 URI for watermark state file."""
        from ..settings import settings
        # Use the main bucket with a state/ prefix
        return f"s3://{settings.s3.bucket_name}/state/unlogged-watermark.json"

    def _get_entity_tables(self) -> list[str]:
        """
        Get list of entity tables that feed into kv_store.

        These are the tables that have kv_store triggers and should
        have data if kv_store needs to be populated.
        """
        # Get from registry - these are the CoreModel tables
        registry = get_model_registry()
        models = registry.get_models(include_core=True)

        # Convert model names to table names (pluralize, lowercase)
        tables = []
        for name, ext in models.items():
            if ext.table_name:
                tables.append(ext.table_name)
            else:
                # Default: lowercase + 's' (e.g., Resource -> resources)
                table_name = name.lower()
                if not table_name.endswith('s'):
                    table_name += 's'
                tables.append(table_name)

        # Filter to tables that actually have kv_store triggers
        # These are the main entity tables
        kv_tables = ['resources', 'moments', 'users', 'schemas', 'files', 'messages']
        return [t for t in tables if t in kv_tables]

    async def is_primary(self) -> bool:
        """
        Check if we're connected to the primary (not a replica).

        UNLOGGED tables cannot be accessed on replicas - they error with:
        "cannot access temporary or unlogged relations during recovery"
        """
        try:
            result = await self.db.fetchval("SELECT NOT pg_is_in_recovery()")
            return bool(result)
        except Exception as e:
            logger.warning(f"Could not determine primary status: {e}")
            return False

    async def get_kv_store_count(self) -> int:
        """Get count of entries in kv_store."""
        try:
            count = await self.db.fetchval("SELECT count(*) FROM kv_store")
            return int(count) if count else 0
        except Exception as e:
            # If we get an error about UNLOGGED tables, we're on a replica
            if "cannot access" in str(e) or "recovery" in str(e):
                logger.warning("Cannot access kv_store (likely on replica)")
                return -1  # Signal that we can't access
            raise

    async def get_entity_counts(self) -> dict[str, int]:
        """Get counts from all entity tables."""
        counts = {}
        for table in self._get_entity_tables():
            try:
                count = await self.db.fetchval(
                    f"SELECT count(*) FROM {table} WHERE deleted_at IS NULL"
                )
                counts[table] = int(count) if count else 0
            except Exception as e:
                logger.warning(f"Could not count {table}: {e}")
                counts[table] = 0
        return counts

    async def check_rebuild_needed(self) -> tuple[bool, str]:
        """
        Check if UNLOGGED tables need to be rebuilt.

        Returns:
            Tuple of (needs_rebuild: bool, reason: str)

        Detection logic:
        1. Must be connected to primary (replicas can't access UNLOGGED tables)
        2. kv_store is empty (count = 0)
        3. At least one entity table has data
        """
        # Check if we're on primary
        if not await self.is_primary():
            return False, "Connected to replica, skipping (UNLOGGED tables not accessible)"

        # Check kv_store count
        kv_count = await self.get_kv_store_count()
        if kv_count < 0:
            return False, "Cannot access kv_store"

        if kv_count > 0:
            return False, f"kv_store has {kv_count} entries, no rebuild needed"

        # kv_store is empty - check if entities exist
        entity_counts = await self.get_entity_counts()
        total_entities = sum(entity_counts.values())

        if total_entities == 0:
            return False, "kv_store empty but no entities exist (fresh database)"

        # Rebuild needed!
        tables_with_data = [t for t, c in entity_counts.items() if c > 0]
        return True, (
            f"kv_store empty but {total_entities} entities exist in "
            f"{tables_with_data}. Likely failover or restart."
        )

    async def check_and_rebuild_if_needed(self) -> bool:
        """
        Check if UNLOGGED tables need rebuild and restore if so.

        This is the main entry point for automated triggers.
        Safe to call multiple times (idempotent).

        Returns:
            True if rebuild was performed, False otherwise
        """
        needs_rebuild, reason = await self.check_rebuild_needed()

        if not needs_rebuild:
            logger.info(f"No rebuild needed: {reason}")
            return False

        logger.warning(f"Rebuild needed: {reason}")
        await self.rebuild_with_lock()
        return True

    async def rebuild_with_lock(self) -> dict[str, Any]:
        """
        Rebuild kv_store with advisory lock to prevent concurrent rebuilds.

        Uses PostgreSQL advisory locks to ensure only one rebuild runs at a time,
        even across multiple pods/processes.

        Returns:
            Dict with rebuild statistics
        """
        # Try to acquire advisory lock (non-blocking)
        locked = await self.db.fetchval(
            "SELECT pg_try_advisory_lock($1)", REBUILD_LOCK_ID
        )

        if not locked:
            logger.info("Another process is rebuilding, skipping")
            return {"skipped": True, "reason": "lock_held"}

        try:
            logger.info("Acquired rebuild lock, starting kv_store rebuild...")
            start_time = time.time()

            # Call the PostgreSQL rebuild function
            results = await self.db.fetch("SELECT * FROM rebuild_kv_store()")

            duration_ms = (time.time() - start_time) * 1000

            # Parse results
            tables_rebuilt = []
            total_rows = 0
            for row in results:
                table_name = row.get('table_name', 'unknown')
                rows_inserted = row.get('rows_inserted', 0)
                tables_rebuilt.append(table_name)
                total_rows += rows_inserted
                logger.info(f"  Rebuilt {rows_inserted} entries for {table_name}")

            logger.success(
                f"Rebuilt kv_store: {total_rows} entries "
                f"from {len(tables_rebuilt)} tables in {duration_ms:.0f}ms"
            )

            # Push watermark to S3
            await self.push_watermark()

            return {
                "success": True,
                "tables_rebuilt": tables_rebuilt,
                "total_rows": total_rows,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            logger.error(f"Rebuild failed: {e}")
            raise

        finally:
            # Always release the lock
            await self.db.fetch(
                "SELECT pg_advisory_unlock($1)", REBUILD_LOCK_ID
            )
            logger.debug("Released rebuild lock")

    async def push_watermark(self) -> dict[str, Any]:
        """
        Push current state to S3 watermark for observability and delta rebuilds.

        Watermark contains:
        - Timestamp of snapshot
        - Current primary instance info
        - kv_store count
        - Per-table entity counts and max updated_at timestamps

        Returns:
            The watermark dict that was written
        """
        try:
            # Get current state
            kv_count = await self.get_kv_store_count()

            # Get server info
            server_info = await self.db.fetchval(
                "SELECT inet_server_addr()::text || ':' || inet_server_port()::text"
            )

            # Get per-table stats with max updated_at for delta rebuild
            tables = {}
            for table in self._get_entity_tables():
                try:
                    row = await self.db.fetchrow(f"""
                        SELECT
                            count(*) as count,
                            max(updated_at) as max_updated
                        FROM {table}
                        WHERE deleted_at IS NULL
                    """)
                    tables[table] = {
                        "count": int(row['count']) if row['count'] else 0,
                        "max_updated_at": (
                            row['max_updated'].isoformat()
                            if row['max_updated'] else None
                        ),
                    }
                except Exception as e:
                    logger.warning(f"Could not get stats for {table}: {e}")
                    tables[table] = {"count": 0, "max_updated_at": None}

            watermark = {
                "snapshot_ts": utc_now().isoformat(),
                "primary_instance": server_info,
                "kv_store_count": kv_count,
                "tables": tables,
            }

            # Write to S3
            uri = self._get_watermark_uri()
            self.s3.write(uri, watermark)

            logger.info(
                f"Pushed watermark to S3: kv_store={kv_count}, "
                f"tables={list(tables.keys())}"
            )

            return watermark

        except Exception as e:
            logger.error(f"Failed to push watermark to S3: {e}")
            # Don't fail the rebuild if watermark push fails
            return {"error": str(e)}

    async def read_watermark(self) -> dict[str, Any] | None:
        """
        Read watermark from S3.

        Returns:
            Watermark dict or None if not found
        """
        try:
            uri = self._get_watermark_uri()
            if self.s3.exists(uri):
                return self.s3.read(uri)
            return None
        except Exception as e:
            logger.warning(f"Could not read watermark from S3: {e}")
            return None


async def _run_maintainer(
    snapshot: bool,
    restore: bool,
    check_and_restore: bool,
) -> int:
    """
    Async entry point for the maintainer.

    Returns exit code (0 for success, 1 for error).
    """
    maintainer = UnloggedMaintainer()

    try:
        await maintainer.db.connect()

        if snapshot:
            logger.info("Pushing watermark snapshot to S3...")
            result = await maintainer.push_watermark()
            if "error" in result:
                logger.error(f"Snapshot failed: {result['error']}")
                return 1
            logger.success("Watermark snapshot complete")
            return 0

        elif restore:
            logger.info("Forcing kv_store rebuild...")
            result = await maintainer.rebuild_with_lock()
            if result.get("skipped"):
                logger.warning(f"Rebuild skipped: {result.get('reason')}")
                return 0
            if result.get("success"):
                logger.success(
                    f"Rebuild complete: {result['total_rows']} rows "
                    f"in {result['duration_ms']:.0f}ms"
                )
                return 0
            return 1

        elif check_and_restore:
            logger.info("Checking if rebuild is needed...")
            rebuilt = await maintainer.check_and_rebuild_if_needed()
            if rebuilt:
                logger.success("Rebuild completed successfully")
            else:
                logger.info("No rebuild was needed")
            return 0

        else:
            # Default: check and restore
            logger.info("No mode specified, defaulting to --check-and-restore")
            await maintainer.check_and_rebuild_if_needed()
            return 0

    except Exception as e:
        logger.exception(f"Maintainer failed: {e}")
        return 1

    finally:
        await maintainer.db.disconnect()


@click.command()
@click.option(
    '--snapshot',
    is_flag=True,
    help='Push current state to S3 watermark (for observability)',
)
@click.option(
    '--restore',
    is_flag=True,
    help='Force rebuild kv_store from entity tables',
)
@click.option(
    '--check-and-restore',
    'check_and_restore',
    is_flag=True,
    help='Check if rebuild needed, restore if so (idempotent, default)',
)
def main(snapshot: bool, restore: bool, check_and_restore: bool):
    """
    UNLOGGED Table Maintainer for REM.

    Ensures kv_store and other UNLOGGED tables are rebuilt after
    PostgreSQL restarts or failovers.

    \b
    Examples:
        # Check and rebuild if needed (safe to run anytime)
        python -m rem.workers.unlogged_maintainer --check-and-restore

        # Force rebuild (useful for manual recovery)
        python -m rem.workers.unlogged_maintainer --restore

        # Push snapshot to S3 (for monitoring)
        python -m rem.workers.unlogged_maintainer --snapshot
    """
    # If no mode specified, default to check-and-restore
    if not any([snapshot, restore, check_and_restore]):
        check_and_restore = True

    exit_code = asyncio.run(_run_maintainer(snapshot, restore, check_and_restore))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
