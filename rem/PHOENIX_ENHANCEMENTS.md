# Phoenix Evaluation Framework - Enhancement Summary

**Date**: 2025-11-21
**Status**: Phase 1 Complete (Documentation + Client Methods)

---

## Overview

This document summarizes the Phoenix evaluation framework enhancements migrated from Carrier and adapted for REM's unique requirements (engrams, multi-stage dreaming, etc.).

---

## Completed Work

### 1. Comprehensive Experiment Design Document ✅

**File**: `rem/src/rem/services/phoenix/EXPERIMENT_DESIGN.md`

**Contents**:
- **Design Principles**: Ground truth first, separation of concerns, iterative refinement
- **Experiment Lifecycle**: 6-stage process from problem definition to tracking
- **Data Sources**: SME examples, production data, engrams (REM-specific), hybrid approach
- **Naming Conventions**: Deterministic patterns to prevent dataset proliferation
- **Vibe-Eval Methodology**: Interactive test/fix cycle before formal Phoenix tracking
- **Phoenix Integration**: Formal experiment workflow after Vibe-Eval passes
- **Re-Evaluation Patterns**: Run new evaluators on existing agent outputs
- **Best Practices**: Golden set quality, evaluator design, progressive testing
- **Example Workflows**: 4 complete workflows with CLI commands

**Key Innovations**:
- **Engrams Integration**: Use REM's generated datasets for scalable testing
- **Three-Folder Structure**: `inputs/` (agent sees), `outputs/` (questions), `validation/` (ground truth)
- **Vibe-Eval First**: Interactive testing before formal Phoenix experiments
- **Hybrid Data Sources**: Combine SME + production + engrams for comprehensive coverage

### 2. Enhanced Phoenix Client Methods ✅

**File**: `rem/src/rem/services/phoenix/client.py`

**New Methods**:

#### `create_dataset_from_traces()`
```python
dataset = client.create_dataset_from_traces(
    name="rem-production-regression",
    project_name="rem-production",
    start_time=datetime.now() - timedelta(days=30),
    limit=500
)
```
**Use Case**: Create regression datasets from validated production traces.

#### `get_experiment()`
```python
exp_data = client.get_experiment("RXhwZXJpbWVudDoxMjM=")
# Returns: id, name, dataset_id, metadata, task_runs
```
**Use Case**: Retrieve experiment data for re-evaluation or export.

**Why These Methods**:
- `create_dataset_from_traces`: Enables production data → golden sets
- `get_experiment`: Required for experiment export and re-evaluation workflows

---

## Remaining Work

### Phase 2: CLI Command Enhancements

**Priority**: HIGH
**Estimated Effort**: 4-6 hours

#### 2.1 Enhanced Dataset Creation

**File**: `rem/src/rem/cli/commands/phoenix.py`

**Add Options to `dataset create`**:

```python
@dataset.command("create")
@click.argument("name", required=False)
@click.option("--task", help="Task identifier (auto-naming: {task}-{agent}-golden)")
@click.option("--agent", help="Agent identifier (for auto-naming)")
@click.option("--source", default="manual",
              help="Source: csv, traces, experiment, engrams, manual")
@click.option("--from-csv", type=click.Path(exists=True, path_type=Path))
@click.option("--from-experiment", help="Experiment ID to extract results from")
@click.option("--from-engrams", help="Engram quality level (high, medium, mature)")
@click.option("--project", help="Project name (for traces source)")
@click.option("--days", default=7, help="Lookback days (for traces)")
@click.option("--limit", default=100, help="Max examples")
@click.option("--description", help="Dataset description")
def dataset_create(...):
    """Create dataset from various sources."""
    # Implementation follows Carrier pattern (see phoenix_cmd.py:95-397)
```

**New Sources**:
1. `--source=traces`: From production Phoenix traces
2. `--source=experiment`: Extract (input, output, reference) from previous experiment
3. `--source=engrams`: From REM's generated engrams

**Auto-Naming**:
```bash
# Task + agent = auto-generate dataset name
rem eval dataset create --task rem-lookup --agent ask_rem --source csv ...
# Creates: "rem-lookup-ask_rem-golden"
```

#### 2.2 Enhanced Experiment Command

**Add Options to `experiment run`**:

```python
@experiment.command("run")
@click.argument("dataset_name", required=False)
@click.option("--task", help="Task identifier (for naming: {task}-{agent}-v{index})")
@click.option("--index", help="Experiment version (v1, v2, baseline)")
@click.option("--agent", help="Agent to run (ask_rem, etc.)")
@click.option("--evaluator", help="Evaluator schema(s), comma-separated")
@click.option("--model", help="Model for agent/evaluator")
@click.option("--experiment", dest="experiment_name", help="Explicit experiment name")
@click.option("--description", help="Experiment description")
@click.option("--metadata-filter", help="Filter dataset by metadata (difficulty=hard)")
@click.option("--limit", type=int, help="Limit examples for quick testing")
@click.option("--concurrency", type=int, help="Parallel workers (default: sequential)")
@click.option("--from-results", type=click.Path(exists=True),
              help="CSV with pre-existing agent outputs (skips agent execution)")
@click.option("--dry-run", is_flag=True, help="Test without saving")
def experiment_run(...):
    """Run evaluation experiment with enhanced features."""
    # Implementation follows Carrier pattern (see phoenix_cmd.py:691-1198)
```

**New Features**:
1. **Task/Index Naming**: `{task}-{agent}-v{index}` pattern
2. **Metadata Tracking**: Auto-store task, agent, index, model, timestamp
3. **Concurrency**: Parallel execution option
4. **From-Results Mode**: Re-evaluate without re-running agent
5. **Metadata Filtering**: Filter dataset examples by metadata
6. **Limit**: Quick testing on subset

**Example Usage**:
```bash
# Auto-naming with metadata
rem eval experiment run rem-lookup-ask_rem-golden \
  --task rem-lookup \
  --index v1 \
  --agent ask_rem \
  --evaluator ask_rem-correctness \
  --model claude-sonnet-4-5

# Creates experiment: "rem-lookup-ask_rem-v1"
# Metadata: {task: rem-lookup, agent: ask_rem, index: v1, model: claude-sonnet-4-5}
```

#### 2.3 New Commands

**Add These Commands**:

```python
@experiment.command("export")
@click.argument("experiment_id")
@click.option("--output", "-o", type=click.Path(), required=True)
@click.option("--task", help="Task ID (for metadata)")
@click.option("--agent", help="Agent ID (for metadata)")
def experiment_export(experiment_id, output, task, agent):
    """Export experiment results to CSV for re-evaluation.

    Format: input, agent_output, reference
    Use with --from-results for re-evaluation.
    """
    # See phoenix_cmd.py:1275-1406

@experiment.command("scaffold")
@click.argument("name")
@click.option("--path", default="experiments/", help="Base path for experiments")
@click.option("--agent", help="Agent being tested")
@click.option("--description", help="Experiment goal")
def experiment_scaffold(name, path, agent, description):
    """Create experiment directory structure.

    Creates:
    - inputs/ (agent CAN see)
    - outputs/ (test questions)
    - validation/ (ground truth, agent CANNOT see)
    """
    # See phoenix_cmd.py:1201-1272

@feedback_app.command("add")
@click.argument("target_type")  # span, trace, session
@click.argument("target_id")
@click.option("--name", "-n", required=True, help="Annotation name")
@click.option("--label", "-l", help="Label (correct, incorrect)")
@click.option("--score", "-s", type=float, help="Score (0.0-1.0)")
@click.option("--explanation", "-e", help="Explanation text")
@click.option("--annotator", default="HUMAN", help="HUMAN, LLM, or CODE")
def feedback_add(target_type, target_id, name, label, score, explanation, annotator):
    """Add feedback/annotation to span, trace, or session."""
    # See phoenix_cmd.py:1414-1498
```

### Phase 3: Engram Integration

**Priority**: MEDIUM
**Estimated Effort**: 2-3 hours

**File**: `rem/src/rem/cli/commands/engram.py` (new file)

**Commands Needed**:

```bash
# List available engrams
rem engram list \
  --quality high \
  --entity-type person,project \
  --limit 100

# Export engrams to Phoenix format
rem engram export rem-engrams-high-quality \
  --output engrams.csv \
  --format phoenix \
  --include-metadata

# Generate test cases from engrams
rem dreaming full \
  --user-id test-user \
  --tenant-id acme \
  --generate-test-cases \
  --quality-level 3
```

**Implementation Notes**:
- Query REM database for engrams at specific quality levels
- Export to Phoenix-compatible CSV format (input, reference, metadata)
- Filter by entity type, quality, tenant, user
- Include confidence scores and source metadata

### Phase 4: Helper Utilities

**Priority**: LOW
**Estimated Effort**: 1-2 hours

**File**: `rem/src/rem/cli/commands/phoenix_helpers.py` (new file)

**Helpers Needed**:
1. `validate_dataset_name()` - Check naming convention
2. `validate_experiment_dataset_name()` - For experiment-based datasets
3. `build_datasets_table()` - Rich table formatting
4. `scaffold_experiment()` - Create directory structure
5. `assign_auto_labels()` - Auto-label datasets

**See**: `carrier/cli/commands/phoenix/helpers.py` for reference implementation

---

## Implementation Guide

### Step 1: Update CLI Commands (4-6 hours)

```bash
# 1. Enhance dataset create command
# Add: --source (traces, experiment, engrams)
# Add: --task, --agent for auto-naming
# Add: --from-experiment, --from-engrams

# 2. Enhance experiment run command
# Add: --task, --index for auto-naming
# Add: --concurrency, --from-results, --metadata-filter, --limit
# Add: Metadata tracking (task, agent, index, model)

# 3. Add new commands
# - experiment export
# - experiment scaffold
# - feedback add

# 4. Test
rem eval dataset create --task rem-test --agent ask_rem --source csv --from-csv test.csv
rem eval experiment run rem-test-ask_rem-golden --task rem-test --index v1 --agent ask_rem
rem eval experiment export <exp-id> --output results.csv
```

### Step 2: Engram Integration (2-3 hours)

```bash
# 1. Create engram CLI module
# File: rem/src/rem/cli/commands/engram.py

# 2. Add commands:
# - rem engram list
# - rem engram export
# - rem engram quality-stats

# 3. Update dreaming worker
# Add: --generate-test-cases flag
# Add: Quality level tracking

# 4. Test
rem engram list --quality high --limit 10
rem engram export test --output test-engrams.csv --format phoenix
rem eval dataset create --source engrams --from-engrams test-engrams.csv
```

### Step 3: Documentation Updates (1 hour)

```bash
# Update files:
# - rem/src/rem/services/phoenix/README.md (add new commands)
# - rem/CLAUDE.md (update Phoenix section)
# - rem/src/rem/cli/README.md (add engram commands)
```

---

## Testing Checklist

### Dataset Creation
- [ ] Create from CSV (existing functionality)
- [ ] Create from traces (new)
- [ ] Create from experiment (new)
- [ ] Create from engrams (new)
- [ ] Auto-naming with task+agent (new)
- [ ] Manual naming (existing)

### Experiment Execution
- [ ] Run with agent only
- [ ] Run with evaluator only
- [ ] Run with agent + evaluator
- [ ] Auto-naming with task+index (new)
- [ ] Metadata tracking (new)
- [ ] Concurrency mode (new)
- [ ] From-results mode (new)
- [ ] Metadata filtering (new)
- [ ] Limit option (new)

### Export/Re-evaluation
- [ ] Export experiment results to CSV
- [ ] Re-evaluate with new evaluator using --from-results
- [ ] Compare evaluator versions

### Engrams
- [ ] List engrams by quality
- [ ] Export engrams to Phoenix format
- [ ] Create dataset from engrams
- [ ] Generate test cases via dreaming

---

## Reference Files

### Carrier Phoenix Implementation
- `carrier/src/carrier/cli/commands/phoenix/phoenix_cmd.py` - Complete CLI implementation
- `carrier/src/carrier/cli/commands/phoenix/helpers.py` - Helper utilities
- `carrier/docs/experiments/experiment-template.md` - Experiment structure template
- `carrier/docs/experiments/VELOYD-001/experiment-summary.md` - Completed experiment example

### REM Current Implementation
- `rem/src/rem/services/phoenix/client.py` - Phoenix client (enhanced with new methods)
- `rem/src/rem/cli/commands/phoenix.py` - CLI commands (needs enhancement)
- `rem/src/rem/services/phoenix/README.md` - Phoenix documentation
- `rem/src/rem/services/phoenix/EXPERIMENT_DESIGN.md` - New experiment design guide

---

## Key Differences from Carrier

### REM-Specific Features

1. **Engrams**: REM's unique generated datasets
   - Multi-stage dreaming (Stage 0-4)
   - Quality levels (raw, entities, moments, affinities, mature)
   - Tenant-scoped data
   - Confidence scoring

2. **REM Query Language**: LOOKUP, SEARCH, TRAVERSE, SQL
   - Carrier evaluates API mappers and CDA mappers
   - REM evaluates memory retrieval and graph queries

3. **Multi-Tenancy**: All experiments scoped to tenant_id
   - Carrier is single-tenant
   - REM requires tenant isolation

4. **Agent Context**: REM agents use case_ref and scratchpad
   - Case-based context management
   - Scratchpad for multi-turn reasoning
   - Parsed document access

### Shared Concepts

1. **Two-Phase Workflow**: Golden set → Evaluation
2. **Vibe-Eval**: Interactive testing before formal tracking
3. **Ground Truth Separation**: Agent never sees validation folder
4. **Deterministic Naming**: Prevent Phoenix dataset proliferation
5. **Re-Evaluation**: Test new evaluators on old agent outputs

---

## Next Actions

### Immediate (This Week)
1. ✅ Write experiment design document
2. ✅ Enhance Phoenix client with new methods
3. ⏳ Implement enhanced CLI commands (dataset create + experiment run)
4. ⏳ Add experiment export command
5. ⏳ Add experiment scaffold command

### Short-Term (Next 2 Weeks)
6. ⏳ Implement engram CLI commands
7. ⏳ Update dreaming worker for test case generation
8. ⏳ Write comprehensive tests
9. ⏳ Update documentation

### Long-Term (Next Month)
10. ⏳ Create example experiments (rem-lookup-001, rem-search-001)
11. ⏳ Build engram quality dashboard
12. ⏳ RAGAS integration (retrieval metrics)
13. ⏳ RRF experiments (Reciprocal Rank Fusion)

---

## Summary

### Completed ✅
- **Experiment Design Document**: Comprehensive 400+ line guide
- **Phoenix Client Methods**: `create_dataset_from_traces()`, `get_experiment()`
- **Design Patterns**: Vibe-Eval, three-folder structure, hybrid data sources

### In Progress ⏳
- **CLI Command Enhancements**: Dataset creation and experiment execution
- **Engram Integration**: List, export, quality tracking
- **Helper Utilities**: Naming validation, scaffolding, auto-labeling

### Benefits
- **Systematic Evaluation**: Track agent improvements over time
- **Scalable Testing**: Use engrams for diverse test coverage
- **Data-Driven Development**: Production traces + SME examples + engrams
- **Re-Evaluation Support**: Test new evaluators on old results
- **Clear Methodology**: Vibe-Eval → Phoenix → Iteration

---

## Questions & Decisions

### Q: Should engrams be stored in Phoenix or REM database?
**A**: Both. REM database is source of truth, Phoenix gets exports for experiments.

### Q: How to handle multi-tenancy in Phoenix?
**A**: Use metadata tags: `{"tenant_id": "acme-corp"}` in all datasets/experiments.

### Q: Should we use RAGAS library or implement metrics independently?
**A**: Implement independently (no dependency), inspired by RAGAS concepts. See evaluator schemas: `rem-retrieval-precision.yaml`, `rem-retrieval-recall.yaml`.

### Q: How often to generate engrams for testing?
**A**:
- Continuous: After each dreaming cycle (background)
- On-demand: Via `rem engram export` when creating datasets
- Scheduled: Weekly engram quality report

---

## Contact

For questions or implementation help:
- Review Carrier reference: `/Users/sirsh/code/tribe/carrier/src/carrier/cli/commands/phoenix/`
- Review REM implementation: `/Users/sirsh/code/mr_saoirse/remstack/rem/src/rem/services/phoenix/`
- Read experiment design guide: `rem/src/rem/services/phoenix/EXPERIMENT_DESIGN.md`
