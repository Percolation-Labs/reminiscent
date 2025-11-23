"""Phoenix client for REM evaluation workflows.

This client provides a lean interface to Arize Phoenix for:
- Dataset management (create golden sets, add examples)
- Experiment execution (run agents, run evaluators)
- Trace retrieval (query agent execution history)
- Label management (organize evaluations by type/difficulty)

Two-Phase Evaluation Pattern:
==============================

Phase 1 - Golden Set Creation (SME-driven):
  1. SMEs create datasets with (input, reference) pairs
  2. Store in Phoenix with metadata labels
  3. No agent execution required

Phase 2 - Automated Evaluation (Agent-driven):
  1. Run agents on golden set → agent outputs
  2. Run evaluators on (input, agent_output, reference) → scores
  3. Track in Phoenix for analysis

Example Workflow:
-----------------

# Phase 1: SME creates golden set
client = PhoenixClient()
dataset = client.create_dataset_from_data(
    name="rem-lookup-golden",
    inputs=[{"query": "LOOKUP person:sarah-chen"}],
    outputs=[{"label": "sarah-chen", "type": "person", ...}],
    metadata=[{"difficulty": "easy", "query_type": "LOOKUP"}]
)

# Phase 2a: Run agents to produce outputs
experiment = client.run_experiment(
    dataset=dataset,
    task=run_agent_task,  # Calls ask_rem agent
    experiment_name="rem-v1-baseline"
)

# Phase 2b: Run evaluators on results
evaluator_exp = client.run_experiment(
    dataset=experiment_results,  # Uses agent outputs
    task=None,  # No task, just evaluate existing outputs
    evaluators=[correctness_evaluator, completeness_evaluator],
    experiment_name="rem-v1-evaluation"
)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING, cast

import pandas as pd
from loguru import logger

from .config import PhoenixConfig

if TYPE_CHECKING:
    from phoenix.client import Client
    from phoenix.client.resources.datasets import Dataset
    from phoenix.client.resources.experiments.types import RanExperiment


class PhoenixClient:
    """High-level Phoenix client for REM evaluation workflows.

    Wraps the official Phoenix client with REM-specific methods for:
    - Creating and managing evaluation datasets
    - Running agent and evaluator experiments
    - Querying trace data for analysis
    - Managing dataset labels

    Attributes:
        config: Phoenix connection configuration
        _client: Underlying Phoenix Client instance
    """

    def __init__(self, config: PhoenixConfig | None = None):
        """Initialize Phoenix client.

        Args:
            config: Optional Phoenix configuration (auto-loads if not provided)
        """
        if config is None:
            config = PhoenixConfig.from_settings()

        self.config = config
        self._client = self._create_client()

        logger.info(f"Phoenix client initialized (endpoint: {self.config.base_url})")

    def _create_client(self) -> "Client":
        """Create underlying Phoenix client.

        Returns:
            Configured Phoenix Client instance
        """
        from phoenix.client import Client

        return Client(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    # =========================================================================
    # DATASET MANAGEMENT
    # =========================================================================

    def list_datasets(self) -> list[dict[str, Any]]:
        """List all datasets in Phoenix.

        Returns:
            List of dataset metadata dicts with keys:
            - id: Dataset ID
            - name: Dataset name
            - example_count: Number of examples
            - created_at: Creation timestamp
        """
        try:
            datasets = list(self._client.datasets.list())
            logger.debug(f"Found {len(datasets)} datasets")
            return [
                {
                    "id": str(ds.get("id", "")),
                    "name": ds.get("name", ""),
                    "example_count": ds.get("example_count", 0),
                    "created_at": ds.get("created_at", ""),
                }
                for ds in datasets
            ]
        except Exception as e:
            logger.error(f"Failed to list datasets: {e}")
            raise

    def get_dataset(self, name: str) -> "Dataset":
        """Get a dataset by name.

        Args:
            name: Dataset name

        Returns:
            Dataset instance

        Raises:
            ValueError: If dataset not found
        """
        try:
            dataset = self._client.datasets.get_dataset(dataset=name)
            logger.debug(f"Loaded dataset: {name} ({len(dataset)} examples)")
            return dataset
        except Exception as e:
            logger.error(f"Failed to get dataset '{name}': {e}")
            raise ValueError(f"Dataset not found: {name}") from e

    def create_dataset_from_data(
        self,
        name: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        metadata: list[dict[str, Any]] | None = None,
        description: str | None = None,
    ) -> "Dataset":
        """Create a dataset from input/output pairs (SME golden set creation).

        This is the primary method for SMEs to create evaluation datasets.
        Each example consists of:
        - input: What the agent receives (e.g., {"query": "LOOKUP person:sarah-chen"})
        - output: Expected correct result (ground truth/reference)
        - metadata: Optional labels (difficulty, query_type, etc.)

        Args:
            name: Dataset name (will be created or updated)
            inputs: List of input dicts (what agents receive)
            outputs: List of expected output dicts (ground truth)
            metadata: Optional list of metadata dicts (labels, difficulty, etc.)
            description: Optional dataset description

        Returns:
            Created Dataset instance

        Example:
            >>> client = PhoenixClient()
            >>> dataset = client.create_dataset_from_data(
            ...     name="rem-lookup-golden",
            ...     inputs=[
            ...         {"query": "LOOKUP person:sarah-chen"},
            ...         {"query": "LOOKUP project:tidb-migration"}
            ...     ],
            ...     outputs=[
            ...         {"label": "sarah-chen", "type": "person", "properties": {...}},
            ...         {"label": "tidb-migration", "type": "project", "properties": {...}}
            ...     ],
            ...     metadata=[
            ...         {"difficulty": "easy", "query_type": "LOOKUP"},
            ...         {"difficulty": "medium", "query_type": "LOOKUP"}
            ...     ]
            ... )
        """
        try:
            # Validate inputs/outputs match
            if len(inputs) != len(outputs):
                raise ValueError(
                    f"Input count ({len(inputs)}) must match output count ({len(outputs)})"
                )

            # Create metadata list if not provided
            if metadata is None:
                metadata = [{} for _ in inputs]
            elif len(metadata) != len(inputs):
                raise ValueError(
                    f"Metadata count ({len(metadata)}) must match input count ({len(inputs)})"
                )

            # Create dataset
            dataset = self._client.datasets.create_dataset(
                name=name,
                dataset_description=description,
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
            )

            logger.info(f"Created dataset '{name}' with {len(inputs)} examples")
            return dataset

        except Exception as e:
            logger.error(f"Failed to create dataset '{name}': {e}")
            raise

    def create_dataset_from_csv(
        self,
        name: str,
        csv_file_path: Path | str,
        input_keys: list[str],
        output_keys: list[str],
        metadata_keys: list[str] | None = None,
        description: str | None = None,
    ) -> "Dataset":
        """Create a dataset from a CSV file.

        Convenience method for loading golden sets from CSV files.

        Args:
            name: Dataset name
            csv_file_path: Path to CSV file
            input_keys: Column names to use as inputs
            output_keys: Column names to use as outputs (reference/ground truth)
            metadata_keys: Optional column names for metadata
            description: Optional dataset description

        Returns:
            Created Dataset instance

        Example CSV structure:
            query,expected_label,expected_type,difficulty,query_type
            "LOOKUP person:sarah-chen",sarah-chen,person,easy,LOOKUP
            "SEARCH semantic AI engineer",sarah-chen,person,medium,SEARCH
        """
        try:
            # Load CSV
            df = pd.read_csv(csv_file_path)

            # Extract inputs
            inputs = cast(list[dict[str, Any]], df[input_keys].to_dict("records"))

            # Extract outputs
            outputs = cast(list[dict[str, Any]], df[output_keys].to_dict("records"))

            # Extract metadata if specified
            metadata = None
            if metadata_keys:
                metadata = cast(list[dict[str, Any]], df[metadata_keys].to_dict("records"))

            return self.create_dataset_from_data(
                name=name,
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
                description=description,
            )

        except Exception as e:
            logger.error(f"Failed to create dataset from CSV '{csv_file_path}': {e}")
            raise

    def add_examples_to_dataset(
        self,
        dataset: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        metadata: list[dict[str, Any]] | None = None,
    ) -> "Dataset":
        """Add examples to an existing dataset.

        Args:
            dataset: Dataset name
            inputs: List of input dicts
            outputs: List of output dicts
            metadata: Optional list of metadata dicts

        Returns:
            Updated Dataset instance
        """
        try:
            if len(inputs) != len(outputs):
                raise ValueError("Input/output counts must match")

            if metadata is None:
                metadata = [{} for _ in inputs]

            updated_dataset = self._client.datasets.add_examples_to_dataset(
                dataset,  # Positional argument instead of keyword
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
            )

            logger.info(f"Added {len(inputs)} examples to dataset '{dataset}'")
            return updated_dataset

        except Exception as e:
            logger.error(f"Failed to add examples to dataset '{dataset}': {e}")
            raise

    # =========================================================================
    # EXPERIMENT EXECUTION
    # =========================================================================

    def run_experiment(
        self,
        dataset: "Dataset" | str,
        task: Callable[[Any], Any] | None = None,
        evaluators: list[Callable[[Any], Any]] | None = None,
        experiment_name: str | None = None,
        experiment_description: str | None = None,
        experiment_metadata: dict[str, Any] | None = None,
        experiment_config: Any | None = None,
    ) -> "RanExperiment":
        """Run an evaluation experiment.

        Three modes:
        1. ExperimentConfig mode: Provide experiment_config with all settings
        2. Agent run: Provide task function to execute agents on dataset
        3. Evaluator run: Provide evaluators to score existing outputs

        Args:
            dataset: Dataset instance or name (required unless experiment_config provided)
            task: Optional task function to run on each example (agent execution)
            evaluators: Optional list of evaluator functions
            experiment_name: Optional experiment name
            experiment_description: Optional description
            experiment_metadata: Optional metadata dict
            experiment_config: Optional ExperimentConfig instance (overrides other params)

        Returns:
            RanExperiment with results

        Example - Agent Run (Phase 2a):
            >>> async def run_agent(example):
            ...     from rem.mcp.tools.rem import ask_rem
            ...     result = await ask_rem(example["input"]["query"])
            ...     return result
            >>> experiment = client.run_experiment(
            ...     dataset="rem-lookup-golden",
            ...     task=run_agent,
            ...     experiment_name="rem-v1-baseline"
            ... )

        Example - Evaluator Run (Phase 2b):
            >>> experiment = client.run_experiment(
            ...     dataset=agent_results,
            ...     evaluators=[correctness_eval, completeness_eval],
            ...     experiment_name="rem-v1-evaluation"
            ... )
        """
        try:
            # Handle ExperimentConfig mode
            if experiment_config:
                experiment_name = experiment_name or experiment_config.name
                experiment_description = experiment_description or experiment_config.description

                # Merge metadata
                config_metadata = {
                    "agent_schema": experiment_config.agent_schema_ref.name,
                    "agent_version": experiment_config.agent_schema_ref.version,
                    "evaluator_schema": experiment_config.evaluator_schema_ref.name,
                    "evaluator_version": experiment_config.evaluator_schema_ref.version,
                    "config_status": experiment_config.status.value,
                    "config_tags": experiment_config.tags,
                }
                config_metadata.update(experiment_config.metadata or {})
                experiment_metadata = experiment_metadata or config_metadata

                # Use ground_truth dataset if dataset not provided
                if not dataset and "ground_truth" in experiment_config.datasets:
                    dataset_ref = experiment_config.datasets["ground_truth"]
                    # Load from Git or use provided path
                    if dataset_ref.location.value == "git":
                        # Assume dataset is already loaded
                        logger.warning(
                            f"Dataset location is 'git' but path-based loading not implemented. "
                            f"Pass dataset explicitly or use Phoenix dataset name."
                        )
                    else:
                        dataset = dataset_ref.path

            # Load dataset if name provided
            if isinstance(dataset, str):
                dataset = self.get_dataset(dataset)

            logger.info(
                f"Running experiment '{experiment_name or 'unnamed'}' "
                f"on dataset with {len(dataset)} examples"
            )

            # Run experiment
            experiment = self._client.experiments.run_experiment(
                dataset=dataset,
                task=task,  # type: ignore[arg-type]
                evaluators=evaluators or [],
                experiment_name=experiment_name,
                experiment_description=experiment_description,
                experiment_metadata=experiment_metadata,
            )

            logger.success(f"Experiment complete: {experiment_name or 'unnamed'}")
            if hasattr(experiment, "url"):
                logger.info(f"View results: {experiment.url}")  # type: ignore[attr-defined]

            # Update ExperimentConfig if provided
            if experiment_config:
                experiment_config.last_run_at = datetime.now()
                experiment_config.status = "running" if hasattr(experiment, "runs") else "completed"

            return experiment

        except Exception as e:
            logger.error(f"Failed to run experiment: {e}")
            raise

    # =========================================================================
    # TRACE RETRIEVAL
    # =========================================================================

    def get_traces(
        self,
        project_name: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        root_spans_only: bool = True,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> pd.DataFrame:
        """Query traces from Phoenix.

        Args:
            project_name: Filter by project name
            start_time: Filter traces after this time
            end_time: Filter traces before this time
            limit: Maximum number of traces to return
            root_spans_only: Only return root spans (default: True)
            trace_id: Filter by specific trace ID
            span_id: Filter by specific span ID

        Returns:
            DataFrame with trace data

        Example:
            >>> traces = client.get_traces(
            ...     project_name="rem-agents",
            ...     start_time=datetime.now() - timedelta(days=7),
            ...     limit=50
            ... )
        """
        try:
            # Build query
            query_params: dict[str, Any] = {}
            if project_name:
                query_params["project_name"] = project_name
            if start_time:
                query_params["start_time"] = start_time.isoformat()
            if end_time:
                query_params["end_time"] = end_time.isoformat()
            if root_spans_only:
                query_params["root_spans_only"] = True
            if trace_id:
                query_params["trace_id"] = trace_id
            if span_id:
                query_params["span_id"] = span_id

            # Query traces
            traces_df = self._client.query_spans(limit=limit, **query_params)  # type: ignore[attr-defined]

            logger.debug(f"Retrieved {len(traces_df)} traces")
            return traces_df

        except Exception as e:
            logger.error(f"Failed to query traces: {e}")
            raise

    def create_dataset_from_traces(
        self,
        name: str,
        project_name: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        description: str | None = None,
    ) -> "Dataset":
        """Create a dataset from production traces.

        Useful for regression testing and coverage analysis.

        Args:
            name: Dataset name
            project_name: Phoenix project name to query traces from
            start_time: Optional start time for trace window
            end_time: Optional end time for trace window
            limit: Maximum number of traces to include
            description: Optional dataset description

        Returns:
            Created Dataset instance

        Example:
            >>> dataset = client.create_dataset_from_traces(
            ...     name="rem-production-regression",
            ...     project_name="rem-production",
            ...     start_time=datetime.now() - timedelta(days=30),
            ...     limit=500
            ... )
        """
        try:
            # Query traces
            traces_df = self.get_traces(
                project_name=project_name,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                root_spans_only=True,
            )

            if len(traces_df) == 0:
                raise ValueError("No traces found matching criteria")

            # Extract inputs and outputs from traces
            inputs = []
            outputs = []
            metadata = []

            for _, row in traces_df.iterrows():
                # Extract input
                span_input = row.get("attributes.input")
                if span_input:
                    if isinstance(span_input, str):
                        inputs.append({"input": span_input})
                    else:
                        inputs.append(span_input)
                else:
                    inputs.append({})

                # Extract output
                span_output = row.get("attributes.output")
                if span_output:
                    if isinstance(span_output, str):
                        outputs.append({"output": span_output})
                    else:
                        outputs.append(span_output)
                else:
                    outputs.append({})

                # Extract metadata
                metadata.append({
                    "span_id": str(row.get("context.span_id", "")),
                    "trace_id": str(row.get("context.trace_id", "")),
                    "start_time": str(row.get("start_time", "")),
                    "latency_ms": row.get("latency_ms", 0),
                })

            # Create dataset
            dataset = self.create_dataset_from_data(
                name=name,
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
                description=description,
            )

            logger.info(f"Created dataset '{name}' from {len(inputs)} traces")
            return dataset

        except Exception as e:
            logger.error(f"Failed to create dataset from traces: {e}")
            raise

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Get experiment data including task runs.

        Args:
            experiment_id: Experiment ID (from Phoenix UI URL)

        Returns:
            Dictionary with experiment data including:
            - id: Experiment ID
            - name: Experiment name
            - dataset_id: Associated dataset ID
            - experiment_metadata: Metadata dict
            - task_runs: List of task run results

        Example:
            >>> exp_data = client.get_experiment("RXhwZXJpbWVudDoxMjM=")
            >>> print(f"Experiment: {exp_data['name']}")
            >>> print(f"Task runs: {len(exp_data['task_runs'])}")
        """
        try:
            # Get experiment object
            experiment = self._client.experiments.get_experiment(experiment_id)  # type: ignore[misc]

            # Extract task runs
            task_runs = []
            for run in experiment.runs:  # type: ignore[attr-defined]
                task_runs.append({
                    "input": run.input,
                    "output": run.output,
                    "expected": run.expected,
                    "dataset_example_id": getattr(run, "dataset_example_id", None),
                })

            # Build response
            exp_data = {
                "id": experiment.id,  # type: ignore[attr-defined]
                "name": experiment.name,  # type: ignore[attr-defined]
                "dataset_id": experiment.dataset_id,  # type: ignore[attr-defined]
                "experiment_metadata": experiment.metadata or {},  # type: ignore[attr-defined]
                "task_runs": task_runs,
            }

            logger.info(f"Retrieved experiment '{experiment.name}' with {len(task_runs)} task runs")  # type: ignore[attr-defined]
            return exp_data

        except Exception as e:
            logger.error(f"Failed to get experiment '{experiment_id}': {e}")
            raise

    # =========================================================================
    # FEEDBACK/ANNOTATION
    # =========================================================================

    def add_span_feedback(
        self,
        span_id: str,
        annotation_name: str,
        annotator_kind: str = "HUMAN",
        label: str | None = None,
        score: float | None = None,
        explanation: str | None = None,
    ) -> None:
        """Add feedback annotation to a span.

        Args:
            span_id: Span ID to annotate
            annotation_name: Name of the annotation (e.g., "correctness")
            annotator_kind: Type of annotator ("HUMAN", "LLM", "CODE")
            label: Optional label (e.g., "correct", "incorrect")
            score: Optional numeric score (0.0-1.0)
            explanation: Optional explanation text
        """
        try:
            self._client.add_span_annotation(  # type: ignore[attr-defined]
                span_id=span_id,
                name=annotation_name,
                annotator_kind=annotator_kind,
                label=label,
                score=score,
                explanation=explanation,
            )

            logger.info(f"Added {annotator_kind} feedback to span {span_id}")

        except Exception as e:
            logger.error(f"Failed to add span feedback: {e}")
            raise
