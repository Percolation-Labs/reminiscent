"""
PostgreSQL LISTEN/NOTIFY Database Listener Worker.

A lightweight, always-running worker that listens for PostgreSQL NOTIFY events
and dispatches them to configurable handlers (SQS, REST API, or custom jobs).

Architecture Overview
---------------------

PostgreSQL's LISTEN/NOTIFY is a pub/sub mechanism built into the database:

    1. Application code issues: NOTIFY channel_name, 'payload'
    2. All clients LISTENing on that channel receive the notification
    3. Notifications are delivered in transaction commit order
    4. If no listeners, the notification is simply dropped (fire-and-forget)

This worker maintains a dedicated connection that LISTENs on configured channels
and dispatches notifications to external systems.

Why LISTEN/NOTIFY?
------------------

From https://brandur.org/notifier:

    - **Single connection per process**: Efficient use of Postgres connections
    - **Non-blocking**: Notifications are delivered asynchronously
    - **Delivery guarantees**: Delivered in commit order within a transaction
    - **Resilience**: If the worker is down, the source data remains in tables
      for catch-up processing on restart

This is ideal for:

    - Syncing data to external systems (Phoenix, webhooks, etc.)
    - Triggering async jobs without polling
    - Event-driven architectures with PostgreSQL as the source of truth

Typical Flow
------------

    1. Trigger on table INSERT/UPDATE sends NOTIFY with row ID
    2. This worker receives the notification
    3. Worker dispatches to configured handler:
       - SQS: Publish message for downstream processing
       - REST: Make HTTP call to internal API endpoint
       - Custom: Execute registered Python handler

Example: Feedback Sync to Phoenix
---------------------------------

    -- In PostgreSQL (trigger on feedbacks table):
    CREATE OR REPLACE FUNCTION notify_feedback_insert()
    RETURNS TRIGGER AS $$
    BEGIN
        PERFORM pg_notify('feedback_sync', json_build_object(
            'id', NEW.id,
            'table', 'feedbacks',
            'action', 'insert'
        )::text);
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER feedback_insert_notify
        AFTER INSERT ON feedbacks
        FOR EACH ROW
        EXECUTE FUNCTION notify_feedback_insert();

    -- Worker config (environment variables):
    DB_LISTENER__CHANNELS=feedback_sync,entity_update
    DB_LISTENER__HANDLER_TYPE=rest
    DB_LISTENER__REST_ENDPOINT=http://localhost:8000/api/v1/internal/events

Deployment
----------

Run as a single-replica Kubernetes Deployment:

    - Always running (not scaled by KEDA)
    - Single replica to avoid duplicate processing
    - Uses Pod Identity for AWS credentials (if SQS handler)
    - Graceful shutdown on SIGTERM

Handler Types
-------------

1. **SQS Handler** (DB_LISTENER__HANDLER_TYPE=sqs):
   - Publishes notification payload to SQS queue
   - Queue consumers process asynchronously
   - Good for: Fan-out, durable processing, existing SQS consumers

2. **REST Handler** (DB_LISTENER__HANDLER_TYPE=rest):
   - POSTs notification to configured endpoint
   - Expects 2xx response for success
   - Good for: Simple webhook patterns, internal API calls

3. **Custom Handler** (Python code):
   - Register handlers via `register_handler(channel, async_fn)`
   - Handler receives (channel, payload) tuple
   - Good for: Complex logic, multiple actions per event

Connection Management
---------------------

The worker uses a dedicated asyncpg connection (not from the pool) because:

    1. LISTEN requires a persistent connection
    2. Pool connections may be returned/closed unexpectedly
    3. We need to handle reconnection on connection loss

The connection is separate from PostgresService's pool to avoid interference.

Error Handling
--------------

    - Connection loss: Automatic reconnection with exponential backoff
    - Handler failure: Logged but doesn't crash the worker
    - Graceful shutdown: SIGTERM triggers clean disconnect

Catch-up Processing
-------------------

NOTIFY is fire-and-forget - if the worker is down, notifications are lost.
For critical data, implement catch-up on startup:

    async def catch_up():
        '''Process records missed while worker was down.'''
        records = await db.fetch(
            "SELECT id FROM feedbacks WHERE phoenix_synced = false"
        )
        for record in records:
            await process_feedback(record['id'])

References
----------

    - PostgreSQL NOTIFY: https://www.postgresql.org/docs/current/sql-notify.html
    - PostgreSQL LISTEN: https://www.postgresql.org/docs/18/sql-listen.html
    - asyncpg notifications: https://magicstack.github.io/asyncpg/current/api/index.html#connection-notifications
    - Brandur's Notifier pattern: https://brandur.org/notifier
"""

import asyncio
import json
import signal
import sys
from typing import Any, Callable, Awaitable

import asyncpg
from loguru import logger

from rem.settings import settings


# Type alias for notification handlers
NotificationHandler = Callable[[str, str], Awaitable[None]]


class DBListener:
    """
    PostgreSQL LISTEN/NOTIFY worker.

    Listens on configured channels and dispatches notifications to handlers.
    Designed to run as a single-replica Kubernetes deployment.

    Attributes:
        channels: List of PostgreSQL channels to LISTEN on
        handler_type: Dispatch method ('sqs', 'rest', or 'custom')
        running: Flag to control the main loop
        connection: Dedicated asyncpg connection for LISTEN

    Example:
        >>> listener = DBListener()
        >>> listener.register_handler('feedback_sync', my_handler)
        >>> await listener.run()
    """

    def __init__(self):
        """
        Initialize the database listener.

        Reads configuration from settings.db_listener:
            - channels: Comma-separated list of channels to listen on
            - handler_type: 'sqs', 'rest', or 'custom'
            - sqs_queue_url: Queue URL for SQS handler
            - rest_endpoint: URL for REST handler
            - reconnect_delay: Initial delay between reconnection attempts
            - max_reconnect_delay: Maximum delay between reconnection attempts
        """
        self.channels: list[str] = settings.db_listener.channel_list
        self.handler_type: str = settings.db_listener.handler_type
        self.running: bool = True
        self.connection: asyncpg.Connection | None = None

        # Custom handlers registered via register_handler()
        self._custom_handlers: dict[str, NotificationHandler] = {}

        # Reconnection backoff
        self._reconnect_delay = settings.db_listener.reconnect_delay
        self._max_reconnect_delay = settings.db_listener.max_reconnect_delay

        # Handler clients (lazy-initialized)
        self._sqs_client = None
        self._http_client = None

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum: int, frame: Any) -> None:
        """
        Handle shutdown signals (SIGTERM, SIGINT).

        Sets running=False to trigger graceful shutdown of the main loop.
        The worker will finish processing the current notification before exiting.
        """
        logger.info(f"Received shutdown signal ({signum}), stopping listener...")
        self.running = False

    def register_handler(self, channel: str, handler: NotificationHandler) -> None:
        """
        Register a custom handler for a specific channel.

        Custom handlers are called when handler_type='custom' and a notification
        arrives on the specified channel.

        Args:
            channel: PostgreSQL channel name
            handler: Async function taking (channel, payload) arguments

        Example:
            >>> async def handle_feedback(channel: str, payload: str):
            ...     data = json.loads(payload)
            ...     await sync_to_phoenix(data['id'])
            ...
            >>> listener.register_handler('feedback_sync', handle_feedback)
        """
        self._custom_handlers[channel] = handler
        logger.info(f"Registered custom handler for channel: {channel}")

    async def _connect(self) -> asyncpg.Connection:
        """
        Establish a dedicated connection for LISTEN.

        This connection is separate from the PostgresService pool because:
        1. LISTEN requires a persistent connection
        2. Pool connections may be returned/closed
        3. We need full control for reconnection logic

        Returns:
            asyncpg.Connection: Dedicated connection for notifications

        Raises:
            asyncpg.PostgresError: If connection fails after retries
        """
        connection_string = settings.postgres.connection_string

        # Connection with keepalive for long-running listener
        conn = await asyncpg.connect(
            connection_string,
            # TCP keepalive to detect dead connections
            # These settings help detect network issues faster
            server_settings={
                'application_name': 'rem-db-listener',
            },
        )

        logger.info("Database connection established for LISTEN")
        return conn

    async def _setup_listeners(self) -> None:
        """
        Subscribe to all configured channels.

        Issues LISTEN command for each channel in self.channels.
        Must be called after connection is established.
        """
        if not self.connection:
            raise RuntimeError("Connection not established")

        for channel in self.channels:
            await self.connection.execute(f"LISTEN {channel}")
            logger.info(f"Listening on channel: {channel}")

    async def _dispatch_notification(self, channel: str, payload: str) -> None:
        """
        Dispatch a notification to the configured handler.

        Routes the notification based on handler_type setting:
        - 'sqs': Publish to SQS queue
        - 'rest': POST to REST endpoint
        - 'custom': Call registered Python handler

        Args:
            channel: The PostgreSQL channel that received the notification
            payload: The notification payload (typically JSON string)
        """
        logger.debug(f"Received notification on {channel}: {payload[:100]}...")

        try:
            if self.handler_type == 'sqs':
                await self._dispatch_to_sqs(channel, payload)
            elif self.handler_type == 'rest':
                await self._dispatch_to_rest(channel, payload)
            elif self.handler_type == 'custom':
                await self._dispatch_to_custom(channel, payload)
            else:
                logger.warning(f"Unknown handler type: {self.handler_type}")

        except Exception as e:
            # Log and continue - don't crash the worker on handler failure
            logger.error(f"Handler failed for {channel}: {e}", exc_info=True)

    async def _dispatch_to_sqs(self, channel: str, payload: str) -> None:
        """
        Publish notification to SQS queue.

        Creates a message with the notification payload and channel metadata.
        Uses boto3 with IRSA credentials in Kubernetes.

        Args:
            channel: Source channel for message attributes
            payload: Notification payload as message body
        """
        import boto3

        if not self._sqs_client:
            self._sqs_client = boto3.client('sqs', region_name=settings.sqs.region)

        queue_url = settings.db_listener.sqs_queue_url
        if not queue_url:
            logger.error("SQS queue URL not configured (DB_LISTENER__SQS_QUEUE_URL)")
            return

        # Build message with channel as attribute
        message = {
            'QueueUrl': queue_url,
            'MessageBody': payload,
            'MessageAttributes': {
                'channel': {
                    'DataType': 'String',
                    'StringValue': channel,
                },
                'source': {
                    'DataType': 'String',
                    'StringValue': 'db_listener',
                },
            },
        }

        response = self._sqs_client.send_message(**message)
        logger.debug(f"Published to SQS: {response['MessageId']}")

    async def _dispatch_to_rest(self, channel: str, payload: str) -> None:
        """
        POST notification to REST endpoint.

        Sends the notification as JSON to the configured endpoint.
        Expects a 2xx response for success.

        Args:
            channel: Included in request body
            payload: Notification payload (will be parsed if JSON)
        """
        import httpx

        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=30.0)

        endpoint = settings.db_listener.rest_endpoint
        if not endpoint:
            logger.error("REST endpoint not configured (DB_LISTENER__REST_ENDPOINT)")
            return

        # Parse payload if it's JSON
        try:
            payload_data = json.loads(payload)
        except json.JSONDecodeError:
            payload_data = payload

        # Build request body
        body = {
            'channel': channel,
            'payload': payload_data,
            'source': 'db_listener',
        }

        response = await self._http_client.post(endpoint, json=body)
        response.raise_for_status()
        logger.debug(f"REST dispatch success: {response.status_code}")

    async def _dispatch_to_custom(self, channel: str, payload: str) -> None:
        """
        Call registered custom handler for the channel.

        Looks up the handler registered via register_handler() and calls it.
        If no handler is registered for the channel, logs a warning.

        Args:
            channel: Used to find the registered handler
            payload: Passed to the handler function
        """
        handler = self._custom_handlers.get(channel)
        if not handler:
            logger.warning(f"No custom handler registered for channel: {channel}")
            return

        await handler(channel, payload)
        logger.debug(f"Custom handler completed for {channel}")

    async def _notification_callback(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """
        Callback invoked by asyncpg when a notification arrives.

        This is called by asyncpg's event loop integration whenever a NOTIFY
        is received on any subscribed channel.

        Args:
            connection: The connection that received the notification
            pid: Process ID of the notifying backend
            channel: The channel name
            payload: The notification payload
        """
        await self._dispatch_notification(channel, payload)

    async def run(self) -> None:
        """
        Main worker loop.

        Establishes connection, subscribes to channels, and processes
        notifications until shutdown is signaled.

        Handles:
        - Initial connection with retry
        - Automatic reconnection on connection loss
        - Graceful shutdown on SIGTERM/SIGINT

        Example:
            >>> listener = DBListener()
            >>> await listener.run()  # Runs until SIGTERM
        """
        if not self.channels:
            logger.error("No channels configured (DB_LISTENER__CHANNELS)")
            sys.exit(1)

        logger.info(f"Starting DB Listener worker")
        logger.info(f"Channels: {', '.join(self.channels)}")
        logger.info(f"Handler type: {self.handler_type}")

        reconnect_delay = self._reconnect_delay

        while self.running:
            try:
                # Establish connection
                self.connection = await self._connect()

                # Register notification callback
                self.connection.add_listener('*', self._notification_callback)

                # Subscribe to channels
                await self._setup_listeners()

                # Reset reconnect delay on successful connection
                reconnect_delay = self._reconnect_delay

                # Wait for notifications (or shutdown)
                # The callback handles actual notification processing
                while self.running:
                    # Check connection health periodically
                    # asyncpg handles notifications in the background
                    await asyncio.sleep(1.0)

                    # Verify connection is still alive
                    if self.connection.is_closed():
                        logger.warning("Connection closed, reconnecting...")
                        break

            except asyncpg.PostgresError as e:
                logger.error(f"Database error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
            finally:
                # Clean up connection
                if self.connection and not self.connection.is_closed():
                    await self.connection.close()
                    self.connection = None

            # Reconnect with backoff (unless shutting down)
            if self.running:
                logger.info(f"Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                # Exponential backoff with max
                reconnect_delay = min(reconnect_delay * 2, self._max_reconnect_delay)

        # Cleanup
        if self._http_client:
            await self._http_client.aclose()

        logger.info("DB Listener stopped")

    async def catch_up(self, query: str, handler: NotificationHandler) -> int:
        """
        Process records missed while the worker was down.

        NOTIFY is fire-and-forget - if the worker wasn't running, notifications
        are lost. For critical data, call this on startup to catch up.

        Args:
            query: SQL query that returns rows with an 'id' column
            handler: Async function to process each record

        Returns:
            Number of records processed

        Example:
            >>> # Catch up on unsynced feedback records
            >>> count = await listener.catch_up(
            ...     "SELECT id FROM feedbacks WHERE phoenix_synced = false",
            ...     handle_feedback
            ... )
            >>> logger.info(f"Caught up {count} records")
        """
        from rem.services.postgres import get_postgres_service

        db = get_postgres_service()
        if not db:
            logger.warning("PostgreSQL not available for catch-up")
            return 0

        await db.connect()
        try:
            records = await db.fetch(query)
            count = 0

            for record in records:
                try:
                    # Convert record to JSON payload
                    payload = json.dumps(dict(record))
                    await handler('catch_up', payload)
                    count += 1
                except Exception as e:
                    logger.error(f"Catch-up failed for record: {e}")

            logger.info(f"Catch-up completed: {count}/{len(records)} records")
            return count

        finally:
            await db.disconnect()


def main() -> None:
    """
    Entry point for containerized deployment.

    Runs the DB Listener worker until SIGTERM.

    Usage:
        python -m rem.workers.db_listener
    """
    logger.info("REM DB Listener Worker")
    logger.info(f"Environment: {settings.environment}")

    if not settings.db_listener.enabled:
        logger.warning("DB Listener is disabled (DB_LISTENER__ENABLED=false)")
        sys.exit(0)

    listener = DBListener()

    # Run the async main loop
    asyncio.run(listener.run())


if __name__ == "__main__":
    main()
