# Phoenix Integration Testing Guide

This guide provides step-by-step instructions for testing the complete REM experiments framework with Phoenix integration on the cluster.

## Prerequisites

1. **Kubernetes Access**:
   ```bash
   kubectl config current-context
   # Should show your cluster context

   kubectl get namespace observability
   # Should show observability namespace
   ```

2. **Phoenix Running**:
   ```bash
   kubectl get pods -n observability -l app=phoenix
   # Should show phoenix pods in Running state

   kubectl get svc -n observability phoenix-svc
   # Should show phoenix service
   ```

3. **REM API Deployed**:
   ```bash
   kubectl get pods -n rem-app -l app=rem-api
   # Should show rem-api pods in Running state
   ```

4. **API Keys Available**:
   ```bash
   # Check if API keys are configured in secrets
   kubectl get secret -n rem-app rem-api-secrets
   ```

## Test 1: Port-Forward Phoenix (Development Pattern)

Test local execution with cluster Phoenix via port-forward.

### Step 1.1: Port-Forward Phoenix Service

```bash
# Terminal 1: Keep this running
kubectl port-forward -n observability svc/phoenix-svc 6006:6006
```

### Step 1.2: Set Environment Variables

```bash
# Terminal 2: Set Phoenix connection
export PHOENIX_BASE_URL=http://localhost:6006
export PHOENIX_API_KEY=<your-phoenix-api-key-if-required>

# Set LLM API keys
export ANTHROPIC_API_KEY=<your-anthropic-key>
# OR
export OPENAI_API_KEY=<your-openai-key>
```

### Step 1.3: Create Test Experiment

```bash
cd /path/to/rem

# Create hello-world experiment
uv run rem experiments create hello-world-phoenix-test \
  --agent hello-world \
  --evaluator default \
  --description "Phoenix integration test with hello-world agent" \
  --dataset-location git \
  --results-location git \
  --tags "test,phoenix,hello-world"
```

**Expected Output**:
```
✓ Created experiment: hello-world-phoenix-test
  Configuration: .experiments/hello-world-phoenix-test/experiment.yaml
  Documentation: .experiments/hello-world-phoenix-test/README.md
  Datasets: .experiments/hello-world-phoenix-test/datasets
  Results: .experiments/hello-world-phoenix-test/results
```

### Step 1.4: Create Test Dataset

```bash
cat > .experiments/hello-world-phoenix-test/datasets/ground_truth.csv << 'EOF'
query,expected_greeting,difficulty
"Say hello","Hello!",easy
"Greet me","Hello!",easy
"Say hello to the world","Hello, World!",medium
"Hi there","Hello!",easy
"Good morning","Hello!",medium
EOF
```

### Step 1.5: Verify Configuration

```bash
# Show experiment details
uv run rem experiments show hello-world-phoenix-test

# List experiments
uv run rem experiments list
```

**Expected Output**:
```
Experiment: hello-world-phoenix-test
============================================================

Description: Phoenix integration test with hello-world agent
Status: draft
Tags: test, phoenix, hello-world

Agent Schema:
  Name: hello-world
  Version: latest

Evaluator Schema:
  Name: default

Datasets:
  ground_truth:
    Location: git
    Path: datasets/ground_truth.csv
    Format: csv

Results:
  Location: git
  Base Path: results/
  Save Traces: False
  Metrics File: metrics.json
```

### Step 1.6: Run Dry-Run Test

```bash
# Test without executing Phoenix
uv run rem experiments run hello-world-phoenix-test --dry-run
```

**Expected Output**:
```
✓ Loaded experiment: hello-world-phoenix-test

Experiment: hello-world-phoenix-test
  Agent: hello-world (version: latest)
  Evaluator: default
  Status: draft
  Mode: DRY RUN (no data will be saved)

Loading agent schema: hello-world (version: latest)
✓ Loaded agent schema from filesystem
Loading evaluator: default for agent hello-world
✓ Loaded evaluator schema
Loading dataset: ground_truth
✓ Loaded dataset: 5 examples

✓ Dry run complete (no data saved)
```

### Step 1.7: Run Full Experiment

```bash
# Run experiment with Phoenix
uv run rem experiments run hello-world-phoenix-test
```

**Expected Output**:
```
✓ Loaded experiment: hello-world-phoenix-test

Experiment: hello-world-phoenix-test
  Agent: hello-world (version: latest)
  Evaluator: default
  Status: draft

Loading agent schema: hello-world (version: latest)
✓ Loaded agent schema from filesystem
Loading evaluator: default for agent hello-world
✓ Loaded evaluator schema
Loading dataset: ground_truth
✓ Loaded dataset: 5 examples

Phoenix Connection:
  URL: http://localhost:6006
  API Key: No

⏳ Running experiment: hello-world-phoenix-test-20250121-140000
   This may take several minutes...

✓ Experiment complete!
  View results: http://localhost:6006/experiments/<experiment-id>

✓ Saved metrics summary: .experiments/hello-world-phoenix-test/results/metrics.json
```

### Step 1.8: Verify Results

```bash
# Check metrics file
cat .experiments/hello-world-phoenix-test/results/metrics.json

# Open Phoenix UI
open http://localhost:6006
```

**Expected metrics.json**:
```json
{
  "experiment_id": "<uuid>",
  "experiment_name": "hello-world-phoenix-test-20250121-140000",
  "agent": "hello-world",
  "evaluator": "default",
  "dataset_size": 5,
  "completed_at": "2025-01-21T14:00:00.000000",
  "phoenix_url": "http://localhost:6006/experiments/<experiment-id>",
  "task_runs": 5
}
```

### Step 1.9: Verify Phoenix UI

In Phoenix UI (http://localhost:6006):
1. Navigate to **Experiments** tab
2. Find experiment: `hello-world-phoenix-test-20250121-140000`
3. Verify:
   - ✅ 5 task runs (one per dataset example)
   - ✅ Agent outputs visible
   - ✅ Evaluator scores visible
   - ✅ Traces captured with OTEL spans
   - ✅ LLM token usage tracked
   - ✅ Latency metrics recorded

## Test 2: On-Cluster Execution (Production Pattern)

Test execution directly on the cluster where Phoenix is deployed.

### Step 2.1: Copy Experiment to Cluster

```bash
# Create configmap with experiment config
kubectl create configmap hello-world-experiment \
  --from-file=experiment.yaml=.experiments/hello-world-phoenix-test/experiment.yaml \
  --from-file=dataset.csv=.experiments/hello-world-phoenix-test/datasets/ground_truth.csv \
  -n rem-app \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Step 2.2: Run Experiment from rem-api Pod

```bash
# Set Phoenix connection for cluster DNS
kubectl exec -it deployment/rem-api -n rem-app -- bash -c '
export PHOENIX_BASE_URL=http://phoenix-svc.observability.svc.cluster.local:6006
export PHOENIX_API_KEY=${PHOENIX_API_KEY}  # From pod env
export ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}  # From pod env

# Run experiment
rem experiments run hello-world-phoenix-test
'
```

**Expected Output**:
```
Phoenix Connection:
  URL: http://phoenix-svc.observability.svc.cluster.local:6006
  API Key: Yes

⏳ Running experiment: hello-world-phoenix-test-20250121-150000
   This may take several minutes...

✓ Experiment complete!
  View results: http://phoenix-svc.observability.svc.cluster.local:6006/experiments/<experiment-id>

✓ Saved metrics summary: .experiments/hello-world-phoenix-test/results/metrics.json
```

### Step 2.3: Verify Cluster Execution

```bash
# Check rem-api logs
kubectl logs -n rem-app deployment/rem-api --tail=100 | grep experiment

# Port-forward Phoenix to view results
kubectl port-forward -n observability svc/phoenix-svc 6006:6006

# Open Phoenix UI
open http://localhost:6006
```

## Test 3: OTEL Trace Verification

Verify that OpenTelemetry traces are properly captured.

### Step 3.1: Enable OTEL in REM Settings

```bash
# Check if OTEL is enabled
kubectl get deployment rem-api -n rem-app -o yaml | grep -A5 OTEL

# Should see:
# - name: OTEL__ENABLED
#   value: "true"
# - name: OTEL__ENDPOINT
#   value: "http://otel-collector.observability.svc.cluster.local:4317"
```

### Step 3.2: Run Experiment with OTEL

```bash
# Run experiment (OTEL should be auto-enabled in cluster)
uv run rem experiments run hello-world-phoenix-test
```

### Step 3.3: Verify OTEL Traces in Phoenix

In Phoenix UI:
1. Navigate to **Traces** tab
2. Filter by project: `rem-agents` or `rem-experiments`
3. Find traces for experiment run
4. Verify trace structure:
   ```
   root span: experiment_run
   ├── span: load_agent_schema
   ├── span: load_evaluator_schema
   ├── span: load_dataset
   └── span: phoenix_experiment
       ├── span: task_run_0
       │   ├── span: agent.run (LLM call)
       │   └── span: evaluator.run (LLM call)
       ├── span: task_run_1
       │   ├── span: agent.run
       │   └── span: evaluator.run
       └── ...
   ```

### Step 3.4: Verify OTEL Metrics

Check OpenTelemetry Collector logs:
```bash
kubectl logs -n observability deployment/otel-collector | grep rem
```

Expected metrics:
- `rem.agent.invocations`
- `rem.agent.latency`
- `rem.agent.tokens`
- `rem.experiment.duration`
- `rem.experiment.task_runs`

## Test 4: Multiple Dataset Formats

Test S3 dataset loading and different formats.

### Step 4.1: Create S3 Dataset Experiment

```bash
uv run rem experiments create hello-world-s3-test \
  --agent hello-world \
  --evaluator default \
  --description "Test S3 dataset loading" \
  --dataset-location s3 \
  --results-location hybrid \
  --tags "test,s3"
```

### Step 4.2: Upload Dataset to S3

```bash
# Create Parquet dataset
python3 << 'EOF'
import pandas as pd

df = pd.DataFrame({
    'query': ['Say hello', 'Greet me', 'Hi there'],
    'expected_greeting': ['Hello!', 'Hello!', 'Hello!'],
    'difficulty': ['easy', 'easy', 'easy']
})

df.to_parquet('ground_truth.parquet', index=False)
EOF

# Upload to S3
aws s3 cp ground_truth.parquet s3://rem-experiments/hello-world-s3-test/datasets/ground_truth.parquet

# Update experiment config to reference S3
vim .experiments/hello-world-s3-test/experiment.yaml
# Change path to: s3://rem-experiments/hello-world-s3-test/datasets/ground_truth.parquet
# Change format to: parquet
```

### Step 4.3: Run S3 Experiment

```bash
uv run rem experiments run hello-world-s3-test
```

**Expected**: Should load dataset from S3 and run successfully.

## Test 5: Schema Versioning

Test loading specific schema versions from Git.

### Step 5.1: Tag Current Schema

```bash
# Tag hello-world schema
git add schemas/agents/examples/hello-world.yaml
git commit -m "feat: hello-world agent v1.0.0"
git tag -a schemas/hello-world/v1.0.0 -m "hello-world v1.0.0: Initial version"
git push origin main --tags
```

### Step 5.2: Create Versioned Experiment

```bash
# Edit experiment config to pin version
vim .experiments/hello-world-phoenix-test/experiment.yaml

# Change:
# agent_schema_ref:
#   name: hello-world
#   version: schemas/hello-world/v1.0.0  # Pin to v1.0.0
#   type: agent
```

### Step 5.3: Run with Pinned Version

```bash
# Should load specific version from Git
uv run rem experiments run hello-world-phoenix-test
```

## Test 6: Error Handling

Test graceful error handling.

### Step 6.1: Test Missing Dataset

```bash
# Create experiment without dataset
uv run rem experiments create hello-world-missing-data \
  --agent hello-world \
  --evaluator default

# Try to run without dataset
uv run rem experiments run hello-world-missing-data
```

**Expected**: Clear error message about missing dataset file.

### Step 6.2: Test Invalid Schema

```bash
# Create experiment with non-existent agent
uv run rem experiments create invalid-agent-test \
  --agent does-not-exist \
  --evaluator default

echo "query,expected" > .experiments/invalid-agent-test/datasets/ground_truth.csv
echo "test,test" >> .experiments/invalid-agent-test/datasets/ground_truth.csv

# Try to run
uv run rem experiments run invalid-agent-test
```

**Expected**: Clear error message about missing agent schema.

### Step 6.3: Test Phoenix Connection Failure

```bash
# Stop port-forward (if running)
# pkill -f "port-forward.*phoenix"

# Try to run without Phoenix
uv run rem experiments run hello-world-phoenix-test
```

**Expected**: Clear error message about Phoenix connection failure.

## Success Criteria

All tests should pass with:

✅ **Test 1 (Port-Forward)**:
- Experiment created successfully
- Dataset loaded from Git
- Agent schema loaded
- Evaluator schema loaded
- Phoenix experiment executed
- Results saved to Git
- Metrics JSON created
- Phoenix UI shows experiment

✅ **Test 2 (On-Cluster)**:
- Experiment runs from rem-api pod
- Cluster DNS resolution works
- API keys from secrets work
- Results accessible

✅ **Test 3 (OTEL)**:
- Traces captured in Phoenix
- Spans show LLM calls
- Metrics collected
- Latency tracked

✅ **Test 4 (S3 Datasets)**:
- S3 dataset loaded
- Parquet format works
- Hybrid results storage works

✅ **Test 5 (Versioning)**:
- Git schema versioning works
- Pinned versions load correctly

✅ **Test 6 (Error Handling)**:
- Missing dataset: clear error
- Invalid schema: clear error
- Phoenix down: clear error

## Cleanup

```bash
# Remove test experiments
rm -rf .experiments/hello-world-phoenix-test
rm -rf .experiments/hello-world-s3-test
rm -rf .experiments/invalid-agent-test

# Remove S3 data
aws s3 rm s3://rem-experiments/hello-world-s3-test/ --recursive

# Remove configmap
kubectl delete configmap hello-world-experiment -n rem-app
```

## Troubleshooting

### Phoenix Not Accessible

```bash
# Check Phoenix pods
kubectl get pods -n observability -l app=phoenix
kubectl logs -n observability deployment/phoenix --tail=50

# Check service
kubectl get svc -n observability phoenix-svc
kubectl describe svc -n observability phoenix-svc
```

### Agent Execution Fails

```bash
# Check API keys are set
echo $ANTHROPIC_API_KEY
echo $OPENAI_API_KEY

# Check agent schema exists
ls -la schemas/agents/examples/hello-world.yaml

# Check evaluator schema exists
ls -la schemas/evaluators/hello-world/default.yaml
```

### Dataset Loading Fails

```bash
# Check file exists
ls -la .experiments/hello-world-phoenix-test/datasets/ground_truth.csv

# Check format
head .experiments/hello-world-phoenix-test/datasets/ground_truth.csv

# For S3:
aws s3 ls s3://rem-experiments/hello-world-s3-test/datasets/
```

### OTEL Traces Missing

```bash
# Check OTEL collector
kubectl get pods -n observability -l app=otel-collector
kubectl logs -n observability deployment/otel-collector --tail=100

# Check REM OTEL settings
kubectl exec -it deployment/rem-api -n rem-app -- env | grep OTEL
```

## Next Steps

After successful testing:

1. **Commit experiment configs to Git**:
   ```bash
   git add .experiments/hello-world-phoenix-test/
   git commit -m "feat: Add hello-world Phoenix integration test"
   git tag -a experiments/hello-world-phoenix-test/v1.0.0 \
     -m "hello-world-phoenix-test v1.0.0: Initial test"
   git push origin main --tags
   ```

2. **Create production experiments**:
   - CV parser validation
   - Contract analyzer tests
   - REM query correctness

3. **Schedule automated runs**:
   - Create K8s CronJob for nightly experiments
   - Set up alerts for failing experiments
   - Dashboard for experiment metrics

4. **Optimize costs**:
   - Use Spot instances for experiment pods
   - Batch experiments together
   - Cache agent schemas
