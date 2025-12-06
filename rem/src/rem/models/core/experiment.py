"""
Experiment configuration model for Phoenix evaluations.

This model defines the structure and conventions for REM experiments,
supporting hybrid storage between Git (configurations) and S3 (datasets/results).

**Storage Convention**:
- **Git**: `.experiments/{experiment-name}/` for configuration and metadata
- **S3**: `s3://bucket/experiments/{experiment-name}/` for datasets and results
- **Hybrid**: Git acts as an "overlay" - configurations reference S3 paths

**Directory Structure**:
```
.experiments/
└── {experiment-name}/
    ├── experiment.yaml          # This model (configuration)
    ├── README.md                # Experiment documentation
    └── results/                 # Optional: Git-tracked results (small datasets)
        ├── metrics.json
        └── traces/

s3://bucket/experiments/
└── {experiment-name}/
    ├── datasets/                # Source data (too large for Git)
    │   ├── ground_truth.csv
    │   └── test_cases.jsonl
    └── results/                 # Experiment outputs
        ├── run-2025-01-15/
        └── run-2025-01-16/
```

**Use Cases**:

1. **Small Experiments (Git-only)**:
   - Q&A validation with <100 examples
   - Manual test cases
   - Configuration-driven experiments
   - Store everything in `.experiments/{name}/`

2. **Large Experiments (Hybrid)**:
   - Thousands of test cases
   - Source data on S3, configs in Git
   - Results on S3, metrics in Git
   - `.experiments/{name}/experiment.yaml` references `s3://` paths

3. **Production Experiments (S3-primary)**:
   - Continuous evaluation pipelines
   - Large-scale A/B tests
   - Real-time dataset generation
   - Git stores only configuration, all data on S3

**Workflow**:

```bash
# 1. Create experiment scaffold
rem experiments create my-experiment \\
    --agent cv-parser \\
    --evaluator default \\
    --description "Test CV parsing accuracy"

# 2. Generated structure:
.experiments/my-experiment/
├── experiment.yaml              # Configuration (this model)
├── README.md                    # Auto-generated documentation
└── datasets/                    # Optional: small datasets
    └── ground_truth.csv

# 3. Run experiment
rem experiments run my-experiment

# 4. Commit configuration to Git
git add .experiments/my-experiment/
git commit -m "feat: Add CV parser experiment"
git tag -a experiments/my-experiment/v1.0.0 \\
    -m "my-experiment v1.0.0: Initial experiment"
```

**Version Tags**:
- Format: `experiments/{experiment-name}/vX.Y.Z`
- Example: `experiments/cv-parser-accuracy/v1.0.0`
- Allows tracking experiment configuration evolution
- GitProvider can load specific experiment versions

**Integration with Phoenix**:
```python
from rem.models.core.experiment import ExperimentConfig
from rem.services.phoenix import PhoenixClient

# Load experiment configuration
config = ExperimentConfig.from_yaml(".experiments/my-experiment/experiment.yaml")

# Run experiment
client = PhoenixClient()
results = client.run_experiment(
    name=config.name,
    agent_schema=config.agent_schema_ref,
    evaluator_schema=config.evaluator_schema_ref,
    dataset=config.load_dataset(),
    metadata=config.metadata
)

# Save results
config.save_results(results)
```
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class DatasetLocation(str, Enum):
    """Where experiment datasets are stored."""
    GIT = "git"        # Small datasets in .experiments/{name}/datasets/
    S3 = "s3"          # Large datasets on S3
    HYBRID = "hybrid"  # Configuration in Git, data on S3


class ExperimentStatus(str, Enum):
    """Experiment lifecycle status."""
    DRAFT = "draft"              # Configuration being defined
    READY = "ready"              # Ready to run
    RUNNING = "running"          # Currently executing
    COMPLETED = "completed"      # Finished successfully
    FAILED = "failed"            # Execution failed
    ARCHIVED = "archived"        # Historical experiment


class DatasetReference(BaseModel):
    """Reference to a dataset (Git or S3)."""

    location: DatasetLocation = Field(
        description="Where the dataset is stored (git, s3, hybrid)"
    )

    path: str = Field(
        description=(
            "Path to dataset. Format is inferred from file extension.\n"
            "Supported: .csv, .tsv, .parquet, .json, .jsonl, .xlsx, .ods, .avro, .ipc\n"
            "- Git: Relative path from experiment root (e.g., 'datasets/ground_truth.csv')\n"
            "- S3: Full S3 URI (e.g., 's3://bucket/experiments/my-exp/datasets/data.parquet')\n"
            "- Hybrid: S3 URI for data, Git path for schema"
        )
    )

    schema_path: str | None = Field(
        default=None,
        description=(
            "Optional: Path to dataset schema definition (for hybrid mode).\n"
            "Useful for documenting expected columns/fields in Git."
        )
    )

    description: str | None = Field(
        default=None,
        description="Human-readable description of this dataset"
    )


class SchemaReference(BaseModel):
    """Reference to an agent or evaluator schema."""

    name: str = Field(
        description=(
            "Schema name (e.g., 'cv-parser', 'hello-world').\n"
            "Corresponds to schemas/agents/{name}.yaml or schemas/evaluators/{agent}/{name}.yaml"
        )
    )

    version: str | None = Field(
        default=None,
        description=(
            "Semantic version tag (e.g., 'schemas/cv-parser/v2.1.0').\n"
            "If None, uses latest version from main branch."
        )
    )

    type: Literal["agent", "evaluator"] = Field(
        description="Schema type (agent or evaluator)"
    )


class ResultsConfig(BaseModel):
    """Configuration for where experiment results are stored."""

    location: DatasetLocation = Field(
        description="Where to store results (git, s3, hybrid)"
    )

    base_path: str = Field(
        description=(
            "Base path for results storage:\n"
            "- Git: '.experiments/{experiment-name}/results/'\n"
            "- S3: 's3://bucket/experiments/{experiment-name}/results/'\n"
            "- Hybrid: Both (small metrics in Git, full traces on S3)"
        )
    )

    save_traces: bool = Field(
        default=True,
        description="Save full Phoenix traces (can be large)"
    )

    save_metrics_summary: bool = Field(
        default=True,
        description="Save metrics summary (small, suitable for Git)"
    )

    metrics_file: str = Field(
        default="metrics.json",
        description="Filename for metrics summary (stored in base_path)"
    )


class ExperimentConfig(BaseModel):
    """
    Complete experiment configuration for Phoenix evaluations.

    This model defines everything needed to run a reproducible experiment:
    - Agent and evaluator schemas (versioned via Git)
    - Dataset references (Git or S3)
    - Results storage configuration
    - Experiment metadata and documentation

    **Naming Convention**:
    - Experiment names: lowercase-with-hyphens (e.g., 'cv-parser-accuracy')
    - Directory: `.experiments/{experiment-name}/`
    - Config file: `.experiments/{experiment-name}/experiment.yaml`
    - Version tags: `experiments/{experiment-name}/vX.Y.Z`

    **Fields**:
    - `name`: Unique experiment identifier
    - `description`: Human-readable purpose
    - `agent_schema_ref`: Which agent to evaluate
    - `evaluator_schema_ref`: Which evaluator to use
    - `datasets`: Input datasets (ground truth, test cases)
    - `results`: Where to store outputs
    - `metadata`: Custom key-value pairs
    - `status`: Current lifecycle stage
    - `tags`: Organizational labels

    **Examples**:

    ```yaml
    # Small experiment (Git-only)
    name: hello-world-validation
    description: Validate hello-world agent responses
    agent_schema_ref:
      name: hello-world
      version: schemas/hello-world/v1.0.0
      type: agent
    evaluator_schema_ref:
      name: default
      type: evaluator
    datasets:
      ground_truth:
        location: git
        path: datasets/ground_truth.csv  # format inferred from extension
    results:
      location: git
      base_path: results/
      save_traces: false
      save_metrics_summary: true
    status: ready
    tags: [validation, smoke-test]
    ```

    ```yaml
    # Large experiment (Hybrid)
    name: cv-parser-production
    description: Production CV parser evaluation with 10K resumes
    agent_schema_ref:
      name: cv-parser
      version: schemas/cv-parser/v2.1.0
      type: agent
    evaluator_schema_ref:
      name: default
      type: evaluator
    datasets:
      ground_truth:
        location: s3
        path: s3://rem-prod/experiments/cv-parser-production/datasets/ground_truth.parquet
        schema_path: datasets/schema.yaml  # Schema in Git for documentation
      test_cases:
        location: s3
        path: s3://rem-prod/experiments/cv-parser-production/datasets/test_cases.jsonl
    results:
      location: hybrid
      base_path: s3://rem-prod/experiments/cv-parser-production/results/
      save_traces: true
      save_metrics_summary: true
      metrics_file: metrics.json  # Copied to Git after run
    metadata:
      cost_per_run_usd: 5.25
      expected_runtime_minutes: 45
      team: recruitment-ai
      priority: high
    status: ready
    tags: [production, cv-parser, weekly]
    ```
    """

    # Core identification
    name: str = Field(
        description=(
            "Unique experiment identifier (lowercase-with-hyphens).\n"
            "Used for directory name, tags, and references."
        )
    )

    task: str = Field(
        default="general",
        description=(
            "Task name for organizing experiments by purpose.\n"
            "Used with agent name to form directory: {agent}/{task}/\n"
            "Examples: 'risk-assessment', 'classification', 'general'"
        )
    )

    description: str = Field(
        description="Human-readable description of experiment purpose and goals"
    )

    # Schema references
    agent_schema_ref: SchemaReference = Field(
        description=(
            "Reference to agent schema being evaluated.\n"
            "Supports versioning via Git tags (e.g., schemas/cv-parser/v2.1.0)"
        )
    )

    evaluator_schema_ref: SchemaReference = Field(
        description=(
            "Reference to evaluator schema for judging agent outputs.\n"
            "Can reference evaluators/{agent-name}/{evaluator-name}.yaml"
        )
    )

    # Dataset configuration
    datasets: dict[str, DatasetReference] = Field(
        description=(
            "Named datasets for this experiment.\n"
            "Common keys: 'ground_truth', 'test_cases', 'validation_set'\n"
            "Supports Git (small datasets), S3 (large datasets), or hybrid"
        )
    )

    # Results configuration
    results: ResultsConfig = Field(
        description=(
            "Configuration for experiment results storage.\n"
            "Supports Git (small results), S3 (large results), or hybrid"
        )
    )

    # Metadata and organization
    status: ExperimentStatus = Field(
        default=ExperimentStatus.DRAFT,
        description="Current experiment lifecycle status"
    )

    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Tags for organizing experiments.\n"
            "Examples: ['production', 'cv-parser', 'weekly', 'regression']"
        )
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Custom metadata key-value pairs.\n"
            "Examples: cost_per_run, expected_runtime, team, priority"
        )
    )

    # Timestamps (auto-managed)
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="When this experiment configuration was created"
    )

    updated_at: datetime = Field(
        default_factory=datetime.now,
        description="When this experiment configuration was last modified"
    )

    last_run_at: datetime | None = Field(
        default=None,
        description="When this experiment was last executed"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate experiment name follows conventions."""
        if not v:
            raise ValueError("Experiment name cannot be empty")

        if not v.islower():
            raise ValueError("Experiment name must be lowercase")

        if " " in v:
            raise ValueError("Experiment name cannot contain spaces (use hyphens)")

        if not all(c.isalnum() or c == "-" for c in v):
            raise ValueError("Experiment name can only contain lowercase letters, numbers, and hyphens")

        return v

    @field_validator("task")
    @classmethod
    def validate_task(cls, v: str) -> str:
        """Validate task name follows conventions."""
        if not v:
            return "general"  # Default value

        if not v.islower():
            raise ValueError("Task name must be lowercase")

        if " " in v:
            raise ValueError("Task name cannot contain spaces (use hyphens)")

        if not all(c.isalnum() or c == "-" for c in v):
            raise ValueError("Task name can only contain lowercase letters, numbers, and hyphens")

        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        """Ensure tags are lowercase and normalized."""
        return [tag.lower().strip() for tag in v]

    def get_experiment_dir(self, base_path: str = ".experiments") -> Path:
        """Get the experiment directory path."""
        return Path(base_path) / self.name

    def get_agent_task_dir(self, base_path: str = ".experiments") -> Path:
        """
        Get the experiment directory path organized by agent/task.

        Returns: Path like .experiments/{agent}/{task}/
        This is the recommended structure for S3 export compatibility.
        """
        return Path(base_path) / self.agent_schema_ref.name / self.task

    def get_config_path(self, base_path: str = ".experiments") -> Path:
        """Get the path to experiment.yaml file."""
        return self.get_experiment_dir(base_path) / "experiment.yaml"

    def get_readme_path(self, base_path: str = ".experiments") -> Path:
        """Get the path to README.md file."""
        return self.get_experiment_dir(base_path) / "README.md"

    def get_evaluator_filename(self) -> str:
        """
        Get the evaluator filename with task prefix.

        Returns: {agent_name}-{task}.yaml (e.g., siggy-risk-assessment.yaml)
        """
        return f"{self.agent_schema_ref.name}-{self.task}.yaml"

    def get_s3_export_path(self, bucket: str, version: str = "v0") -> str:
        """
        Get the S3 path for exporting this experiment.

        Returns: s3://{bucket}/{version}/datasets/calibration/experiments/{agent}/{task}/
        """
        return f"s3://{bucket}/{version}/datasets/calibration/experiments/{self.agent_schema_ref.name}/{self.task}"

    def to_yaml(self) -> str:
        """Export configuration as YAML string."""
        import yaml
        return yaml.dump(
            self.model_dump(mode="json", exclude_none=True),
            default_flow_style=False,
            sort_keys=False
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExperimentConfig":
        """Load configuration from YAML file."""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)

    def save(self, base_path: str = ".experiments") -> Path:
        """
        Save experiment configuration to YAML file.

        Creates directory structure if it doesn't exist.
        Updates `updated_at` timestamp.

        Returns:
            Path to saved experiment.yaml file
        """
        self.updated_at = datetime.now()

        config_path = self.get_config_path(base_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        with open(config_path, "w") as f:
            f.write(self.to_yaml())

        return config_path

    def generate_readme(self) -> str:
        """
        Generate README.md content for experiment.

        Includes:
        - Experiment description
        - Schema references
        - Dataset information
        - How to run
        - Results location
        """
        readme = f"""# {self.name}

{self.description}

## Configuration

**Status**: `{self.status.value}`
**Task**: `{self.task}`
**Tags**: {', '.join(f'`{tag}`' for tag in self.tags) if self.tags else 'None'}

## Agent Schema

- **Name**: `{self.agent_schema_ref.name}`
- **Version**: `{self.agent_schema_ref.version or 'latest'}`
- **Type**: `{self.agent_schema_ref.type}`

## Evaluator Schema

- **Name**: `{self.evaluator_schema_ref.name}`
- **File**: `{self.get_evaluator_filename()}`
- **Type**: `{self.evaluator_schema_ref.type}`

## Datasets

"""
        for name, dataset in self.datasets.items():
            readme += f"""### {name}

- **Location**: `{dataset.location.value}`
- **Path**: `{dataset.path}`
"""
            if dataset.description:
                readme += f"- **Description**: {dataset.description}\n"
            readme += "\n"

        readme += f"""## Results

- **Location**: `{self.results.location.value}`
- **Base Path**: `{self.results.base_path}`
- **Save Traces**: `{self.results.save_traces}`
- **Metrics File**: `{self.results.metrics_file}`

## How to Run

```bash
# Run this experiment
rem experiments run {self.name}

# Run with specific version
rem experiments run {self.name} --version experiments/{self.name}/v1.0.0
```

## Metadata

"""
        if self.metadata:
            for key, value in self.metadata.items():
                readme += f"- **{key}**: `{value}`\n"
        else:
            readme += "None\n"

        readme += f"""
## Timestamps

- **Created**: {self.created_at.isoformat()}
- **Updated**: {self.updated_at.isoformat()}
"""
        if self.last_run_at:
            readme += f"- **Last Run**: {self.last_run_at.isoformat()}\n"

        return readme

    def save_readme(self, base_path: str = ".experiments") -> Path:
        """Save auto-generated README.md file."""
        readme_path = self.get_readme_path(base_path)
        readme_path.parent.mkdir(parents=True, exist_ok=True)

        with open(readme_path, "w") as f:
            f.write(self.generate_readme())

        return readme_path


# Example configurations for reference
EXAMPLE_SMALL_EXPERIMENT = ExperimentConfig(
    name="hello-world-validation",
    description="Smoke test for hello-world agent responses",
    agent_schema_ref=SchemaReference(
        name="hello-world",
        version="schemas/hello-world/v1.0.0",
        type="agent"
    ),
    evaluator_schema_ref=SchemaReference(
        name="default",
        type="evaluator"
    ),
    datasets={
        "ground_truth": DatasetReference(
            location=DatasetLocation.GIT,
            path="datasets/ground_truth.csv",
            description="10 manually curated test cases"
        )
    },
    results=ResultsConfig(
        location=DatasetLocation.GIT,
        base_path="results/",
        save_traces=False,
        save_metrics_summary=True
    ),
    status=ExperimentStatus.READY,
    tags=["validation", "smoke-test"]
)

EXAMPLE_LARGE_EXPERIMENT = ExperimentConfig(
    name="cv-parser-production",
    description="Production CV parser evaluation with 10K resumes",
    agent_schema_ref=SchemaReference(
        name="cv-parser",
        version="schemas/cv-parser/v2.1.0",
        type="agent"
    ),
    evaluator_schema_ref=SchemaReference(
        name="default",
        type="evaluator"
    ),
    datasets={
        "ground_truth": DatasetReference(
            location=DatasetLocation.S3,
            path="s3://rem-prod/experiments/cv-parser-production/datasets/ground_truth.parquet",
            schema_path="datasets/schema.yaml",
            description="10,000 CV/resume pairs with ground truth extractions"
        )
    },
    results=ResultsConfig(
        location=DatasetLocation.HYBRID,
        base_path="s3://rem-prod/experiments/cv-parser-production/results/",
        save_traces=True,
        save_metrics_summary=True,
        metrics_file="metrics.json"
    ),
    metadata={
        "cost_per_run_usd": 5.25,
        "expected_runtime_minutes": 45,
        "team": "recruitment-ai",
        "priority": "high"
    },
    status=ExperimentStatus.READY,
    tags=["production", "cv-parser", "weekly"]
)
