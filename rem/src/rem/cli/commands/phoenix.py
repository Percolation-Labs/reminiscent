"""Phoenix evaluation workflow CLI commands for REM.

Two-Phase Evaluation Workflow:
===============================

Phase 1 - SME Golden Set Creation:
  rem eval dataset create <name> --from-csv golden.csv --input-keys query --output-keys expected
  # SMEs create datasets with input/reference pairs

Phase 2 - Automated Evaluation:
  rem eval run <dataset> --experiment <name>
  # Run agents + evaluators, track in Phoenix

Commands follow noun-verb pattern for consistency with Carrier:
- eval dataset list
- eval dataset create
- eval dataset add
- eval experiment run
- eval trace list
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Optional

import click
from loguru import logger


@click.group()
def eval():
    """Phoenix evaluation workflow commands."""
    pass


@eval.group()
def dataset():
    """Dataset management commands."""
    pass


@eval.group()
def experiment():
    """Experiment execution commands."""
    pass


@eval.group()
def trace():
    """Trace retrieval commands."""
    pass


# =============================================================================
# DATASET COMMANDS
# =============================================================================


@dataset.command("list")
def dataset_list():
    """List all datasets in Phoenix.

    Example:
        rem eval dataset list
    """
    from rem.services.phoenix import PhoenixClient

    try:
        client = PhoenixClient()
        datasets = client.list_datasets()

        if not datasets:
            click.echo("No datasets found in Phoenix")
            return

        click.echo(f"\nPhoenix Datasets ({len(datasets)} total):\n")
        click.echo(f"{'Name':<40} {'Examples':>10} {'Created':<12}")
        click.echo("-" * 65)

        for ds in datasets:
            name = ds.get("name", "")[:40]
            count = ds.get("example_count", 0)
            created = ds.get("created_at", "")[:10]
            click.echo(f"{name:<40} {count:>10} {created:<12}")

    except Exception as e:
        logger.error(f"Failed to list datasets: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@dataset.command("create")
@click.argument("name")
@click.option("--from-csv", type=click.Path(exists=True, path_type=Path), help="Create from CSV file")
@click.option("--input-keys", help="Comma-separated input column names")
@click.option("--output-keys", help="Comma-separated output column names (reference/ground truth)")
@click.option("--metadata-keys", help="Comma-separated metadata column names (difficulty, type, etc.)")
@click.option("--description", help="Dataset description")
def dataset_create(
    name: str,
    from_csv: Optional[Path],
    input_keys: Optional[str],
    output_keys: Optional[str],
    metadata_keys: Optional[str],
    description: Optional[str],
):
    """Create a dataset (golden set) in Phoenix.

    Two modes:
    1. From CSV: --from-csv golden.csv --input-keys query --output-keys expected
    2. Manual (empty): Will create empty dataset to populate later

    Examples:
        # From CSV (SME golden set)
        rem eval dataset create rem-lookup-golden \\
            --from-csv golden-lookup.csv \\
            --input-keys query \\
            --output-keys expected_label,expected_type \\
            --metadata-keys difficulty,query_type

        # Empty dataset (populate later)
        rem eval dataset create rem-test --description "Test dataset"
    """
    from rem.services.phoenix import PhoenixClient

    try:
        client = PhoenixClient()

        if from_csv:
            # Create from CSV
            if not input_keys or not output_keys:
                click.echo("Error: --input-keys and --output-keys required for CSV", err=True)
                raise click.Abort()

            dataset = client.create_dataset_from_csv(
                name=name,
                csv_file_path=from_csv,
                input_keys=input_keys.split(","),
                output_keys=output_keys.split(","),
                metadata_keys=metadata_keys.split(",") if metadata_keys else None,
                description=description,
            )

            click.echo(f"✓ Created dataset '{dataset.name}' from CSV with {len(dataset)} examples")

        else:
            # Create empty dataset
            dataset = client.create_dataset_from_data(
                name=name,
                inputs=[],
                outputs=[],
                description=description,
            )

            click.echo(f"✓ Created empty dataset '{dataset.name}'")
            click.echo("  Use 'rem eval dataset add' to add examples")

    except Exception as e:
        logger.error(f"Failed to create dataset: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@dataset.command("add")
@click.argument("dataset_name")
@click.option("--from-csv", type=click.Path(exists=True, path_type=Path), required=True,
              help="CSV file with examples")
@click.option("--input-keys", required=True, help="Comma-separated input column names")
@click.option("--output-keys", required=True, help="Comma-separated output column names")
@click.option("--metadata-keys", help="Comma-separated metadata column names")
def dataset_add(
    dataset_name: str,
    from_csv: Path,
    input_keys: str,
    output_keys: str,
    metadata_keys: Optional[str],
):
    """Add examples to an existing dataset.

    Example:
        rem eval dataset add rem-lookup-golden \\
            --from-csv new-examples.csv \\
            --input-keys query \\
            --output-keys expected_label,expected_type
    """
    from rem.services.phoenix import PhoenixClient
    import pandas as pd

    try:
        client = PhoenixClient()

        # Load CSV
        df = pd.read_csv(from_csv)

        # Extract data
        inputs = df[input_keys.split(",")].to_dict("records")
        outputs = df[output_keys.split(",")].to_dict("records")
        metadata = None
        if metadata_keys:
            metadata = df[metadata_keys.split(",")].to_dict("records")

        # Add to dataset
        dataset = client.add_examples_to_dataset(
            dataset=dataset_name,
            inputs=inputs,
            outputs=outputs,
            metadata=metadata,
        )

        click.echo(f"✓ Added {len(inputs)} examples to dataset '{dataset.name}'")
        click.echo(f"  Total examples: {len(dataset)}")

    except Exception as e:
        logger.error(f"Failed to add examples: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# EXPERIMENT COMMANDS
# =============================================================================


@experiment.command("run")
@click.argument("dataset_name")
@click.option("--experiment", "-e", "experiment_name", help="Experiment name")
@click.option("--agent", "-a", help="Agent to run (e.g., ask_rem)")
@click.option("--evaluator", help="Evaluator schema name (e.g., rem-lookup-correctness)")
@click.option("--model", "-m", help="Model to use for agent/evaluator")
@click.option("--description", "-d", help="Experiment description")
@click.option("--dry-run", is_flag=True, help="Test on small subset without saving")
def experiment_run(
    dataset_name: str,
    experiment_name: Optional[str],
    agent: Optional[str],
    evaluator: Optional[str],
    model: Optional[str],
    description: Optional[str],
    dry_run: bool,
):
    """Run an evaluation experiment.

    Three modes:
    1. Agent only: --agent ask_rem
    2. Evaluator only: --evaluator rem-lookup-correctness
    3. Both: --agent ask_rem --evaluator rem-lookup-correctness

    Examples:
        # Phase 2a: Run agent on golden set
        rem eval experiment run rem-lookup-golden \\
            --experiment rem-v1-baseline \\
            --agent ask_rem \\
            --model claude-sonnet-4-5

        # Phase 2b: Run evaluator on agent results
        rem eval experiment run rem-v1-results \\
            --experiment rem-v1-evaluation \\
            --evaluator rem-lookup-correctness

        # Combined: Agent + Evaluator in one pass
        rem eval experiment run rem-lookup-golden \\
            --experiment rem-v1-full \\
            --agent ask_rem \\
            --evaluator rem-lookup-correctness
    """
    from rem.services.phoenix import PhoenixClient
    from rem.agentic.providers.phoenix import create_evaluator_from_schema

    try:
        client = PhoenixClient()

        # Create task function if agent specified
        task_fn = None
        if agent:
            # Import agent function
            if agent == "ask_rem":
                from rem.mcp.tools.rem import ask_rem

                def task(example: dict[str, Any]) -> dict[str, Any]:
                    """Run ask_rem agent on example."""
                    input_data = example.get("input", {})
                    query = input_data.get("query", "")

                    # Run async agent in sync wrapper
                    result = asyncio.run(ask_rem(query=query))
                    return result

                task_fn = task
            else:
                click.echo(f"Error: Unknown agent '{agent}'", err=True)
                raise click.Abort()

        # Create evaluators if specified
        evaluators = []
        if evaluator:
            click.echo(f"Loading evaluator: {evaluator}")
            evaluator_fn = create_evaluator_from_schema(
                evaluator_schema_path=evaluator,
                model_name=model,
            )
            evaluators.append(evaluator_fn)

        # Validate inputs
        if not task_fn and not evaluators:
            click.echo("Error: Must specify --agent or --evaluator (or both)", err=True)
            raise click.Abort()

        # Run experiment
        click.echo(f"\n{'Dry Run' if dry_run else 'Running Experiment'}:")
        click.echo(f"  Dataset: {dataset_name}")
        if agent:
            click.echo(f"  Agent: {agent}")
        if evaluator:
            click.echo(f"  Evaluator: {evaluator}")
        if experiment_name:
            click.echo(f"  Name: {experiment_name}")
        click.echo()

        if not dry_run:
            experiment = client.run_experiment(
                dataset=dataset_name,
                task=task_fn,
                evaluators=evaluators if evaluators else None,
                experiment_name=experiment_name,
                experiment_description=description,
            )

            click.echo(f"\n✓ Experiment complete")
            if hasattr(experiment, "url"):
                click.echo(f"  View results: {experiment.url}")
        else:
            click.echo("✓ Dry run complete (no data saved)")

    except Exception as e:
        logger.error(f"Failed to run experiment: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# TRACE COMMANDS
# =============================================================================


@trace.command("list")
@click.option("--project", "-p", help="Filter by project name")
@click.option("--days", "-d", default=7, help="Number of days to look back")
@click.option("--limit", "-l", default=20, help="Maximum traces to return")
def trace_list(
    project: Optional[str],
    days: int,
    limit: int,
):
    """List recent traces from Phoenix.

    Example:
        rem eval trace list --project rem-agents --days 7 --limit 50
    """
    from rem.services.phoenix import PhoenixClient

    try:
        client = PhoenixClient()

        start_time = datetime.now() - timedelta(days=days)

        traces_df = client.get_traces(
            project_name=project,
            start_time=start_time,
            limit=limit,
        )

        if len(traces_df) == 0:
            click.echo("No traces found")
            return

        click.echo(f"\nRecent Traces ({len(traces_df)} results):\n")
        click.echo(f"{'Span ID':<15} {'Name':<30} {'Start Time':<20}")
        click.echo("-" * 70)

        for _, row in traces_df.head(limit).iterrows():
            span_id = str(row.get("context.span_id", ""))[:12]
            name = str(row.get("name", ""))[:30]
            start = str(row.get("start_time", ""))[:19]
            click.echo(f"{span_id:<15} {name:<30} {start:<20}")

    except Exception as e:
        logger.error(f"Failed to list traces: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# REGISTER COMMAND
# =============================================================================


def register_command(cli_group):
    """Register Phoenix evaluation commands with CLI.

    Args:
        cli_group: Click group to register commands to
    """
    cli_group.add_command(eval)
