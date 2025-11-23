"""CLI commands for dreaming worker operations.

Commands:
    rem dreaming user-model   - Update user profiles
    rem dreaming moments      - Extract temporal narratives
    rem dreaming affinity     - Build resource relationships
    rem dreaming custom       - Run custom extractors
    rem dreaming full         - Run complete workflow
"""

import asyncio
from typing import Optional

import click
from loguru import logger


def register_commands(dreaming: click.Group):
    """Register dreaming commands."""

    @dreaming.command("user-model")
    @click.option("--user-id", required=True, help="User ID to process")
    @click.option("--time-window-days", type=int, default=30, help="Days to look back")
    @click.option("--max-sessions", type=int, default=100, help="Max sessions to analyze")
    @click.option("--max-moments", type=int, default=20, help="Max moments to include")
    @click.option("--max-resources", type=int, default=20, help="Max resources to include")
    def user_model(
        user_id: str,
        time_window_days: int,
        max_sessions: int,
        max_moments: int,
        max_resources: int,
    ):
        """Update user model from recent activity.

        Example:
            rem dreaming user-model --user-id user-123
            rem dreaming user-model --user-id sarah-chen
        """
        from ...workers.dreaming import DreamingWorker

        async def run():
            worker = DreamingWorker()
            try:
                logger.info(f"Updating user model for user: {user_id}")
                result = await worker.update_user_model(
                    user_id=user_id,
                    time_window_days=time_window_days,
                    max_sessions=max_sessions,
                    max_moments=max_moments,
                    max_resources=max_resources,
                )

                if result["status"] == "success":
                    logger.success(f"User model updated successfully!")
                    logger.info(f"Messages analyzed: {result.get('messages_analyzed', 0)}")
                    logger.info(f"Moments included: {result.get('moments_included', 0)}")
                    logger.info(f"Resources included: {result.get('resources_included', 0)}")
                    logger.info(f"Activity level: {result.get('activity_level', 'N/A')}")
                else:
                    logger.warning(f"Status: {result['status']}")

            finally:
                await worker.close()

        asyncio.run(run())

    @dreaming.command("moments")
    @click.option("--user-id", required=True, help="User ID to process")
    @click.option("--lookback-hours", type=int, help="Hours to look back")
    @click.option("--limit", type=int, help="Max resources to process")
    def moments(
        user_id: str,
        lookback_hours: Optional[int],
        limit: Optional[int],
    ):
        """Extract temporal narratives from resources.

        Example:
            rem dreaming moments --user-id user-123 --lookback-hours 48
            rem dreaming moments --user-id sarah-chen
        """
        from ...workers.dreaming import DreamingWorker

        async def run():
            worker = DreamingWorker()
            try:
                logger.info(f"Constructing moments for user: {user_id}")
                result = await worker.construct_moments(
                    user_id=user_id,
                    lookback_hours=lookback_hours,
                    limit=limit,
                )

                if result["status"] == "success":
                    logger.success(f"Moments constructed successfully!")
                    logger.info(f"Resources queried: {result['resources_queried']}")
                    logger.info(f"Sessions queried: {result['sessions_queried']}")
                    logger.info(f"Moments created: {result['moments_created']}")
                    logger.info(f"Graph edges added: {result['graph_edges_added']}")
                    logger.info(f"Analysis: {result.get('analysis_summary', 'N/A')[:200]}")
                else:
                    logger.warning(f"Status: {result['status']}")

            finally:
                await worker.close()

        asyncio.run(run())

    @dreaming.command("affinity")
    @click.option("--user-id", required=True, help="User ID to process")
    @click.option("--use-llm", is_flag=True, help="Use LLM mode (expensive)")
    @click.option("--lookback-hours", type=int, help="Hours to look back")
    @click.option("--limit", type=int, help="Max resources (REQUIRED for LLM mode)")
    @click.option("--similarity-threshold", type=float, default=0.7, help="Min similarity (semantic mode)")
    @click.option("--top-k", type=int, default=3, help="Max similar resources per resource")
    def affinity(
        user_id: str,
        use_llm: bool,
        lookback_hours: Optional[int],
        limit: Optional[int],
        similarity_threshold: float,
        top_k: int,
    ):
        """Build semantic relationships between resources.

        Semantic mode (default): Fast vector similarity
        LLM mode (--use-llm): Intelligent but expensive

        Examples:
            rem dreaming affinity --user-id user-123
            rem dreaming affinity --user-id user-123 --use-llm --limit 100
            rem dreaming affinity --user-id sarah-chen
        """
        from ...workers.dreaming import DreamingWorker
        from ...services.dreaming.affinity_service import AffinityMode

        if use_llm and not limit:
            logger.error("--limit is REQUIRED when using --use-llm to control costs")
            raise click.ClickException("--limit is required with --use-llm")

        async def run():
            worker = DreamingWorker()
            try:
                mode = AffinityMode.LLM if use_llm else AffinityMode.SEMANTIC
                logger.info(f"Building {mode.value} affinity for user: {user_id}")

                result = await worker.build_affinity(
                    user_id=user_id,
                    mode=mode,
                    lookback_hours=lookback_hours,
                    limit=limit,
                    similarity_threshold=similarity_threshold,
                    top_k=top_k,
                )

                if result["status"] == "success":
                    logger.success(f"Resource affinity built successfully!")
                    logger.info(f"Resources processed: {result['resources_processed']}")
                    logger.info(f"Edges created: {result['edges_created']}")
                    if mode == AffinityMode.LLM:
                        logger.info(f"LLM calls made: {result['llm_calls_made']}")
                else:
                    logger.warning(f"Status: {result['status']}")

            finally:
                await worker.close()

        asyncio.run(run())

    @dreaming.command("custom")
    @click.option("--user-id", required=True, help="User ID to process")
    @click.option("--extractor", required=True, help="Extractor schema ID (e.g., cv-parser-v1)")
    @click.option("--lookback-hours", type=int, help="Hours to look back")
    @click.option("--limit", type=int, help="Max resources/files to process")
    @click.option("--provider", help="Optional LLM provider override")
    @click.option("--model", help="Optional model override")
    def custom(
        user_id: str,
        extractor: str,
        lookback_hours: Optional[int],
        limit: Optional[int],
        provider: Optional[str],
        model: Optional[str],
    ):
        """Run custom extractor on user's resources and files.

        Loads the user's recent resources/files and runs them through
        a custom extractor agent to extract domain-specific knowledge.

        Examples:
            # Extract from CVs
            rem dreaming custom --user-id user-123 --extractor cv-parser-v1

            # Extract from contracts with lookback
            rem dreaming custom --user-id user-123 --extractor contract-analyzer-v1 \\
                --lookback-hours 168 --limit 50

            # Override provider
            rem dreaming custom --user-id user-123 --extractor cv-parser-v1 \\
                --provider anthropic --model claude-sonnet-4-5
        """
        logger.warning("Not implemented yet")
        logger.info(f"Would run extractor '{extractor}' for user: {user_id}")
        if lookback_hours:
            logger.info(f"Lookback: {lookback_hours} hours")
        if limit:
            logger.info(f"Limit: {limit} items")
        if provider:
            logger.info(f"Provider override: {provider}")
        if model:
            logger.info(f"Model override: {model}")

    @dreaming.command("full")
    @click.option("--user-id", help="User ID (or --all-users)")
    @click.option("--all-users", is_flag=True, help="Process all active users")
    @click.option("--use-llm-affinity", is_flag=True, help="Use LLM mode for affinity")
    @click.option("--lookback-hours", type=int, help="Hours to look back")
    @click.option("--skip-extractors", is_flag=True, help="Skip custom extractors")
    def full(
        user_id: Optional[str],
        all_users: bool,
        use_llm_affinity: bool,
        lookback_hours: Optional[int],
        skip_extractors: bool,
    ):
        """Run complete dreaming workflow.

        Executes all operations in sequence:
        1. Custom extractors (if configs exist)
        2. User model update
        3. Moment construction
        4. Resource affinity

        Examples:
            # Process single user
            rem dreaming full --user-id user-123

            # Process user with LLM affinity
            rem dreaming full --user-id sarah-chen --use-llm-affinity

            # Process all active users (daily cron)
            rem dreaming full --all-users

            # Skip extractors (faster)
            rem dreaming full --user-id user-123 --skip-extractors
        """
        from ...workers.dreaming import DreamingWorker

        if not user_id and not all_users:
            logger.error("Either --user-id or --all-users is required")
            raise click.ClickException("Either --user-id or --all-users required")

        if user_id and all_users:
            logger.error("Cannot use both --user-id and --all-users")
            raise click.ClickException("Cannot use both --user-id and --all-users")

        async def run():
            worker = DreamingWorker()
            try:
                if all_users:
                    logger.warning("--all-users not implemented yet")
                    logger.info("Would process all active users")
                    # TODO: Implement process_all_users() method
                else:
                    logger.info(f"Running full dreaming workflow for user: {user_id}")
                    if use_llm_affinity:
                        logger.warning("Using LLM affinity mode (expensive)")

                    result = await worker.process_full(
                        user_id=user_id,
                        use_llm_affinity=use_llm_affinity,
                        lookback_hours=lookback_hours,
                        extract_ontologies=not skip_extractors,
                    )

                    logger.success("Dreaming workflow completed!")
                    logger.info("\n=== Results Summary ===")

                    # Ontologies
                    if not skip_extractors:
                        ont = result.get("ontologies", {})
                        if ont.get("error"):
                            logger.error(f"Ontologies: {ont['error']}")
                        else:
                            logger.info(
                                f"Ontologies: {ont.get('ontologies_created', 0)} created"
                            )

                    # User model
                    user = result.get("user_model", {})
                    if user.get("error"):
                        logger.error(f"User model: {user['error']}")
                    else:
                        logger.info(
                            f"User model: {user.get('sessions_analyzed', 0)} sessions, "
                            f"{user.get('moments_included', 0)} moments, "
                            f"{user.get('current_projects', 0)} projects"
                        )

                    # Moments
                    moments = result.get("moments", {})
                    if moments.get("error"):
                        logger.error(f"Moments: {moments['error']}")
                    else:
                        logger.info(
                            f"Moments: {moments.get('moments_created', 0)} created, "
                            f"{moments.get('graph_edges_added', 0)} edges"
                        )

                    # Affinity
                    aff = result.get("affinity", {})
                    if aff.get("error"):
                        logger.error(f"Affinity: {aff['error']}")
                    else:
                        logger.info(
                            f"Affinity: {aff.get('resources_processed', 0)} resources, "
                            f"{aff.get('edges_created', 0)} edges created"
                        )

            finally:
                await worker.close()

        asyncio.run(run())
