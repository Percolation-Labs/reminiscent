"""
Experiment management CLI commands.

Experiments use ExperimentConfig (rem/models/core/experiment.py) for configuration
and delegate to Phoenix provider for execution. Supports Git+S3 hybrid storage.

Directory Structure:
    .experiments/{experiment-name}/
    ├── experiment.yaml          # ExperimentConfig
    ├── README.md                # Auto-generated docs
    ├── datasets/                # Optional: small datasets
    └── results/                 # Optional: metrics summaries

Commands:
    rem experiments create <name> --agent <agent> --evaluator <evaluator>
    rem experiments list
    rem experiments show <name>
    rem experiments run <name> [--version <tag>]
    rem experiments diff <name> v1.0.0 v2.0.0
"""

import asyncio
from pathlib import Path
from typing import Any, Optional

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
@click.option("--evaluator", "-e", default="default", help="Evaluator schema name (default: 'default')")
@click.option("--description", "-d", help="Experiment description")
@click.option("--dataset-location", type=click.Choice(["git", "s3", "hybrid"]), default="git",
              help="Where to store datasets")
@click.option("--results-location", type=click.Choice(["git", "s3", "hybrid"]), default="git",
              help="Where to store results")
@click.option("--tags", help="Comma-separated tags (e.g., 'production,cv-parser')")
@click.option("--base-path", default=".experiments", help="Base directory for experiments")
def create(
    name: str,
    agent: str,
    evaluator: str,
    description: Optional[str],
    dataset_location: str,
    results_location: str,
    tags: Optional[str],
    base_path: str,
):
    """Create a new experiment configuration.

    Creates directory structure and generates experiment.yaml and README.md.

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
    """
    from rem.models.core.experiment import (
        ExperimentConfig,
        DatasetLocation,
        DatasetReference,
        SchemaReference,
        ResultsConfig,
        ExperimentStatus,
    )

    try:
        # Build dataset reference
        if dataset_location == "git":
            dataset_ref = DatasetReference(
                location=DatasetLocation.GIT,
                path="datasets/ground_truth.csv",
                format="csv",
                description="Ground truth dataset for evaluation"
            )
        else:  # s3 or hybrid
            dataset_ref = DatasetReference(
                location=DatasetLocation(dataset_location),
                path=f"s3://rem-experiments/{name}/datasets/ground_truth.parquet",
                format="parquet",
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
            description=description or f"Evaluation experiment for {agent} agent",
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

        # Create datasets directory
        datasets_dir = config.get_experiment_dir(base_path) / "datasets"
        datasets_dir.mkdir(parents=True, exist_ok=True)

        # Create results directory if Git-based
        if results_location == "git":
            results_dir = config.get_experiment_dir(base_path) / "results"
            results_dir.mkdir(parents=True, exist_ok=True)

        click.echo(f"\n✓ Created experiment: {name}")
        click.echo(f"  Configuration: {config_path}")
        click.echo(f"  Documentation: {readme_path}")
        click.echo(f"  Datasets: {datasets_dir}")
        if results_location == "git":
            click.echo(f"  Results: {results_dir}")
        click.echo(f"\nNext steps:")
        click.echo(f"  1. Add dataset to {datasets_dir}/")
        click.echo(f"  2. Review configuration: {config_path}")
        click.echo(f"  3. Run experiment: rem experiments run {name}")
        click.echo(f"  4. Commit to Git: git add .experiments/{name}/ && git commit")

    except Exception as e:
        logger.error(f"Failed to create experiment: {e}")
        click.echo(f"Error: {e}", err=True)
        raise click.Abort()


# =============================================================================
# LIST COMMAND
# =============================================================================


@experiments.command("list")
@click.option("--base-path", default=".experiments", help="Base directory for experiments")
@click.option("--status", help="Filter by status (draft, ready, completed, etc.)")
@click.option("--tags", help="Filter by tags (comma-separated)")
def list_experiments(
    base_path: str,
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

    try:
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
@click.option("--base-path", default=".experiments", help="Base directory for experiments")
def show(name: str, base_path: str):
    """Show experiment details.

    Examples:
        rem experiments show hello-world-validation
    """
    from rem.models.core.experiment import ExperimentConfig

    try:
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
# RUN COMMAND
# =============================================================================


@experiments.command("run")
@click.argument("name")
@click.option("--base-path", default=".experiments", help="Base directory for experiments")
@click.option("--version", help="Git tag version to load (e.g., 'experiments/my-exp/v1.0.0')")
@click.option("--dry-run", is_flag=True, help="Test on small subset without saving")
@click.option("--update-prompts", is_flag=True, help="Update prompts in Phoenix before running")
@click.option("--phoenix-url", help="Phoenix server URL (overrides PHOENIX_BASE_URL env var)")
@click.option("--phoenix-api-key", help="Phoenix API key (overrides PHOENIX_API_KEY env var)")
def run(
    name: str,
    base_path: str,
    version: Optional[str],
    dry_run: bool,
    update_prompts: bool,
    phoenix_url: Optional[str],
    phoenix_api_key: Optional[str],
):
    """Run an experiment using Phoenix provider.

    Loads configuration, executes agent and evaluator, saves results.

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
    from datetime import datetime
    import pandas as pd

    try:
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

        # Load agent schema from Git or filesystem
        agent_name = config.agent_schema_ref.name
        agent_version = config.agent_schema_ref.version

        click.echo(f"Loading agent schema: {agent_name} (version: {agent_version or 'latest'})")

        # Try Git first, fallback to filesystem
        agent_schema = None
        try:
            git_svc = GitService()
            agent_schema = git_svc.load_schema(agent_name, version=agent_version)
            click.echo(f"✓ Loaded agent schema from Git")
        except Exception as e:
            logger.debug(f"Git not available, trying filesystem: {e}")

            # Fallback to local filesystem
            from rem.services.fs import FS
            fs = FS()

            schema_path = f"schemas/agents/{agent_name}.yaml"
            try:
                agent_schema = fs.read(schema_path)
                click.echo(f"✓ Loaded agent schema from filesystem")
            except Exception as fs_error:
                logger.error(f"Failed to load agent schema: Git: {e}, FS: {fs_error}")
                click.echo(f"Error: Could not load agent schema '{agent_name}'")
                click.echo(f"  Tried Git: {e}")
                click.echo(f"  Tried filesystem: {schema_path}")
                click.echo(f"  Make sure the schema exists")
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

        agent = asyncio.run(create_agent(
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
            result = asyncio.run(agent.run(query))

            # Serialize result (critical for Pydantic models!)
            from rem.agentic.serialization import serialize_agent_result
            return serialize_agent_result(result)

        # Load evaluator schema
        evaluator_name = config.evaluator_schema_ref.name
        evaluator_version = config.evaluator_schema_ref.version

        # Resolve evaluator path (evaluators are organized by agent name)
        evaluator_schema_path = f"rem/schemas/evaluators/{agent_name}/{evaluator_name}.yaml"

        click.echo(f"Loading evaluator: {evaluator_name} for agent {agent_name}")

        try:
            evaluator_fn = create_evaluator_from_schema(
                evaluator_schema_path=evaluator_schema_path,
                model_name=None,  # Use default from schema
            )
            click.echo(f"✓ Loaded evaluator schema")
        except Exception as e:
            logger.warning(f"Failed to load evaluator: {e}")
            click.echo(f"Error: Could not load evaluator schema")
            click.echo(f"  Path: {evaluator_schema_path}")
            click.echo(f"  Make sure the schema exists")
            raise click.Abort()

        # Load dataset
        click.echo(f"Loading dataset: {list(config.datasets.keys())[0]}")
        dataset_ref = list(config.datasets.values())[0]

        if dataset_ref.location.value == "git":
            # Load from Git
            dataset_path = Path(base_path) / name / dataset_ref.path
            if not dataset_path.exists():
                click.echo(f"Error: Dataset not found: {dataset_path}")
                raise click.Abort()

            if dataset_ref.format == "csv":
                dataset_df = pd.read_csv(dataset_path)
            elif dataset_ref.format == "parquet":
                dataset_df = pd.read_parquet(dataset_path)
            elif dataset_ref.format == "jsonl":
                dataset_df = pd.read_json(dataset_path, lines=True)
            else:
                click.echo(f"Error: Format '{dataset_ref.format}' not yet supported")
                raise click.Abort()
        elif dataset_ref.location.value in ["s3", "hybrid"]:
            # Load from S3 using FS provider
            from rem.services.fs import FS

            fs = FS()

            try:
                if dataset_ref.format == "csv":
                    content = fs.read(dataset_ref.path)
                    from io import StringIO
                    dataset_df = pd.read_csv(StringIO(content))
                elif dataset_ref.format == "parquet":
                    # For parquet, we need binary read
                    import tempfile
                    with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp:
                        tmp_path = tmp.name
                        # Download via FS
                        content_bytes = fs.read(dataset_ref.path)
                        tmp.write(content_bytes)
                    dataset_df = pd.read_parquet(tmp_path)
                    Path(tmp_path).unlink()  # Clean up temp file
                elif dataset_ref.format == "jsonl":
                    content = fs.read(dataset_ref.path)
                    from io import StringIO
                    dataset_df = pd.read_json(StringIO(content), lines=True)
                else:
                    click.echo(f"Error: Format '{dataset_ref.format}' not yet supported")
                    raise click.Abort()

                click.echo(f"✓ Loaded dataset from S3")
            except Exception as e:
                logger.error(f"Failed to load dataset from S3: {e}")
                click.echo(f"Error: Could not load dataset from S3")
                click.echo(f"  Path: {dataset_ref.path}")
                click.echo(f"  Format: {dataset_ref.format}")
                raise click.Abort()
        else:
            click.echo(f"Error: Unknown dataset location: {dataset_ref.location.value}")
            raise click.Abort()

        click.echo(f"✓ Loaded dataset: {len(dataset_df)} examples")

        # Update prompts in Phoenix if requested
        if update_prompts:
            # TODO: Implement prompt updating
            click.echo("⚠  --update-prompts not yet implemented")

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

            experiment_name = f"{config.name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

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
                }
            )

            # Update experiment status
            config.status = ExperimentStatus.COMPLETED
            config.last_run_at = datetime.now()
            if not version:  # Only save if not loading from Git
                config.save(base_path)

            click.echo(f"\n✓ Experiment complete!")
            if hasattr(experiment, "url"):
                click.echo(f"  View results: {experiment.url}")

            # Save results according to config.results settings
            if config.results.save_metrics_summary:
                # Get experiment data
                try:
                    exp_data = client.get_experiment(experiment.id)

                    # Build metrics summary
                    metrics = {
                        "experiment_id": experiment.id,
                        "experiment_name": experiment_name,
                        "agent": config.agent_schema_ref.name,
                        "evaluator": config.evaluator_schema_ref.name,
                        "dataset_size": len(dataset_df),
                        "completed_at": datetime.now().isoformat(),
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
