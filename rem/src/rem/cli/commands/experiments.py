"""
Experiment management CLI commands.

Experiments use ExperimentConfig (rem/models/core/experiment.py) for configuration
and support Git+S3 hybrid storage. Includes dataset, prompt, and trace management.

Directory Structure:
    experiments/{experiment-name}/
    ├── experiment.yaml          # ExperimentConfig (metadata, agent ref, evaluator ref)
    ├── README.md                # Auto-generated documentation
    ├── ground-truth/            # Evaluation datasets (Q&A pairs)
    │   ├── dataset.csv          # Input/output pairs for evaluation
    │   └── dataset.yaml         # Alternative YAML format
    ├── seed-data/              # Data to seed REM before running experiments
    │   └── data.yaml           # Users, resources, moments in REM format
    └── results/                # Experiment results and metrics
        └── {run-timestamp}/    # Each run gets its own timestamped folder
            ├── metrics.json    # Summary metrics
            └── run_info.json   # Run metadata (eval framework URLs, etc)

Environment Variables:
    EXPERIMENTS_HOME: Override default experiment directory (default: "experiments")

Commands:
    # Experiment lifecycle
    rem experiments create <name> --agent <agent> --evaluator <evaluator>
    rem experiments list
    rem experiments show <name>
    rem experiments run <name> [--version <tag>]

    # Dataset management
    rem experiments dataset list
    rem experiments dataset create <name> --from-csv data.csv
    rem experiments dataset add <name> --from-csv data.csv

    # Prompt management
    rem experiments prompt list
    rem experiments prompt create <name> --system-prompt "..."

    # Trace retrieval
    rem experiments trace list --project <name>
"""

import asyncio
from pathlib import Path
from typing import Any, Optional, cast

import click
from loguru import logger


@click.group()
def experiments():
    """Experiment configuration and execution commands."""
    pass


# =============================================================================
# CREATE COMMAND
# =============================================================================


@experiments.command("create")
@click.argument("name")
@click.option("--agent", "-a", required=True, help="Agent schema name (e.g., 'cv-parser')")
@click.option("--task", "-t", default="general", help="Task name for organizing experiments (e.g., 'risk-assessment')")
@click.option("--evaluator", "-e", default="default", help="Evaluator schema name (default: 'default')")
@click.option("--description", "-d", help="Experiment description")
@click.option("--dataset-location", type=click.Choice(["git", "s3", "hybrid"]), default="git",
              help="Where to store datasets")
@click.option("--results-location", type=click.Choice(["git", "s3", "hybrid"]), default="git",
              help="Where to store results")
@click.option("--tags", help="Comma-separated tags (e.g., 'production,cv-parser')")
@click.option("--base-path", help="Base directory for experiments (default: EXPERIMENTS_HOME or 'experiments')")
def create(
    name: str,
    agent: str,
    task: str,
    evaluator: str,
    description: Optional[str],
    dataset_location: str,
    results_location: str,
    tags: Optional[str],
    base_path: Optional[str],
):
    """Create a new experiment configuration.

    Creates directory structure and generates experiment.yaml and README.md.

    The experiment directory will contain:
    - ground-truth/: Q&A pairs for evaluation
    - seed-data/: REM data (users, resources, moments) to load before running
    - results/: Timestamped run results

    Examples:
        # Small experiment (Git-only)
        rem experiments create hello-world-validation \\
            --agent hello-world \\
            --evaluator default \\
            --description "Smoke test for hello-world agent"

        # Large experiment (Hybrid storage)
        rem experiments create cv-parser-production \\
            --agent cv-parser \\
            --evaluator default \\
            --description "Production CV parser evaluation" \\
            --dataset-location s3 \\
            --results-location hybrid \\
            --tags "production,cv-parser,weekly"

        # Custom location
        EXPERIMENTS_HOME=/path/to/experiments rem experiments create my-test --agent my-agent
    """
    from rem.models.core.experiment import (
        ExperimentConfig,
        DatasetLocation,
        DatasetReference,
        SchemaReference,
        ResultsConfig,
        ExperimentStatus,
    )
    import os

    try:
        # Resolve base path: CLI arg > EXPERIMENTS_HOME env var > default "experiments"
        if base_path is None:
            base_path = os.getenv("EXPERIMENTS_HOME", "experiments")
        # Build dataset reference (format auto-detected from file extension)
        if dataset_location == "git":
            dataset_ref = DatasetReference(
                location=DatasetLocation.GIT,
                path="ground-truth/dataset.csv",
                description="Ground truth Q&A dataset for evaluation"
            )
        else:  # s3 or hybrid
            dataset_ref = DatasetReference(
                location=DatasetLocation(dataset_location),
                path=f"s3://rem-experiments/{name}/datasets/ground_truth.parquet",
                schema_path="datasets/schema.yaml" if dataset_location == "hybrid" else None,
                description="Ground truth dataset for evaluation"
            )

        # Build results config
        if results_location == "git":
            results_config = ResultsConfig(
                location=DatasetLocation.GIT,
                base_path="results/",
                save_traces=False,
                save_metrics_summary=True
            )
        elif results_location == "s3":
            results_config = ResultsConfig(
                location=DatasetLocation.S3,
                base_path=f"s3://rem-experiments/{name}/results/",
                save_traces=True,
                save_metrics_summary=False
            )
        else:  # hybrid
            results_config = ResultsConfig(
                location=DatasetLocation.HYBRID,
                base_path=f"s3://rem-experiments/{name}/results/",
                save_traces=True,
                save_metrics_summary=True,
                metrics_file="metrics.json"
            )

        # Parse tags
        tag_list = [t.strip() for t in tags.split(",")] if tags else []

        # Create experiment config
        config = ExperimentConfig(
            name=name,
            task=task,
            description=description or f"Evaluation experiment for {agent} agent ({task} task)",
            agent_schema_ref=SchemaReference(
                name=agent,
                version=None,  # Use latest by default
                type="agent"
            ),
            evaluator_schema_ref=SchemaReference(
                name=evaluator,
                type="evaluator"
            ),
            datasets={"ground_truth": dataset_ref},
            results=results_config,
            status=ExperimentStatus.DRAFT,
            tags=tag_list
        )

        # Save configuration
        config_path = config.save(base_path)
        readme_path = config.save_readme(base_path)

        # Create new directory structure
        exp_dir = config.get_experiment_dir(base_path)

        # Create ground-truth directory
        ground_truth_dir = exp_dir / "ground-truth"
        ground_truth_dir.mkdir(parents=True, exist_ok=True)

        # Create seed-data directory
        seed_data_dir = exp_dir / "seed-data"
        seed_data_dir.mkdir(parents=True, exist_ok=True)

        # Create results directory if Git-based
        if results_location == "git":
            results_dir = exp_dir / "results"
            results_dir.mkdir(parents=True, exist_ok=True)

        # Create placeholder files with documentation
        ground_truth_readme = ground_truth_dir / "README.md"
        ground_truth_readme.write_text("""# Ground Truth Dataset

This directory contains Q&A pairs for evaluating the agent.

## Format

**CSV format** (`dataset.csv`):
```csv
input,expected_output,metadata
"What is the capital of France?","Paris","{\"difficulty\": \"easy\"}"
```

**YAML format** (`dataset.yaml`):
```yaml
- input: "What is the capital of France?"
  expected_output: "Paris"
  metadata:
    difficulty: easy
```

## Generating Ground Truth

### Using AI Assistants

AI coding assistants (like Claude, GPT-4, etc.) can help generate comprehensive ground-truth datasets:

1. **Generate from existing examples**: Show the assistant examples from your domain and ask it to create similar Q&A pairs
2. **Create challenging questions**: Ask the assistant to act as a judge and generate HARD questions that test edge cases
3. **Vary difficulty levels**: Request a mix of easy, medium, and hard questions with appropriate metadata tags

Example prompt:
```
Based on these example documents about [your domain], generate 20 Q&A pairs
for evaluating an agent. Include:
- 5 easy factual questions
- 10 medium questions requiring reasoning
- 5 hard questions with edge cases
Format as CSV with difficulty and category metadata.
```

### Ground Truth as Judge

**Important**: Keep ground-truth data **separate** from the agent being tested:
- Ground truth should be hidden from the agent during evaluation
- The agent should only see the `input` field
- The evaluator compares agent output against `expected_output`
- This ensures unbiased evaluation

### Quality Guidelines

1. **Diverse Coverage**: Include various question types and difficulty levels
2. **Domain-Specific**: Use terminology and scenarios from your actual use case
3. **Metadata Tags**: Add difficulty, category, priority for analysis
4. **SME Review**: Have domain experts validate expected outputs

## Usage

These datasets can be:
- Loaded into evaluation frameworks (Arize Phoenix, etc.)
- Used for regression testing
- Converted to different formats as needed

The experiment runner will automatically use this data for evaluation.
""")

        seed_data_readme = seed_data_dir / "README.md"
        seed_data_readme.write_text("""# Seed Data

This directory contains REM data to load before running the experiment.

## Format

Use standard REM YAML format:

```yaml
users:
  - id: test-user-001
    user_id: experiment-test
    email: test@example.com

resources:
  - id: resource-001
    user_id: experiment-test
    label: example-document
    content: "Document content here..."

moments:
  - id: moment-001
    user_id: experiment-test
    label: example-meeting
    starts_timestamp: "2024-01-15T14:00:00"
```

## Generating Seed Data

### Using AI Assistants

AI coding assistants can help generate realistic seed data for your experiments:

1. **From existing datasets**: Reference examples from the `datasets/` directory
2. **Domain-specific scenarios**: Describe your use case and ask for appropriate test data
3. **Anonymized versions**: Ask to create fictional data based on real patterns

Example prompt:
```
Based on the recruitment dataset examples in datasets/domains/recruitment/,
generate seed data for testing a CV parser agent. Include:
- 3 test users
- 5 CV documents (resources) with varied experience levels
- 2 interview moment entries
Use fictional names and anonymize all content.
```

### Best Practices

1. **Minimal**: Only include data necessary for the ground-truth questions to be answerable
2. **Anonymized**: Always use fictional names, companies, and content
3. **Relevant**: Seed data should provide context for evaluation questions
4. **Versioned**: Track changes to seed data in Git for reproducibility

## Usage

Load this data before running experiments:
```bash
rem db load --file seed-data/data.yaml --user-id experiment-test
```

This ensures your agent has the necessary context for evaluation.
""")

        click.echo(f"\n✓ Created experiment: {name}")
        click.echo(f"  Configuration: {config_path}")
        click.echo(f"  Documentation: {readme_path}")
        click.echo(f"  Ground Truth: {ground_truth_dir}")
        click.echo(f"  Seed Data: {seed_data_dir}")
        if results_location == "git":
            click.echo(f"  Results: {results_dir}")
        click.echo(f"\nNext steps:")
        click.echo(f"  1. Add ground truth Q&A to {ground_truth_dir}/dataset.csv")
        click.echo(f"  2. Add seed data to {seed_data_dir}/data.yaml (optional)")
        click.echo(f"  3. Review configuration: {config_path}")
        click.echo(f"  4. Run experiment: rem experiments run {name}")
        click.echo(f"  5. Commit to Git: git add {base_path}/{name}/ && git commit")

    except Exception as e:
        logger.error(f"Failed to create experiment: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# LIST COMMAND
# =============================================================================


@experiments.command("list")
@click.option("--base-path", help="Base directory for experiments (default: EXPERIMENTS_HOME or 'experiments')")
@click.option("--status", help="Filter by status (draft, ready, completed, etc.)")
@click.option("--tags", help="Filter by tags (comma-separated)")
def list_experiments(
    base_path: Optional[str],
    status: Optional[str],
    tags: Optional[str],
):
    """List all experiments.

    Examples:
        rem experiments list
        rem experiments list --status ready
        rem experiments list --tags production,cv-parser
    """
    from rem.models.core.experiment import ExperimentConfig, ExperimentStatus
    import os

    try:
        # Resolve base path
        if base_path is None:
            base_path = os.getenv("EXPERIMENTS_HOME", "experiments")

        experiments_dir = Path(base_path)
        if not experiments_dir.exists():
            click.echo(f"No experiments directory found at {base_path}")
            return

        # Find all experiment.yaml files
        configs = []
        for exp_dir in experiments_dir.iterdir():
            if not exp_dir.is_dir() or exp_dir.name.startswith("."):
                continue

            config_file = exp_dir / "experiment.yaml"
            if config_file.exists():
                try:
                    config = ExperimentConfig.from_yaml(config_file)
                    configs.append(config)
                except Exception as e:
                    logger.warning(f"Failed to load {config_file}: {e}")

        # Apply filters
        if status:
            status_enum = ExperimentStatus(status)
            configs = [c for c in configs if c.status == status_enum]

        if tags:
            filter_tags = set(t.strip().lower() for t in tags.split(","))
            configs = [c for c in configs if filter_tags & set(c.tags)]

        if not configs:
            click.echo("No experiments found")
            return

        # Sort by updated_at descending
        configs.sort(key=lambda c: c.updated_at, reverse=True)

        # Display table
        click.echo(f"\nExperiments ({len(configs)} total):\n")
        click.echo(f"{'Name':<30} {'Status':<12} {'Agent':<20} {'Updated':<12}")
        click.echo("-" * 75)

        for config in configs:
            name = config.name[:30]
            status_str = config.status.value[:12]
            agent = config.agent_schema_ref.name[:20]
            updated = config.updated_at.strftime("%Y-%m-%d")
            click.echo(f"{name:<30} {status_str:<12} {agent:<20} {updated:<12}")

    except Exception as e:
        logger.error(f"Failed to list experiments: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# SHOW COMMAND
# =============================================================================


@experiments.command("show")
@click.argument("name")
@click.option("--base-path", help="Base directory for experiments (default: EXPERIMENTS_HOME or 'experiments')")
def show(name: str, base_path: Optional[str]):
    """Show experiment details.

    Examples:
        rem experiments show hello-world-validation
    """
    from rem.models.core.experiment import ExperimentConfig
    import os

    try:
        # Resolve base path
        if base_path is None:
            base_path = os.getenv("EXPERIMENTS_HOME", "experiments")

        config_path = Path(base_path) / name / "experiment.yaml"
        if not config_path.exists():
            click.echo(f"Experiment not found: {name}")
            click.echo(f"  Looked in: {config_path}")
            raise click.Abort()

        config = ExperimentConfig.from_yaml(config_path)

        click.echo(f"\nExperiment: {config.name}")
        click.echo(f"{'=' * 60}\n")
        click.echo(f"Description: {config.description}")
        click.echo(f"Status: {config.status.value}")
        if config.tags:
            click.echo(f"Tags: {', '.join(config.tags)}")

        click.echo(f"\nAgent Schema:")
        click.echo(f"  Name: {config.agent_schema_ref.name}")
        click.echo(f"  Version: {config.agent_schema_ref.version or 'latest'}")

        click.echo(f"\nEvaluator Schema:")
        click.echo(f"  Name: {config.evaluator_schema_ref.name}")

        click.echo(f"\nDatasets:")
        for ds_name, ds_ref in config.datasets.items():
            click.echo(f"  {ds_name}:")
            click.echo(f"    Location: {ds_ref.location.value}")
            click.echo(f"    Path: {ds_ref.path}")
            click.echo(f"    Format: {ds_ref.format}")

        click.echo(f"\nResults:")
        click.echo(f"  Location: {config.results.location.value}")
        click.echo(f"  Base Path: {config.results.base_path}")
        click.echo(f"  Save Traces: {config.results.save_traces}")
        click.echo(f"  Metrics File: {config.results.metrics_file}")

        click.echo(f"\nTimestamps:")
        click.echo(f"  Created: {config.created_at.isoformat()}")
        click.echo(f"  Updated: {config.updated_at.isoformat()}")
        if config.last_run_at:
            click.echo(f"  Last Run: {config.last_run_at.isoformat()}")

        if config.metadata:
            click.echo(f"\nMetadata:")
            for key, value in config.metadata.items():
                click.echo(f"  {key}: {value}")

    except Exception as e:
        logger.error(f"Failed to show experiment: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# VIBES MODE HELPER
# =============================================================================


def _run_vibes_mode(
    config: Any,
    dataset_df: Any,
    task_fn: Any,
    base_path: str,
    limit: Optional[int],
    evaluator_schema_path: Path,
) -> None:
    """Run experiment in vibes mode - execute agent and export for AI evaluation.

    Vibes mode runs the agent on each example and saves results to a JSONL file.
    The AI assistant (e.g., Claude Code) then acts as the judge using the
    evaluator schema to evaluate results.

    Args:
        config: ExperimentConfig object
        dataset_df: Polars DataFrame with ground truth examples
        task_fn: Function to run agent on each example
        base_path: Base directory for experiments
        limit: Optional limit on number of examples to process
        evaluator_schema_path: Path to the evaluator schema YAML file
    """
    from rem.utils.date_utils import format_timestamp_for_experiment, utc_now, to_iso
    import json

    # Apply limit if specified
    if limit:
        dataset_df = dataset_df.head(limit)
        click.echo(f"  (Limited to {limit} examples)")

    # Create results directory
    timestamp = format_timestamp_for_experiment()
    results_dir = Path(base_path) / config.name / "results" / timestamp
    results_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"\n⏳ Running agent on {len(dataset_df)} examples...")
    click.echo(f"   Results will be saved to: {results_dir}")
    click.echo()

    # Run agent on each example and collect results
    results = []
    records = dataset_df.to_dicts()

    for i, record in enumerate(records, 1):
        example_id = record.get("id", i)
        click.echo(f"  [{i}/{len(records)}] Processing example {example_id}...", nl=False)

        try:
            # Prepare input for agent
            input_text = record.get("text", record.get("input", record.get("query", "")))
            example_input = {"query": input_text} if isinstance(input_text, str) else input_text

            # Run agent
            output = task_fn({"input": example_input})

            result = {
                "id": example_id,
                "input": input_text,
                "ground_truth": record.get("ground_truth", record.get("expected_output", "")),
                "category": record.get("category", ""),
                "agent_output": output,
                "status": "success",
            }
            click.echo(" ✓")

        except Exception as e:
            result = {
                "id": example_id,
                "input": record.get("text", record.get("input", "")),
                "ground_truth": record.get("ground_truth", record.get("expected_output", "")),
                "category": record.get("category", ""),
                "agent_output": None,
                "status": "error",
                "error": str(e),
            }
            click.echo(f" ✗ ({e})")

        results.append(result)

    # Save results to JSONL
    results_file = results_dir / "vibes-results.jsonl"
    with open(results_file, "w") as f:
        for result in results:
            f.write(json.dumps(result) + "\n")

    # Copy evaluator schema to results dir for easy reference
    import shutil
    evaluator_copy = results_dir / "evaluator-schema.yaml"
    shutil.copy(evaluator_schema_path, evaluator_copy)

    # Save run metadata
    run_info = {
        "experiment": config.name,
        "agent": config.agent_schema_ref.name,
        "evaluator": config.evaluator_schema_ref.name,
        "mode": "vibes",
        "timestamp": timestamp,
        "total_examples": len(records),
        "successful": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "error"]),
        "completed_at": to_iso(utc_now()),
    }

    run_info_file = results_dir / "run-info.json"
    with open(run_info_file, "w") as f:
        json.dump(run_info, f, indent=2)

    # Print summary and instructions
    success_count = run_info["successful"]
    fail_count = run_info["failed"]

    click.echo(f"\n{'=' * 60}")
    click.echo(f"VIBES MODE COMPLETE")
    click.echo(f"{'=' * 60}")
    click.echo(f"\nResults: {success_count} successful, {fail_count} failed")
    click.echo(f"\nFiles saved to: {results_dir}/")
    click.echo(f"  - vibes-results.jsonl    (agent outputs)")
    click.echo(f"  - evaluator-schema.yaml  (evaluation criteria)")
    click.echo(f"  - run-info.json          (run metadata)")

    click.echo(f"\n{'=' * 60}")
    click.echo(f"NEXT STEP: Ask your AI assistant to evaluate")
    click.echo(f"{'=' * 60}")
    click.echo(f"""
Copy this prompt to Claude Code or your AI assistant:

    Please evaluate the experiment results in:
    {results_dir}/

    Read the vibes-results.jsonl file and evaluate each example
    using the evaluator schema in evaluator-schema.yaml.

    For each example, provide:
    1. extracted_classification
    2. exact_match (vs ground_truth)
    3. semantic_match
    4. reasoning_quality_score
    5. overall_score
    6. pass/fail

    Then provide summary metrics:
    - Exact match accuracy
    - Semantic match accuracy
    - Average overall score
    - Pass rate
""")


# =============================================================================
# RUN COMMAND
# =============================================================================


@experiments.command("run")
@click.argument("name")
@click.option("--base-path", help="Base directory for experiments (default: EXPERIMENTS_HOME or 'experiments')")
@click.option("--version", help="Git tag version to load (e.g., 'experiments/my-exp/v1.0.0')")
@click.option("--dry-run", is_flag=True, help="Test on small subset without saving")
@click.option("--only-vibes", is_flag=True, help="Run agent locally, export results for AI evaluation (no Phoenix)")
@click.option("--limit", "-n", type=int, help="Limit number of examples to evaluate (useful with --only-vibes)")
@click.option("--update-prompts", is_flag=True, help="Update prompts in Phoenix before running")
@click.option("--phoenix-url", help="Phoenix server URL (overrides PHOENIX_BASE_URL env var)")
@click.option("--phoenix-api-key", help="Phoenix API key (overrides PHOENIX_API_KEY env var)")
def run(
    name: str,
    base_path: Optional[str],
    version: Optional[str],
    dry_run: bool,
    only_vibes: bool,
    limit: Optional[int],
    update_prompts: bool,
    phoenix_url: Optional[str],
    phoenix_api_key: Optional[str],
):
    """Run an experiment using Phoenix provider or local vibes mode.

    Loads configuration, executes agent and evaluator, saves results.

    Vibes Mode (--only-vibes):
        Run agent locally without Phoenix infrastructure. Agent outputs are saved
        to a JSONL file along with the evaluator schema. Your AI assistant (e.g.,
        Claude Code) then acts as the judge to evaluate results.

        This enables seamless switching between:
        - Local evaluation: Quick iteration with AI-as-judge
        - Phoenix evaluation: Production metrics and dashboards

        Usage:
            rem experiments run my-experiment --only-vibes
            rem experiments run my-experiment --only-vibes --limit 5

        The command will:
        1. Run the agent on each ground-truth example
        2. Save results to results/{timestamp}/vibes-results.jsonl
        3. Print the evaluator prompt and schema
        4. Instruct you to ask your AI assistant to evaluate

        Example workflow with Claude Code:
            $ rem experiments run mental-health-classifier --only-vibes --limit 3
            # ... agent runs ...
            # Results saved to: .experiments/mental-health-classifier/results/20241203-143022/

            # Then ask Claude Code:
            "Please evaluate the experiment results in
             .experiments/mental-health-classifier/results/20241203-143022/
             using the evaluator schema provided"

    Phoenix Connection:
        Commands respect PHOENIX_BASE_URL and PHOENIX_API_KEY environment variables.
        Defaults to localhost:6006 for local development.

        Production (on cluster):
            export PHOENIX_BASE_URL=http://phoenix-svc.observability.svc.cluster.local:6006
            export PHOENIX_API_KEY=<your-key>
            kubectl exec -it deployment/rem-api -- rem experiments run my-experiment

        Development (port-forward):
            kubectl port-forward -n observability svc/phoenix-svc 6006:6006
            export PHOENIX_API_KEY=<your-key>
            rem experiments run my-experiment

        Local (local Phoenix):
            python -m phoenix.server.main serve
            rem experiments run my-experiment

    Examples:
        # Run experiment with latest schemas
        rem experiments run hello-world-validation

        # Quick local evaluation (vibes mode)
        rem experiments run hello-world-validation --only-vibes

        # Vibes mode with limited examples
        rem experiments run hello-world-validation --only-vibes --limit 5

        # Run specific version
        rem experiments run hello-world-validation \\
            --version experiments/hello-world-validation/v1.0.0

        # Dry run (test without saving)
        rem experiments run cv-parser-production --dry-run

        # Override Phoenix connection
        rem experiments run my-experiment \\
            --phoenix-url http://phoenix.example.com:6006 \\
            --phoenix-api-key <key>
    """
    from rem.models.core.experiment import ExperimentConfig, ExperimentStatus
    from rem.services.git import GitService
    from rem.services.phoenix import PhoenixClient
    from rem.agentic.providers.phoenix import create_evaluator_from_schema
    from rem.utils.date_utils import utc_now, to_iso, format_timestamp_for_experiment
    import os

    try:
        # Resolve base path
        if base_path is None:
            base_path = os.getenv("EXPERIMENTS_HOME", "experiments")

        # Load experiment configuration
        if version:
            # Load from Git at specific version
            git_svc = GitService()
            config_yaml = git_svc.fs.read(
                f"git://rem/.experiments/{name}/experiment.yaml?ref={version}"
            )
            config = ExperimentConfig(**config_yaml)
            click.echo(f"✓ Loaded experiment from Git: {version}")
        else:
            # Load from local filesystem
            config_path = Path(base_path) / name / "experiment.yaml"
            if not config_path.exists():
                click.echo(f"Experiment not found: {name}")
                click.echo(f"  Looked in: {config_path}")
                raise click.Abort()
            config = ExperimentConfig.from_yaml(config_path)
            click.echo(f"✓ Loaded experiment: {name}")

        # Display experiment info
        click.echo(f"\nExperiment: {config.name}")
        click.echo(f"  Agent: {config.agent_schema_ref.name} (version: {config.agent_schema_ref.version or 'latest'})")
        click.echo(f"  Evaluator: {config.evaluator_schema_ref.name}")
        click.echo(f"  Status: {config.status.value}")
        if dry_run:
            click.echo(f"  Mode: DRY RUN (no data will be saved)")
        click.echo()

        # Load agent schema using centralized schema loader
        agent_name = config.agent_schema_ref.name
        agent_version = config.agent_schema_ref.version

        click.echo(f"Loading agent schema: {agent_name} (version: {agent_version or 'latest'})")

        from rem.utils.schema_loader import load_agent_schema

        try:
            agent_schema = load_agent_schema(agent_name)
            click.echo(f"✓ Loaded agent schema: {agent_name}")
        except FileNotFoundError as e:
            logger.error(f"Failed to load agent schema: {e}")
            click.echo(f"Error: Could not load agent schema '{agent_name}'")
            click.echo(f"  {e}")
            raise click.Abort()

        # Create agent function from schema
        from rem.agentic.providers.pydantic_ai import create_agent
        from rem.agentic.context import AgentContext

        # Create agent context
        context = AgentContext(
            user_id="experiment-runner",
            tenant_id="experiments",
            session_id=f"experiment-{config.name}",
        )

        agent_runtime = asyncio.run(create_agent(
            context=context,
            agent_schema_override=agent_schema
        ))

        def task_fn(example: dict[str, Any]) -> dict[str, Any]:
            """Run agent on example."""
            input_data = example.get("input", {})

            # Extract query from input
            query = input_data.get("query", "")
            if not query:
                # Try other common input keys
                query = input_data.get("text", input_data.get("prompt", str(input_data)))

            # Run agent
            result = asyncio.run(agent_runtime.run(query))

            # Serialize result (critical for Pydantic models!)
            from rem.agentic.serialization import serialize_agent_result
            serialized = serialize_agent_result(result)
            # Ensure we return a dict (Phoenix expects dict output)
            if isinstance(serialized, str):
                return {"output": serialized}
            return serialized if isinstance(serialized, dict) else {"output": str(serialized)}

        # Load evaluator schema using centralized schema loader
        evaluator_name = config.evaluator_schema_ref.name
        evaluator_version = config.evaluator_schema_ref.version

        click.echo(f"Loading evaluator: {evaluator_name} for agent {agent_name}")

        # Find evaluator schema file path
        from rem.utils.schema_loader import get_evaluator_schema_path

        evaluator_schema_path = get_evaluator_schema_path(evaluator_name)
        if not evaluator_schema_path or not evaluator_schema_path.exists():
            click.echo(f"Error: Could not find evaluator schema '{evaluator_name}'")
            raise click.Abort()

        click.echo(f"✓ Found evaluator schema: {evaluator_schema_path}")

        # For Phoenix mode, also load evaluator function
        evaluator_fn = None
        if not only_vibes:
            # Try multiple evaluator path patterns (agent-specific, then generic)
            evaluator_paths_to_try = [
                f"{agent_name}/{evaluator_name}",  # e.g., hello-world/default
                f"{agent_name}-{evaluator_name}",  # e.g., hello-world-default
                evaluator_name,                     # e.g., default (generic)
            ]

            evaluator_load_error = None

            for evaluator_path in evaluator_paths_to_try:
                try:
                    evaluator_fn = create_evaluator_from_schema(
                        evaluator_schema_path=evaluator_path,
                        model_name=None,  # Use default from schema
                    )
                    click.echo(f"✓ Loaded evaluator function: {evaluator_path}")
                    break
                except FileNotFoundError as e:
                    evaluator_load_error = e
                    logger.debug(f"Evaluator not found at {evaluator_path}: {e}")
                    continue
                except Exception as e:
                    evaluator_load_error = e
                    logger.warning(f"Failed to load evaluator from {evaluator_path}: {e}")
                    continue

        if evaluator_fn is None and not only_vibes:
            click.echo(f"Error: Could not load evaluator function '{evaluator_name}'")
            click.echo(f"  Tried paths: {evaluator_paths_to_try}")
            if evaluator_load_error:
                click.echo(f"  Last error: {evaluator_load_error}")
            raise click.Abort()

        # Validate evaluator credentials before running expensive agent tasks
        if evaluator_fn is not None and not only_vibes:
            from rem.agentic.providers.phoenix import validate_evaluator_credentials

            click.echo("Validating evaluator credentials...")
            is_valid, error_msg = validate_evaluator_credentials()
            if not is_valid:
                click.echo(click.style(f"\n⚠️  Evaluator validation failed: {error_msg}", fg="yellow"))
                click.echo("\nOptions:")
                click.echo("  1. Fix the credentials issue and re-run")
                click.echo("  2. Run with --only-vibes to skip LLM evaluation")
                click.echo("  3. Use --evaluator-model to specify a different model")
                raise click.Abort()
            click.echo("✓ Evaluator credentials validated")

        # Load dataset using read_dataframe utility (auto-detects format from extension)
        from rem.utils.files import read_dataframe

        click.echo(f"Loading dataset: {list(config.datasets.keys())[0]}")
        dataset_ref = list(config.datasets.values())[0]

        try:
            if dataset_ref.location.value == "git":
                # Load from Git (local filesystem)
                dataset_path = Path(base_path) / name / dataset_ref.path
                if not dataset_path.exists():
                    click.echo(f"Error: Dataset not found: {dataset_path}")
                    raise click.Abort()

                dataset_df = read_dataframe(dataset_path)

            elif dataset_ref.location.value in ["s3", "hybrid"]:
                # Load from S3 using FS provider
                from rem.services.fs import FS

                fs = FS()
                content = fs.read(dataset_ref.path)
                # Ensure we have bytes
                if isinstance(content, str):
                    content = content.encode()
                dataset_df = read_dataframe(content, filename=dataset_ref.path)
                click.echo(f"✓ Loaded dataset from S3")

            else:
                click.echo(f"Error: Unknown dataset location: {dataset_ref.location.value}")
                raise click.Abort()

        except ValueError as e:
            # Unsupported format error from read_dataframe
            click.echo(f"Error: {e}")
            raise click.Abort()
        except Exception as e:
            logger.error(f"Failed to load dataset: {e}")
            click.echo(f"Error: Could not load dataset")
            click.echo(f"  Path: {dataset_ref.path}")
            raise click.Abort()

        click.echo(f"✓ Loaded dataset: {len(dataset_df)} examples")

        # Update prompts in Phoenix if requested
        if update_prompts:
            # TODO: Implement prompt updating
            click.echo("⚠  --update-prompts not yet implemented")

        # Vibes mode: run agent and export for AI evaluation
        if only_vibes:
            _run_vibes_mode(
                config=config,
                dataset_df=dataset_df,
                task_fn=task_fn,
                base_path=base_path,
                limit=limit,
                evaluator_schema_path=evaluator_schema_path,
            )
            return

        # Run experiment via Phoenix
        if not dry_run:
            # Create Phoenix client with optional overrides
            from rem.services.phoenix.config import PhoenixConfig
            import os

            phoenix_config = PhoenixConfig(
                base_url=phoenix_url or os.getenv("PHOENIX_BASE_URL"),
                api_key=phoenix_api_key or os.getenv("PHOENIX_API_KEY")
            )

            # Display Phoenix connection info
            phoenix_display_url = phoenix_config.base_url
            phoenix_has_key = "Yes" if phoenix_config.api_key else "No"
            click.echo(f"\nPhoenix Connection:")
            click.echo(f"  URL: {phoenix_display_url}")
            click.echo(f"  API Key: {phoenix_has_key}")
            click.echo()

            client = PhoenixClient(config=phoenix_config)

            experiment_name = f"{config.name}-{format_timestamp_for_experiment()}"

            click.echo(f"\n⏳ Running experiment: {experiment_name}")
            click.echo(f"   This may take several minutes...")

            experiment = client.run_experiment(
                dataset=dataset_df,
                task=task_fn,
                evaluators=[evaluator_fn],
                experiment_name=experiment_name,
                experiment_description=config.description,
                experiment_metadata={
                    "agent": config.agent_schema_ref.name,
                    "evaluator": config.evaluator_schema_ref.name,
                    "experiment_config": config.name,
                    **config.metadata
                },
                # Smart column detection for DataFrame -> Phoenix Dataset conversion
                input_keys=["input"] if "input" in dataset_df.columns else None,
                output_keys=["expected_output"] if "expected_output" in dataset_df.columns else None,
            )

            # Update experiment status
            config.status = ExperimentStatus.COMPLETED
            config.last_run_at = utc_now()
            if not version:  # Only save if not loading from Git
                config.save(base_path)

            click.echo(f"\n✓ Experiment complete!")
            if hasattr(experiment, "url"):
                click.echo(f"  View results: {experiment.url}")  # type: ignore[attr-defined]

            # Save results according to config.results settings
            if config.results.save_metrics_summary:
                # Get experiment data
                try:
                    exp_data = client.get_experiment(experiment.id)  # type: ignore[attr-defined]

                    # Build metrics summary
                    metrics = {
                        "experiment_id": experiment.id,  # type: ignore[attr-defined]
                        "experiment_name": experiment_name,
                        "agent": config.agent_schema_ref.name,
                        "evaluator": config.evaluator_schema_ref.name,
                        "dataset_size": len(dataset_df),
                        "completed_at": to_iso(utc_now()),
                        "phoenix_url": getattr(experiment, "url", None),
                        "task_runs": len(exp_data.get("task_runs", [])),
                    }

                    # Save metrics
                    if config.results.location.value == "git" or config.results.location.value == "hybrid":
                        # Save to Git
                        metrics_path = Path(base_path) / name / "results" / (config.results.metrics_file or "metrics.json")
                        metrics_path.parent.mkdir(parents=True, exist_ok=True)

                        import json
                        with open(metrics_path, "w") as f:
                            json.dump(metrics, f, indent=2)

                        click.echo(f"\n✓ Saved metrics summary: {metrics_path}")

                    if config.results.location.value == "s3" or config.results.location.value == "hybrid":
                        # Save to S3
                        from rem.services.fs import FS
                        fs = FS()

                        s3_metrics_path = config.results.base_path.rstrip("/") + "/" + (config.results.metrics_file or "metrics.json")

                        import json
                        fs.write(s3_metrics_path, json.dumps(metrics, indent=2))

                        click.echo(f"✓ Saved metrics summary to S3: {s3_metrics_path}")

                except Exception as e:
                    logger.warning(f"Failed to save metrics: {e}")
                    click.echo(f"⚠  Could not save metrics summary: {e}")
        else:
            click.echo("\n✓ Dry run complete (no data saved)")

    except Exception as e:
        logger.error(f"Failed to run experiment: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# DATASET COMMANDS
# =============================================================================


@experiments.group()
def dataset():
    """Dataset management commands."""
    pass


@dataset.command("list")
def dataset_list():
    """List all datasets.

    Example:
        rem experiments dataset list
    """
    from rem.services.phoenix import PhoenixClient

    try:
        client = PhoenixClient()
        datasets = client.list_datasets()

        if not datasets:
            click.echo("No datasets found")
            return

        click.echo(f"\nDatasets ({len(datasets)} total):\n")
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
    """Create a dataset (golden set).

    Two modes:
    1. From CSV: --from-csv golden.csv --input-keys query --output-keys expected
    2. Manual (empty): Will create empty dataset to populate later

    Examples:
        # From CSV (SME golden set)
        rem experiments dataset create rem-lookup-golden \\
            --from-csv golden-lookup.csv \\
            --input-keys query \\
            --output-keys expected_label,expected_type \\
            --metadata-keys difficulty,query_type

        # Empty dataset (populate later)
        rem experiments dataset create rem-test --description "Test dataset"
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
            click.echo("  Use 'rem experiments dataset add' to add examples")

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
        rem experiments dataset add rem-lookup-golden \\
            --from-csv new-examples.csv \\
            --input-keys query \\
            --output-keys expected_label,expected_type
    """
    from rem.services.phoenix import PhoenixClient
    import polars as pl

    try:
        client = PhoenixClient()

        # Load CSV with Polars
        df = pl.read_csv(from_csv)
        records = df.to_dicts()

        # Extract data
        input_cols = input_keys.split(",")
        output_cols = output_keys.split(",")
        inputs = [{k: row.get(k) for k in input_cols} for row in records]
        outputs = [{k: row.get(k) for k in output_cols} for row in records]
        metadata = None
        if metadata_keys:
            meta_cols = metadata_keys.split(",")
            metadata = [{k: row.get(k) for k in meta_cols} for row in records]

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
# PROMPT COMMANDS
# =============================================================================


@experiments.group()
def prompt():
    """Prompt management commands."""
    pass


@prompt.command("create")
@click.argument("name")
@click.option("--system-prompt", "-s", required=True, help="System prompt text")
@click.option("--description", "-d", help="Prompt description")
@click.option("--model-provider", default="OPENAI", help="Model provider (OPENAI, ANTHROPIC)")
@click.option("--model-name", "-m", help="Model name (e.g., gpt-4.1, claude-sonnet-4-5)")
@click.option("--type", "-t", "prompt_type", default="Agent", help="Prompt type (Agent or Evaluator)")
def prompt_create(
    name: str,
    system_prompt: str,
    description: Optional[str],
    model_provider: str,
    model_name: Optional[str],
    prompt_type: str,
):
    """Create a prompt.

    Examples:
        # Create agent prompt
        rem experiments prompt create hello-world \\
            --system-prompt "You are a helpful assistant." \\
            --model-name gpt-4.1

        # Create evaluator prompt
        rem experiments prompt create correctness-evaluator \\
            --system-prompt "Evaluate the correctness of responses." \\
            --type Evaluator \\
            --model-provider ANTHROPIC \\
            --model-name claude-sonnet-4-5
    """
    from rem.services.phoenix import PhoenixClient
    from rem.services.phoenix.prompt_labels import PhoenixPromptLabels
    from phoenix.client import Client
    from phoenix.client.types.prompts import PromptVersion
    from phoenix.client.__generated__ import v1

    try:
        # Set default model if not specified
        if not model_name:
            model_name = "gpt-4.1" if model_provider == "OPENAI" else "claude-sonnet-4-5-20250929"

        # Get config
        phoenix_client = PhoenixClient()
        config = phoenix_client.config

        # Create client
        client = Client(
            base_url=config.base_url,
            api_key=config.api_key
        )

        # Create prompt messages
        messages = [
            v1.PromptMessage(
                role="system",
                content=system_prompt
            )
        ]

        # Create PromptVersion
        version = PromptVersion(
            messages,
            model_name=model_name,
            description="v1.0",
            model_provider=model_provider  # type: ignore[arg-type]
        )

        # Create the prompt
        result = client.prompts.create(
            name=name,
            version=version,
            prompt_description=description or f"{prompt_type} prompt: {name}"
        )

        click.echo(f"✓ Created prompt '{name}' (ID: {result.id})")

        # Try to get the prompt ID for label assignment
        try:
            import httpx
            query = """
            query {
              prompts(first: 1, filterBy: {name: {equals: "%s"}}) {
                edges {
                  node {
                    id
                    name
                  }
                }
              }
            }
            """ % name

            response = httpx.post(
                f"{config.base_url}/graphql",
                json={"query": query},
                headers={"authorization": f"Bearer {config.api_key}"},
                timeout=10,
            )
            graphql_result = response.json()
            prompts = graphql_result.get("data", {}).get("prompts", {}).get("edges", [])

            if prompts:
                prompt_id = prompts[0]["node"]["id"]

                # Assign labels
                if not config.base_url:
                    raise ValueError("Phoenix base_url is required")
                labels_helper = PhoenixPromptLabels(
                    base_url=config.base_url, api_key=config.api_key
                )

                # Assign REM + type label
                label_names = ["REM", prompt_type]
                labels_helper.assign_prompt_labels(prompt_id, label_names)
                click.echo(f"✓ Assigned labels: {', '.join(label_names)}")
        except Exception as e:
            click.echo(f"⚠ Warning: Could not assign labels: {e}")

        click.echo(f"\nView in UI: {config.base_url}")

    except Exception as e:
        logger.error(f"Failed to create prompt: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


@prompt.command("list")
def prompt_list():
    """List all prompts.

    Example:
        rem experiments prompt list
    """
    import httpx
    from rem.services.phoenix import PhoenixClient

    try:
        phoenix_client = PhoenixClient()
        config = phoenix_client.config

        query = """
        query {
          prompts(first: 100) {
            edges {
              node {
                id
                name
                description
                createdAt
              }
            }
          }
        }
        """

        response = httpx.post(
            f"{config.base_url}/graphql",
            json={"query": query},
            headers={"authorization": f"Bearer {config.api_key}"},
            timeout=10,
        )

        result = response.json()
        prompts = result.get("data", {}).get("prompts", {}).get("edges", [])

        if not prompts:
            click.echo("No prompts found")
            return

        click.echo(f"\nPrompts ({len(prompts)} total):\n")
        click.echo(f"{'Name':<40} {'Created':<20}")
        click.echo("-" * 65)

        for edge in prompts:
            node = edge["node"]
            name = node.get("name", "")[:40]
            created = node.get("createdAt", "")[:19]
            click.echo(f"{name:<40} {created:<20}")

    except Exception as e:
        logger.error(f"Failed to list prompts: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# TRACE COMMANDS
# =============================================================================


@experiments.group()
def trace():
    """Trace retrieval commands."""
    pass


@trace.command("list")
@click.option("--project", "-p", help="Filter by project name")
@click.option("--days", "-d", default=7, help="Number of days to look back")
@click.option("--limit", "-l", default=20, help="Maximum traces to return")
def trace_list(
    project: Optional[str],
    days: int,
    limit: int,
):
    """List recent traces.

    Example:
        rem experiments trace list --project rem-agents --days 7 --limit 50
    """
    from rem.services.phoenix import PhoenixClient
    from rem.utils.date_utils import days_ago

    try:
        client = PhoenixClient()

        start_time = days_ago(days)

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
# EXPORT COMMAND
# =============================================================================


@experiments.command("export")
@click.argument("name")
@click.option("--base-path", help="Base directory for experiments (default: EXPERIMENTS_HOME or 'experiments')")
@click.option("--bucket", "-b", help="S3 bucket name (default: DATA_LAKE__BUCKET_NAME)")
@click.option("--version", "-v", default="v0", help="Data lake version prefix (default: v0)")
@click.option("--plan", is_flag=True, help="Show what would be exported without uploading")
@click.option("--include-results", is_flag=True, help="Include results directory in export")
def export(
    name: str,
    base_path: Optional[str],
    bucket: Optional[str],
    version: str,
    plan: bool,
    include_results: bool,
):
    """Export experiment to S3 data lake.

    Exports experiment configuration, ground truth, and optionally results
    to the S3 data lake following the convention:

        s3://{bucket}/{version}/datasets/calibration/experiments/{agent}/{task}/

    The export includes:
    - experiment.yaml (configuration)
    - README.md (documentation)
    - ground-truth/ (evaluation datasets)
    - seed-data/ (optional seed data)
    - results/ (optional, with --include-results)

    Examples:
        # Preview what would be exported
        rem experiments export my-experiment --plan

        # Export to configured data lake bucket
        rem experiments export my-experiment

        # Export to specific bucket
        rem experiments export my-experiment --bucket siggy-data

        # Include results in export
        rem experiments export my-experiment --include-results

        # Export with custom version prefix
        rem experiments export my-experiment --version v1
    """
    from rem.models.core.experiment import ExperimentConfig
    from rem.settings import settings
    from rem.services.fs.s3_provider import S3Provider
    import os
    import json

    try:
        # Resolve base path
        if base_path is None:
            base_path = os.getenv("EXPERIMENTS_HOME", "experiments")

        # Load experiment configuration
        config_path = Path(base_path) / name / "experiment.yaml"
        if not config_path.exists():
            click.echo(f"Experiment not found: {name}")
            click.echo(f"  Looked in: {config_path}")
            raise click.Abort()

        config = ExperimentConfig.from_yaml(config_path)
        click.echo(f"✓ Loaded experiment: {name}")

        # Resolve bucket
        if bucket is None:
            bucket = settings.data_lake.bucket_name
            if bucket is None:
                click.echo("Error: No S3 bucket configured.")
                click.echo("  Set DATA_LAKE__BUCKET_NAME environment variable or use --bucket option")
                raise click.Abort()

        # Build S3 paths
        s3_base = config.get_s3_export_path(bucket, version)
        exp_dir = config.get_experiment_dir(base_path)

        # Collect files to export
        files_to_export = []

        # Always include these files
        required_files = [
            ("experiment.yaml", exp_dir / "experiment.yaml"),
            ("README.md", exp_dir / "README.md"),
        ]

        for s3_name, local_path in required_files:
            if local_path.exists():
                files_to_export.append((s3_name, local_path))

        # Include ground-truth directory
        ground_truth_dir = exp_dir / "ground-truth"
        if ground_truth_dir.exists():
            for f in ground_truth_dir.rglob("*"):
                if f.is_file():
                    relative = f.relative_to(exp_dir)
                    files_to_export.append((str(relative), f))

        # Include seed-data directory
        seed_data_dir = exp_dir / "seed-data"
        if seed_data_dir.exists():
            for f in seed_data_dir.rglob("*"):
                if f.is_file():
                    relative = f.relative_to(exp_dir)
                    files_to_export.append((str(relative), f))

        # Optionally include results
        if include_results:
            results_dir = exp_dir / "results"
            if results_dir.exists():
                for f in results_dir.rglob("*"):
                    if f.is_file():
                        relative = f.relative_to(exp_dir)
                        files_to_export.append((str(relative), f))

        # Display export plan
        click.echo(f"\n{'=' * 60}")
        click.echo(f"EXPORT {'PLAN' if plan else 'TO S3'}")
        click.echo(f"{'=' * 60}")
        click.echo(f"\nExperiment: {config.name}")
        click.echo(f"Agent: {config.agent_schema_ref.name}")
        click.echo(f"Task: {config.task}")
        click.echo(f"Evaluator file: {config.get_evaluator_filename()}")
        click.echo(f"\nDestination: {s3_base}/")
        click.echo(f"\nFiles to export ({len(files_to_export)}):")

        for s3_name, local_path in files_to_export:
            s3_uri = f"{s3_base}/{s3_name}"
            if plan:
                click.echo(f"  {local_path}")
                click.echo(f"    → {s3_uri}")
            else:
                click.echo(f"  {s3_name}")

        if plan:
            click.echo(f"\n[PLAN MODE] No files were uploaded.")
            click.echo(f"Run without --plan to execute the export.")
            return

        # Execute export
        click.echo(f"\n⏳ Uploading to S3...")
        s3 = S3Provider()

        uploaded = 0
        for s3_name, local_path in files_to_export:
            s3_uri = f"{s3_base}/{s3_name}"
            try:
                s3.copy(str(local_path), s3_uri)
                uploaded += 1
                click.echo(f"  ✓ {s3_name}")
            except Exception as e:
                click.echo(f"  ✗ {s3_name}: {e}")

        click.echo(f"\n✓ Exported {uploaded}/{len(files_to_export)} files to {s3_base}/")

        # Show next steps
        click.echo(f"\nNext steps:")
        click.echo(f"  - View in S3: aws s3 ls {s3_base}/ --recursive")
        click.echo(f"  - Download: aws s3 sync {s3_base}/ ./{config.agent_schema_ref.name}/{config.task}/")

    except Exception as e:
        logger.error(f"Failed to export experiment: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()
