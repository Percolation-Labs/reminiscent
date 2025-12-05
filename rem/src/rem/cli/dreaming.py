"""
REM Dreaming CLI - Memory indexing and insight extraction.

Command-line interface for running dreaming workers to build the
REM knowledge graph through user model updates, moment construction,
and resource affinity operations.

Commands:
- user-model: Update user profiles from activity
- moments: Extract temporal narratives from resources
- affinity: Build semantic relationships between resources
- custom: Run custom extractors on user's resources/sessions
- full: Run complete dreaming workflow (all operations)

Usage Examples:
```bash
# Update user model for specific user
rem-dreaming user-model --user-id=user-123

# Extract moments with custom lookback
rem-dreaming moments --user-id=user-123 --lookback-hours=48

# Build resource affinity (semantic mode, fast)
rem-dreaming affinity --user-id=user-123

# Build resource affinity (LLM mode, intelligent but expensive)
rem-dreaming affinity --user-id=user-123 --use-llm --limit=100

# Run custom extractor on user's data
rem-dreaming custom --user-id=user-123 --extractor cv-parser-v1
rem-dreaming custom --user-id=user-123 --extractor contract-analyzer-v1 --lookback-hours=168

# Run full workflow for user
rem-dreaming full --user-id=user-123

# Process all active users (daily cron)
rem-dreaming full --all-users

# Process with custom REM API endpoint
rem-dreaming full --user-id=user-123 --rem-api-url=http://localhost:8000
```

Environment Variables:
- REM_API_URL: REM API endpoint (default: http://rem-api:8000)
- REM_EMBEDDING_PROVIDER: Embedding provider (default: text-embedding-3-small)
- REM_DEFAULT_MODEL: LLM model (default: gpt-4.1)
- REM_LOOKBACK_HOURS: Default lookback window (default: 24)
- OPENAI_API_KEY: OpenAI API key

Exit Codes:
- 0: Success
- 1: Validation error (missing required args)
- 2: Execution error (worker failed)
"""

import asyncio
import os
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from rem.workers.dreaming import (
    AffinityMode,
    DreamingWorker,
    TaskType,
)

app = typer.Typer(
    name="rem-dreaming",
    help="REM dreaming worker for memory indexing",
    add_completion=False,
)
console = Console()


def get_worker() -> DreamingWorker:
    """Create dreaming worker from environment."""
    return DreamingWorker(
        rem_api_url=os.getenv("REM_API_URL", "http://rem-api:8000"),
        embedding_provider=os.getenv(
            "REM_EMBEDDING_PROVIDER", "text-embedding-3-small"
        ),
        default_model=os.getenv("REM_DEFAULT_MODEL", "gpt-4.1"),
        lookback_hours=int(os.getenv("REM_LOOKBACK_HOURS", "24")),
    )


@app.command()
def user_model(
    user_id: str = typer.Option(..., help="User ID to process"),
    max_sessions: int = typer.Option(100, help="Max sessions to analyze"),
    max_moments: int = typer.Option(20, help="Max moments to include"),
    max_resources: int = typer.Option(20, help="Max resources to include"),
):
    """
    Update user model from recent activity.

    Reads recent sessions, moments, and resources to generate
    a comprehensive user profile summary using LLM analysis.
    """

    async def run():
        worker = get_worker()
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"Updating user model for {user_id}...", total=None
                )

                result = await worker.update_user_model(
                    user_id=user_id,
                    max_sessions=max_sessions,
                    max_moments=max_moments,
                    max_resources=max_resources,
                )

                progress.update(task, completed=True)
                console.print(f"[green]✓[/green] User model updated")
                console.print(result)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed: {e}", style="red")
            sys.exit(2)
        finally:
            await worker.close()

    asyncio.run(run())


@app.command()
def moments(
    user_id: str = typer.Option(..., help="User ID to process"),
    lookback_hours: Optional[int] = typer.Option(
        None, help="Hours to look back (default: from env)"
    ),
    limit: Optional[int] = typer.Option(None, help="Max resources to process"),
):
    """
    Extract moments from resources.

    Analyzes recent resources to identify temporal narratives
    (meetings, coding sessions, conversations) and creates
    Moment entities with temporal boundaries and metadata.
    """

    async def run():
        worker = get_worker()
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"Constructing moments for {user_id}...", total=None
                )

                result = await worker.construct_moments(
                    user_id=user_id,
                    lookback_hours=lookback_hours,
                    limit=limit,
                )

                progress.update(task, completed=True)
                console.print(f"[green]✓[/green] Moments constructed")
                console.print(result)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed: {e}", style="red")
            sys.exit(2)
        finally:
            await worker.close()

    asyncio.run(run())


@app.command()
def affinity(
    user_id: str = typer.Option(..., help="User ID to process"),
    use_llm: bool = typer.Option(
        False, "--use-llm", help="Use LLM mode (expensive, use --limit)"
    ),
    lookback_hours: Optional[int] = typer.Option(
        None, help="Hours to look back (default: from env)"
    ),
    limit: Optional[int] = typer.Option(
        None, help="Max resources to process (REQUIRED for LLM mode)"
    ),
):
    """
    Build resource affinity graph.

    Creates semantic relationships between resources using either
    vector similarity (fast, default) or LLM analysis (intelligent but expensive).

    Semantic Mode (default):
    - Fast vector similarity search
    - No LLM calls, just embedding cosine similarity
    - Good for frequent updates

    LLM Mode (--use-llm):
    - Intelligent relationship assessment
    - Expensive: ALWAYS use --limit to control costs
    - Good for deep analysis (weekly or monthly)

    Example:
        # Semantic mode (fast, cheap)
        rem-dreaming affinity --user-id=user-123

        # LLM mode (intelligent, expensive)
        rem-dreaming affinity --user-id=user-123 --use-llm --limit=100
    """
    if use_llm and not limit:
        console.print(
            "[red]Error:[/red] --limit is REQUIRED when using --use-llm to control costs",
            style="red",
        )
        sys.exit(1)

    async def run():
        worker = get_worker()
        try:
            mode = AffinityMode.LLM if use_llm else AffinityMode.SEMANTIC
            mode_str = "LLM" if use_llm else "semantic"

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"Building {mode_str} affinity for {user_id}...", total=None
                )

                result = await worker.build_affinity(
                    user_id=user_id,
                    mode=mode,
                    lookback_hours=lookback_hours,
                    limit=limit,
                )

                progress.update(task, completed=True)
                console.print(f"[green]✓[/green] Resource affinity built ({mode_str} mode)")
                console.print(result)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed: {e}", style="red")
            sys.exit(2)
        finally:
            await worker.close()

    asyncio.run(run())


@app.command()
def full(
    user_id: Optional[str] = typer.Option(None, help="User ID (or --all-users)"),
    all_users: bool = typer.Option(
        False, "--all-users", help="Process all active users"
    ),
    use_llm_affinity: bool = typer.Option(
        False, "--use-llm-affinity", help="Use LLM mode for affinity (expensive)"
    ),
    lookback_hours: Optional[int] = typer.Option(
        None, help="Hours to look back (default: from env)"
    ),
):
    """
    Run complete dreaming workflow.

    Executes all dreaming operations in sequence:
    1. Update user model
    2. Construct moments
    3. Build resource affinity

    Recommended for daily cron execution.

    Examples:
        # Process single user
        rem-dreaming full --user-id=user-123

        # Process all active users (daily cron)
        rem-dreaming full --all-users

        # Use LLM affinity mode (expensive)
        rem-dreaming full --user-id=user-123 --use-llm-affinity
    """
    if not user_id and not all_users:
        console.print(
            "[red]Error:[/red] Either --user-id or --all-users is required",
            style="red",
        )
        sys.exit(1)

    if user_id and all_users:
        console.print(
            "[red]Error:[/red] Cannot use both --user-id and --all-users",
            style="red",
        )
        sys.exit(1)

    async def run():
        worker = get_worker()
        try:
            if all_users:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task = progress.add_task("Processing all users...", total=None)

                    results = await worker.process_all_users(
                        task_type=TaskType.FULL,
                        use_llm_affinity=use_llm_affinity,
                        lookback_hours=lookback_hours,
                    )

                    progress.update(task, completed=True)
                    console.print(
                        f"[green]✓[/green] Processed {len(results)} users"
                    )
                    for result in results:
                        console.print(result)
            else:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=console,
                ) as progress:
                    task = progress.add_task(
                        f"Running full workflow for {user_id}...", total=None
                    )

                    result = await worker.process_full(
                        user_id=user_id,
                        use_llm_affinity=use_llm_affinity,
                        lookback_hours=lookback_hours,
                    )

                    progress.update(task, completed=True)
                    console.print(f"[green]✓[/green] Full workflow completed")
                    console.print(result)
        except Exception as e:
            console.print(f"[red]✗[/red] Failed: {e}", style="red")
            sys.exit(2)
        finally:
            await worker.close()

    asyncio.run(run())


def main():
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
