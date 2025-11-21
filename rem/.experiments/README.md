# REM Experiments Directory

This directory contains experiment configurations for Phoenix evaluations. Experiments use a **hybrid storage model**: configurations and metadata live in Git, while large datasets and results live on S3.

## Directory Structure

```
.experiments/
├── README.md                                    # This file
├── {experiment-name}/                           # One directory per experiment
│   ├── experiment.yaml                          # Configuration (ExperimentConfig model)
│   ├── README.md                                # Auto-generated documentation
│   ├── datasets/                                # Optional: Small datasets (Git-tracked)
│   │   ├── ground_truth.csv                     # <1MB datasets suitable for Git
│   │   └── schema.yaml                          # Dataset schema documentation
│   └── results/                                 # Optional: Small results (Git-tracked)
│       ├── metrics.json                         # Summary metrics
│       └── latest-run.txt                       # Pointer to S3 results
│
└── hello-world-validation/                      # Example experiment
    ├── experiment.yaml
    ├── README.md
    └── datasets/
        └── ground_truth.csv
```

## Storage Convention: Git + S3 Hybrid

### What Goes in Git (`.experiments/`)

**DO store in Git**:
- ✅ `experiment.yaml` - Configuration and metadata
- ✅ `README.md` - Auto-generated documentation
- ✅ Small datasets (<1MB, <100 rows)
- ✅ Dataset schemas (YAML/JSON schema definitions)
- ✅ Metrics summaries (`metrics.json`)
- ✅ Run pointers (links to S3 results)

**DON'T store in Git**:
- ❌ Large datasets (>1MB or >1000 rows)
- ❌ Full Phoenix traces (can be GBs)
- ❌ Raw experiment outputs
- ❌ Temporary files

### What Goes on S3

**S3 Structure**:
```
s3://rem-experiments/
└── {experiment-name}/
    ├── datasets/                                # Source data
    │   ├── ground_truth.parquet                 # Large ground truth
    │   ├── test_cases.jsonl                     # Test inputs
    │   └── validation_set.parquet               # Validation data
    │
    └── results/                                 # Experiment outputs
        ├── run-2025-01-15-120000/               # Timestamped run
        │   ├── traces.jsonl                     # Phoenix traces
        │   ├── metrics.json                     # Full metrics
        │   └── metadata.json                    # Run metadata
        └── run-2025-01-16-093000/
            └── ...
```

**DO store on S3**:
- ✅ Large datasets (>1MB)
- ✅ Phoenix traces (full execution logs)
- ✅ Per-example results
- ✅ Multiple experiment runs
- ✅ Raw outputs and intermediate data

## Experiment Lifecycle

### 1. Create Experiment

```bash
# Create new experiment scaffold
rem experiments create my-experiment \
  --agent cv-parser \
  --evaluator default \
  --description "Test CV parsing accuracy on 100 samples"

# Generated structure:
.experiments/my-experiment/
├── experiment.yaml          # Configuration template
├── README.md                # Auto-generated docs
└── datasets/                # Empty directory for datasets
```

### 2. Configure Experiment

Edit `.experiments/my-experiment/experiment.yaml`:

```yaml
name: my-experiment
description: Test CV parsing accuracy on 100 samples
agent_schema_ref:
  name: cv-parser
  version: schemas/cv-parser/v2.1.0  # Pin specific version
  type: agent
evaluator_schema_ref:
  name: default
  type: evaluator
datasets:
  ground_truth:
    location: git  # Small dataset in Git
    path: datasets/ground_truth.csv
    format: csv
results:
  location: hybrid  # Metrics in Git, traces on S3
  base_path: s3://rem-experiments/my-experiment/results/
  save_traces: true
  save_metrics_summary: true
status: ready
tags: [validation, cv-parser]
```

### 3. Add Datasets

**Option A: Small dataset in Git**
```bash
# Add dataset to Git
cp ~/data/ground_truth.csv .experiments/my-experiment/datasets/
git add .experiments/my-experiment/datasets/ground_truth.csv
```

**Option B: Large dataset on S3**
```bash
# Upload to S3
aws s3 cp ~/data/large_ground_truth.parquet \
  s3://rem-experiments/my-experiment/datasets/ground_truth.parquet

# Update experiment.yaml to reference S3
vim .experiments/my-experiment/experiment.yaml
# Change location: s3
# Change path: s3://rem-experiments/my-experiment/datasets/ground_truth.parquet
```

### 4. Run Experiment

**Phoenix Connection Patterns**:

REM typically runs on Kubernetes alongside Phoenix in the observability namespace. Experiments are executed directly on the cluster where Phoenix is deployed.

```bash
# Production (on cluster) - RECOMMENDED
export PHOENIX_BASE_URL=http://phoenix-svc.observability.svc.cluster.local:6006
export PHOENIX_API_KEY=<your-key>
kubectl exec -it deployment/rem-api -- rem experiments run my-experiment

# Development (port-forward from cluster)
kubectl port-forward -n observability svc/phoenix-svc 6006:6006
export PHOENIX_API_KEY=<your-key>
rem experiments run my-experiment

# Local development (local Phoenix instance)
python -m phoenix.server.main serve
rem experiments run my-experiment

# Override Phoenix connection
rem experiments run my-experiment \
  --phoenix-url http://phoenix.example.com:6006 \
  --phoenix-api-key <key>
```

**Output**:
```
✓ Loaded configuration from .experiments/my-experiment/experiment.yaml
✓ Loaded agent schema: cv-parser v2.1.0
✓ Loaded evaluator schema: default
✓ Loaded dataset: ground_truth (100 rows)

Phoenix Connection:
  URL: http://phoenix-svc.observability.svc.cluster.local:6006
  API Key: Yes

⏳ Running experiment... (ETA: 5 minutes)
✓ Completed: 95/100 correct (95% accuracy)
✓ Saved results to: s3://rem-experiments/my-experiment/results/run-2025-01-15-120000/
✓ Saved metrics to: .experiments/my-experiment/results/metrics.json
```

### 5. Review Results

```bash
# View metrics summary (Git-tracked)
cat .experiments/my-experiment/results/metrics.json

# Open Phoenix UI
# Production: Access via ingress or port-forward
kubectl port-forward -n observability svc/phoenix-svc 6006:6006
open http://localhost:6006

# View S3 results
aws s3 ls s3://rem-experiments/my-experiment/results/run-2025-01-15-120000/
```

### 6. Commit to Git

```bash
# Commit configuration and small results
git add .experiments/my-experiment/
git commit -m "feat: Add my-experiment v1.0.0"

# Tag experiment version
git tag -a experiments/my-experiment/v1.0.0 \
  -m "my-experiment v1.0.0: Initial experiment configuration"

# Push to remote
git push origin main --tags
```

## Versioning Experiments

Experiments follow the same semantic versioning as schemas:

**Tag Format**: `experiments/{experiment-name}/vMAJOR.MINOR.PATCH`

**Examples**:
- `experiments/cv-parser-accuracy/v1.0.0` - Initial experiment
- `experiments/cv-parser-accuracy/v1.1.0` - Added new test cases
- `experiments/cv-parser-accuracy/v2.0.0` - Changed agent schema (breaking)

**Version Bumps**:
- **MAJOR**: Changed agent schema, evaluator, or dataset structure
- **MINOR**: Added test cases, updated configuration
- **PATCH**: Fixed typos, updated metadata

## Loading Versioned Experiments

```python
from rem.services.git import GitService
from rem.models.core.experiment import ExperimentConfig

git_svc = GitService()

# Load latest experiment
config = ExperimentConfig.from_yaml(".experiments/my-experiment/experiment.yaml")

# Load specific version (from Git)
git_svc.fs.read("git://rem/.experiments/my-experiment/experiment.yaml?ref=experiments/my-experiment/v1.0.0")
```

## Best Practices

### Dataset Size Guidelines

| Size | Storage | Example |
|------|---------|---------|
| <1MB | Git | Manual test cases, smoke tests |
| 1-100MB | S3 | Production validation sets |
| >100MB | S3 | Large-scale evaluations |

### Results Storage Guidelines

| Type | Storage | Example |
|------|---------|---------|
| Metrics summary | Git | metrics.json (accuracy, precision, recall) |
| Aggregated results | Git | Per-category breakdowns (<100KB) |
| Full traces | S3 | Phoenix traces (can be GBs) |
| Raw outputs | S3 | Individual example results |

### Naming Conventions

**Experiment Names**:
- ✅ `cv-parser-accuracy`
- ✅ `contract-analyzer-v2-validation`
- ✅ `hello-world-smoke-test`
- ❌ `CV_Parser_Accuracy` (uppercase)
- ❌ `cv parser accuracy` (spaces)
- ❌ `cv-parser-accuracy-v1` (version in name)

**Tags**:
- Use lowercase
- Organize by: domain, agent, frequency, priority
- Examples: `[production, cv-parser, weekly, p0]`

## Integration with Phoenix

Experiments integrate directly with Arize Phoenix:

```python
from rem.models.core.experiment import ExperimentConfig
from rem.services.phoenix import PhoenixClient

# Load experiment
config = ExperimentConfig.from_yaml(".experiments/my-experiment/experiment.yaml")

# Run in Phoenix
client = PhoenixClient()
results = client.run_experiment(
    name=config.name,
    agent_schema=config.agent_schema_ref,
    evaluator_schema=config.evaluator_schema_ref,
    dataset=config.datasets["ground_truth"],
    metadata=config.metadata
)

# Save results
config.save_results(results)
config.last_run_at = datetime.now()
config.save()
```

## CLI Commands

```bash
# Create new experiment
rem experiments create <name> --agent <agent> --evaluator <evaluator>

# List experiments
rem experiments list

# Show experiment details
rem experiments show <name>

# Run experiment
rem experiments run <name> [--version <tag>]

# Compare experiment versions
rem experiments diff <name> v1.0.0 v2.0.0

# Archive experiment
rem experiments archive <name>
```

## Example Experiments

### Small Experiment (Git-only)

```yaml
# .experiments/hello-world-validation/experiment.yaml
name: hello-world-validation
description: Smoke test for hello-world agent
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
    path: datasets/ground_truth.csv
    format: csv
results:
  location: git
  base_path: results/
  save_traces: false
  save_metrics_summary: true
status: ready
tags: [validation, smoke-test]
```

### Large Experiment (Hybrid)

```yaml
# .experiments/cv-parser-production/experiment.yaml
name: cv-parser-production
description: Weekly production evaluation with 10K CVs
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
    format: parquet
    schema_path: datasets/schema.yaml  # Schema in Git
results:
  location: hybrid
  base_path: s3://rem-prod/experiments/cv-parser-production/results/
  save_traces: true
  save_metrics_summary: true
  metrics_file: metrics.json
metadata:
  cost_per_run_usd: 5.25
  expected_runtime_minutes: 45
  team: recruitment-ai
  priority: high
status: ready
tags: [production, cv-parser, weekly]
```

## Troubleshooting

### "Dataset not found"
- Check `location` in experiment.yaml
- For `git`: Ensure file exists in `.experiments/{name}/datasets/`
- For `s3`: Verify S3 path and credentials

### "Schema version not found"
- Check `version` tag exists: `git tag | grep schemas/`
- Push tags if missing: `git push origin --tags`
- Use `version: null` for latest

### "Results storage failed"
- For `git`: Check write permissions
- For `s3`: Verify AWS credentials and bucket access
- For `hybrid`: Check both Git and S3 access

## Resources

- [ExperimentConfig Model](/src/rem/models/core/experiment.py)
- [GitService Documentation](/src/rem/services/git/README.md)
- [Phoenix Integration](/src/rem/services/phoenix/README.md)
- [Schema Versioning](/schemas/README.md)
