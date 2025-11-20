"""
SQS File Processor Worker.

Consumes S3 ObjectCreated events from SQS queue and processes files.
Designed to run as a K8s deployment scaled by KEDA based on queue depth.
"""

import json
import signal
import sys
from typing import Any

import boto3
from botocore.exceptions import ClientError
from loguru import logger

from rem.services.content import ContentService
from rem.settings import settings


class SQSFileProcessor:
    """
    SQS-based file processor worker.

    Polls SQS queue for S3 ObjectCreated events and processes files
    using ContentService.

    Gracefully handles:
    - SIGTERM (K8s pod termination)
    - SIGINT (Ctrl+C for local testing)
    - SQS visibility timeout (message redelivery)
    - DLQ (failed messages after retries)
    """

    def __init__(self):
        self.sqs_client = self._create_sqs_client()
        self.content_service = ContentService()
        self.running = True
        self.processing_message = False

        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _create_sqs_client(self):
        """Create SQS client with IRSA or configured credentials."""
        return boto3.client("sqs", region_name=settings.sqs.region)

    def _handle_shutdown(self, signum, frame):
        """Handle graceful shutdown signals."""
        logger.info(f"Received shutdown signal ({signum}), finishing current message...")
        self.running = False

    def run(self):
        """
        Main worker loop.

        Long polls SQS queue, processes messages, deletes on success.
        Exits gracefully on SIGTERM/SIGINT after completing current message.
        """
        if not settings.sqs.queue_url:
            logger.error("SQS_QUEUE_URL not configured")
            sys.exit(1)

        logger.info(f"Starting file processor worker")
        logger.info(f"Queue: {settings.sqs.queue_url}")
        logger.info(f"Polling interval: {settings.sqs.wait_time_seconds}s (long polling)")

        while self.running:
            try:
                # Long poll for messages
                response = self.sqs_client.receive_message(
                    QueueUrl=settings.sqs.queue_url,
                    MaxNumberOfMessages=settings.sqs.max_messages,
                    WaitTimeSeconds=settings.sqs.wait_time_seconds,
                    AttributeNames=["All"],
                    MessageAttributeNames=["All"],
                )

                messages = response.get("Messages", [])
                if not messages:
                    continue

                logger.info(f"Received {len(messages)} message(s)")

                # Process each message
                for message in messages:
                    if not self.running:
                        logger.info("Shutdown requested, stopping message processing")
                        break

                    self.processing_message = True
                    try:
                        self._process_message(message)
                        self._delete_message(message)
                    except Exception as e:
                        logger.error(f"Failed to process message: {e}", exc_info=True)
                        # Message will be redelivered after visibility timeout
                    finally:
                        self.processing_message = False

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt, shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in worker loop: {e}", exc_info=True)

        logger.info("Worker stopped")

    def _process_message(self, message: dict):
        """
        Process a single SQS message containing S3 event(s).

        S3 notification format:
        {
          "Records": [{
            "eventName": "ObjectCreated:Put",
            "s3": {
              "bucket": {"name": "rem"},
              "object": {"key": "uploads/file.md", "size": 12345}
            }
          }]
        }
        """
        body = json.loads(message["Body"])

        for record in body.get("Records", []):
            event_name = record.get("eventName", "")

            if not event_name.startswith("ObjectCreated:"):
                logger.debug(f"Skipping non-create event: {event_name}")
                continue

            bucket = record["s3"]["bucket"]["name"]
            key = record["s3"]["object"]["key"]
            size = record["s3"]["object"].get("size", 0)

            logger.info(f"Processing {event_name}: s3://{bucket}/{key} ({size} bytes)")

            try:
                # Process file using ContentService
                uri = f"s3://{bucket}/{key}"
                result = self.content_service.process_uri(uri)

                # TODO: Store in PostgreSQL with pgvector
                # TODO: Generate embeddings
                # TODO: Create graph edges
                # TODO: Update REM entities

                logger.info(
                    f"Successfully processed s3://{bucket}/{key} "
                    f"({len(result['content'])} chars, provider={result['provider']})"
                )

                # Log extraction metadata
                logger.debug(f"Metadata: {json.dumps(result['metadata'], default=str)}")

            except FileNotFoundError as e:
                logger.error(f"File not found: {e}")
                # Don't retry - file is gone
                raise
            except RuntimeError as e:
                logger.error(f"Processing error: {e}")
                # Retry on next visibility timeout
                raise
            except Exception as e:
                logger.exception(f"Unexpected error processing s3://{bucket}/{key}: {e}")
                raise

    def _delete_message(self, message: dict):
        """Delete message from queue after successful processing."""
        try:
            self.sqs_client.delete_message(
                QueueUrl=settings.sqs.queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
            logger.debug("Message deleted from queue")
        except ClientError as e:
            logger.error(f"Failed to delete message: {e}")
            # Message will be redelivered, but processing was successful


def main():
    """Entry point for containerized deployment."""
    logger.info("REM File Processor Worker")
    logger.info(f"Environment: {settings.environment}")

    processor = SQSFileProcessor()
    processor.run()


if __name__ == "__main__":
    main()
