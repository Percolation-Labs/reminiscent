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
    @click.option("--max-sessions", type=int, default=100, help="Max sessions to analyze")
    @click.option("--max-moments", type=int, default=20, help="Max moments to include")
    @click.option("--max-resources", type=int, default=20, help="Max resources to include")
    def user_model(
        user_id: str,
        max_sessions: int,
        max_moments: int,
        max_resources: int,
    ):
        """Update user model from recent activity.

        Example:
            rem dreaming user-model --user-id user-123
        """
        logger.warning("Not implemented yet")
        logger.info(f"Would update user model for user: {user_id}")
        logger.info(f"Max sessions: {max_sessions}, moments: {max_moments}, resources: {max_resources}")

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
        """
        logger.warning("Not implemented yet")
        logger.info(f"Would construct moments for user: {user_id}")
        if lookback_hours:
            logger.info(f"Lookback: {lookback_hours} hours")
        if limit:
            logger.info(f"Limit: {limit} resources")

    @dreaming.command("affinity")
    @click.option("--user-id", required=True, help="User ID to process")
    @click.option("--use-llm", is_flag=True, help="Use LLM mode (expensive)")
    @click.option("--lookback-hours", type=int, help="Hours to look back")
    @click.option("--limit", type=int, help="Max resources (REQUIRED for LLM mode)")
    def affinity(
        user_id: str,
        use_llm: bool,
        lookback_hours: Optional[int],
        limit: Optional[int],
    ):
        """Build semantic relationships between resources.

        Semantic mode (default): Fast vector similarity
        LLM mode (--use-llm): Intelligent but expensive

        Examples:
            rem dreaming affinity --user-id user-123
            rem dreaming affinity --user-id user-123 --use-llm --limit 100
        """
        if use_llm and not limit:
            logger.error("--limit is REQUIRED when using --use-llm to control costs")
            raise click.ClickException("--limit is required with --use-llm")

        mode = "LLM" if use_llm else "semantic"
        logger.warning("Not implemented yet")
        logger.info(f"Would build {mode} affinity for user: {user_id}")
        if lookback_hours:
            logger.info(f"Lookback: {lookback_hours} hours")
        if limit:
            logger.info(f"Limit: {limit} resources")

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

            # Process all active users (daily cron)
            rem dreaming full --all-users

            # Skip extractors (faster)
            rem dreaming full --user-id user-123 --skip-extractors
        """
        if not user_id and not all_users:
            logger.error("Either --user-id or --all-users is required")
            raise click.ClickException("Either --user-id or --all-users required")

        if user_id and all_users:
            logger.error("Cannot use both --user-id and --all-users")
            raise click.ClickException("Cannot use both --user-id and --all-users")

        logger.warning("Not implemented yet")
        if all_users:
            logger.info("Would process all active users")
        else:
            logger.info(f"Would process user: {user_id}")

        if use_llm_affinity:
            logger.info("Using LLM affinity mode (expensive)")
        if lookback_hours:
            logger.info(f"Lookback: {lookback_hours} hours")
        if skip_extractors:
            logger.info("Skipping custom extractors")
        else:
            logger.info("Will run custom extractors if configs exist")
