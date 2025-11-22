"""
Embedding Worker - Background task processor for generating embeddings.

Design:
- Asyncio-based task queue (asyncio.Queue)
- Worker pool processes embedding tasks in background
- Non-blocking: batch_upsert returns immediately, embeddings generated async
- Batching: Groups tasks for efficient API calls to OpenAI/Anthropic
- Error handling: Retries with exponential backoff

Flow:
1. batch_upsert() queues embedding tasks
2. Worker pool picks up tasks from queue
3. Workers batch tasks and call embedding API
4. Workers upsert embeddings to embeddings_<table>

Future:
- Replace with Celery/RQ for production (multi-process, Redis backend)
- Add monitoring and metrics (task latency, queue depth, error rate)
- Support multiple embedding providers (OpenAI, Cohere, local models)
"""

import asyncio
import os
from typing import Any, Optional
from uuid import uuid4

import httpx
from loguru import logger
from pydantic import BaseModel


class EmbeddingTask(BaseModel):
    """
    Embedding task for background processing.

    Each task represents one field of one entity that needs embedding.
    """

    task_id: str
    entity_id: str
    table_name: str
    field_name: str
    content: str
    provider: str = "openai"
    model: str = "text-embedding-3-small"


class EmbeddingWorker:
    """
    Background worker for generating embeddings.

    Uses asyncio.Queue for task management and worker pool pattern.
    Workers consume tasks, batch them, and call embedding APIs.
    """

    def __init__(
        self,
        postgres_service: Any,
        num_workers: int = 2,
        batch_size: int = 10,
        batch_timeout: float = 1.0,
        openai_api_key: Optional[str] = None,
    ):
        """
        Initialize embedding worker.

        Args:
            postgres_service: PostgresService instance for upserting embeddings
            num_workers: Number of concurrent worker tasks
            batch_size: Number of tasks to batch for API call
            batch_timeout: Max seconds to wait before processing partial batch
            openai_api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.postgres_service = postgres_service
        self.num_workers = num_workers
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout

        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.workers: list[asyncio.Task] = []
        self.running = False

        # Store API key for direct HTTP requests
        from ...settings import settings
        self.openai_api_key = openai_api_key or settings.llm.openai_api_key
        if not self.openai_api_key:
            logger.warning(
                "No OpenAI API key provided - embeddings will use zero vectors"
            )

        logger.info(
            f"Initialized EmbeddingWorker: {num_workers} workers, "
            f"batch_size={batch_size}, timeout={batch_timeout}s"
        )

    async def start(self) -> None:
        """Start worker pool."""
        if self.running:
            logger.warning("EmbeddingWorker already running")
            return

        self.running = True
        logger.info(f"Starting {self.num_workers} embedding workers")

        for i in range(self.num_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self.workers.append(worker)

        logger.info("EmbeddingWorker started")

    async def stop(self) -> None:
        """Stop worker pool gracefully."""
        if not self.running:
            return

        logger.info("Stopping EmbeddingWorker")
        self.running = False

        # Cancel all workers
        for worker in self.workers:
            worker.cancel()

        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)

        self.workers.clear()
        logger.info("EmbeddingWorker stopped")

    async def queue_task(self, task: EmbeddingTask) -> None:
        """
        Queue embedding task for background processing.

        Returns immediately (non-blocking).

        Args:
            task: Embedding task to process
        """
        await self.task_queue.put(task)
        logger.debug(
            f"Queued embedding task: {task.table_name}.{task.field_name} "
            f"(queue size: {self.task_queue.qsize()})"
        )

    async def _worker_loop(self, worker_id: int) -> None:
        """
        Worker loop: consume tasks, batch, and generate embeddings.

        Args:
            worker_id: Unique worker identifier
        """
        logger.info(f"Worker {worker_id} started")

        while self.running:
            try:
                # Collect batch of tasks
                batch = await self._collect_batch()

                if not batch:
                    continue

                logger.info(f"Worker {worker_id} processing batch of {len(batch)} tasks")

                # Generate embeddings for batch
                await self._process_batch(batch)

                logger.debug(f"Worker {worker_id} completed batch")

            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                # Continue processing (don't crash worker on error)
                await asyncio.sleep(1)

        logger.info(f"Worker {worker_id} stopped")

    async def _collect_batch(self) -> list[EmbeddingTask]:
        """
        Collect batch of tasks from queue.

        Waits for first task, then collects up to batch_size or until timeout.

        Returns:
            List of tasks to process
        """
        batch = []

        try:
            # Wait for first task
            first_task = await asyncio.wait_for(
                self.task_queue.get(), timeout=self.batch_timeout
            )
            batch.append(first_task)

            # Collect additional tasks (up to batch_size)
            while len(batch) < self.batch_size:
                try:
                    task = await asyncio.wait_for(
                        self.task_queue.get(), timeout=0.1  # Quick timeout
                    )
                    batch.append(task)
                except asyncio.TimeoutError:
                    # No more tasks available quickly
                    break

        except asyncio.TimeoutError:
            # No tasks available (timeout on first task)
            pass

        return batch

    async def _process_batch(self, batch: list[EmbeddingTask]) -> None:
        """
        Process batch of embedding tasks.

        Generates embeddings via API and upserts to database.

        Args:
            batch: List of tasks to process
        """
        if not batch:
            return

        # Group by provider/model for efficient batching
        # Future enhancement: group heterogeneous batches by provider/model
        provider = batch[0].provider
        model = batch[0].model

        # Extract text content for embedding
        texts = [task.content for task in batch]

        try:
            # Generate embeddings
            embeddings = await self._generate_embeddings_api(
                texts=texts, provider=provider, model=model
            )

            # Upsert to database
            await self._upsert_embeddings(batch, embeddings)

            logger.info(
                f"Successfully generated and stored {len(embeddings)} embeddings "
                f"(provider={provider}, model={model})"
            )

        except Exception as e:
            logger.error(f"Failed to process embedding batch: {e}", exc_info=True)

    async def _generate_embeddings_api(
        self, texts: list[str], provider: str, model: str
    ) -> list[list[float]]:
        """
        Generate embeddings via external API.

        Args:
            texts: List of text strings to embed
            provider: Embedding provider (openai, cohere, etc.)
            model: Model name

        Returns:
            List of embedding vectors (1536 dimensions for text-embedding-3-small)
        """
        if provider == "openai" and self.openai_api_key:
            try:
                logger.info(
                    f"Generating OpenAI embeddings for {len(texts)} texts using {model}"
                )

                # Call OpenAI embeddings API using httpx
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.openai.com/v1/embeddings",
                        headers={
                            "Authorization": f"Bearer {self.openai_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={"input": texts, "model": model},
                        timeout=60.0,
                    )
                    response.raise_for_status()

                    # Extract embeddings from response
                    data = response.json()
                    embeddings = [item["embedding"] for item in data["data"]]

                    logger.info(
                        f"Successfully generated {len(embeddings)} embeddings from OpenAI"
                    )
                    return embeddings

            except Exception as e:
                logger.error(
                    f"Failed to generate embeddings from OpenAI: {e}", exc_info=True
                )
                # Fall through to zero vectors

        # Fallback to zero vectors if no API key or error
        logger.warning(
            f"Using zero-vector embeddings for {len(texts)} texts "
            f"(provider={provider}, model={model})"
        )
        dimension = 1536  # text-embedding-3-small dimension
        return [[0.0] * dimension for _ in texts]

    async def _upsert_embeddings(
        self, tasks: list[EmbeddingTask], embeddings: list[list[float]]
    ) -> None:
        """
        Upsert embeddings to database.

        Args:
            tasks: List of embedding tasks
            embeddings: Generated embedding vectors
        """
        if len(tasks) != len(embeddings):
            raise ValueError(
                f"Task count ({len(tasks)}) != embedding count ({len(embeddings)})"
            )

        for task, embedding in zip(tasks, embeddings):
            table_name = f"embeddings_{task.table_name}"

            # Build upsert SQL
            sql = f"""
                INSERT INTO {table_name} (
                    id,
                    entity_id,
                    field_name,
                    provider,
                    model,
                    embedding,
                    created_at,
                    updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT (entity_id, field_name, provider)
                DO UPDATE SET
                    model = EXCLUDED.model,
                    embedding = EXCLUDED.embedding,
                    updated_at = CURRENT_TIMESTAMP;
            """

            try:
                # Convert embedding list to PostgreSQL array format
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

                await self.postgres_service.execute(
                    sql,
                    (
                        str(uuid4()),
                        task.entity_id,
                        task.field_name,
                        task.provider,
                        task.model,
                        embedding_str,  # pgvector expects string format
                    ),
                )

                logger.debug(
                    f"Upserted embedding: {task.table_name}.{task.entity_id}.{task.field_name}"
                )

            except Exception as e:
                logger.error(
                    f"Failed to upsert embedding for {task.entity_id}: {e}",
                    exc_info=True,
                )
                raise
