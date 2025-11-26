# REM Experiment Design Guide

**Version**: 1.0
**Date**: 2025-11-21
**Status**: Production-Ready

A comprehensive guide to designing, executing, and iterating on LLM evaluation experiments for REM agents using Phoenix.

---

## Table of Contents

1. [Overview](#overview)
2. [Design Principles](#design-principles)
3. [Experiment Lifecycle](#experiment-lifecycle)
4. [Data Sources](#data-sources)
5. [Naming Conventions](#naming-conventions)
6. [Vibe-Eval Methodology](#vibe-eval-methodology)
7. [Phoenix Integration](#phoenix-integration)
8. [Re-Evaluation Patterns](#re-evaluation-patterns)
9. [Best Practices](#best-practices)
10. [Example Workflows](#example-workflows)

---

## Overview

REM's experiment framework combines **interactive testing** (Vibe-Eval) with **systematic tracking** (Phoenix) to build reliable agent evaluation pipelines.

### Key Concepts

**Engrams**: Generated datasets from REM's memory system (resources, entities, moments). These are synthetic but realistic test cases created by the dreaming worker.

**Ground Truth**: Reference answers from subject matter experts (SMEs), production data, or validated engrams. The agent NEVER sees ground truth during testing—it's the answer key for evaluation.

**Vibe-Eval**: Interactive test/fix cycle using CLI tools. Rapid iteration before committing to formal Phoenix experiments.

**Phoenix Experiments**: Automated evaluation runs tracked in Phoenix for systematic comparison over time.

### Three-Folder Structure

Every experiment follows a strict separation of concerns:

```
{EXPERIMENT-ID}/
├── inputs/              # What agent CAN see
│   ├── specs/           # API specs, documentation
│   ├── engrams/         # Generated test data
│   └── context/         # Additional context files
│
├── outputs/             # Questions to test agent
│   ├── questions.csv    # Test questions (created FROM ground truth)
│   └── questions.yaml   # Alternative format
│
└── validation/          # Ground truth (agent CANNOT see!)
    ├── golden-set/      # Reference answers
    ├── sme-examples/    # Expert-provided examples
    └── production/      # Real-world validated data
```

**Critical Rule**: The agent NEVER accesses the `validation/` folder. It must answer questions using only `inputs/`.

---

## Design Principles

### 1. Ground Truth First

**Start with the answer key**, not the questions.

```
Bad:  "Let's test if the agent can map APIs" → Write random questions
Good: "Here's how APIs should be mapped" → Test if agent matches SME examples
```

**Sources of Ground Truth**:
- SME examples (e.g., Postman collections, expert mappings)
- Production data (validated historical queries)
- Curated engrams (generated data that passed manual review)

### 2. Separation of Concerns

**What agent sees** vs **What we judge against** must be distinct.

```
inputs/     → Agent reads these to answer questions
validation/ → We read these to judge agent answers
outputs/    → Questions derived FROM validation (not shown to agent)
```

### 3. Iterative Refinement

**Vibe-Eval before Phoenix.**

1. Test agent interactively (CLI tools)
2. Fix broken prompts, tools, or schemas
3. Iterate until stable
4. THEN track with Phoenix experiments

**Why**: Prevents wasting Phoenix runs on obviously broken agents.

### 4. Deterministic Naming

**Predictable artifact names** prevent Phoenix dataset proliferation.

```
Dataset:    {task}-{agent}-golden     (e.g., rem-lookup-ask_rem-golden)
Experiment: {task}-{agent}-v{index}   (e.g., rem-lookup-ask_rem-v1)
Evaluator:  {agent}-{dimension}       (e.g., ask_rem-correctness)
```

### 5. Data-Driven Design

**Use data to build better LLMs**, not guesses.

- Generate engrams from real REM usage patterns
- Extract failure modes from production traces
- Create test cases targeting specific weaknesses
- Track improvements with controlled experiments

---

## Experiment Lifecycle

### Stage 0: Problem Definition

**What are you trying to improve?**

```
Example:
- Problem: LOOKUP queries return wrong entity types
- Hypothesis: Agent confuses person vs project entities
- Goal: Improve type classification accuracy from 75% to 95%
```

**Define Success Metrics:**
```
Metric                 | Baseline | Target
-----------------------|----------|-------
Type correctness       | 75%      | 95%
Label completeness     | 60%      | 90%
Hallucination rate     | 15%      | < 5%
```

### Stage 1: Ground Truth Collection

**Gather reference answers.**

**Option A: SME Examples**
```bash
# Expert provides examples
mkdir -p experiments/rem-001/validation/sme-examples/
cp postman-collection.json experiments/rem-001/validation/sme-examples/
```

**Option B: Production Data**
```bash
# Export validated production queries
rem experiments trace list --project rem-production --days 30 --output prod-queries.csv
# Manual review and curation
cp curated-queries.csv experiments/rem-001/validation/production/
```

**Option C: Curated Engrams**
```bash
# Generate engrams from REM data
rem dreaming full --user-id test-user  --generate-test-cases

# Review and select high-quality engrams
rem engram list --quality high --limit 100 --output engrams.csv
cp engrams.csv experiments/rem-001/validation/engrams/
```

### Stage 2: Test Question Design

**Create questions FROM ground truth.**

Read `validation/` folder and extract test questions WITHOUT revealing answers.

```csv
# outputs/questions.csv
input,reference
"LOOKUP person:sarah-chen","{""label"": ""sarah-chen"", ""type"": ""person"", ""properties"": {...}}"
"SEARCH for API design projects","{""entities"": [""api-design-v2"", ""rest-api-spec""], ""query_type"": ""semantic""}"
"TRAVERSE from sarah-chen to projects","{""paths"": [[""sarah-chen"", ""leads"", ""api-design-v2""]], ""depth"": 2}"
```

**Question Design Checklist:**
- [ ] Covers diverse difficulty levels (easy, medium, hard)
- [ ] Includes edge cases (ambiguous queries, missing data)
- [ ] Tests specific failure modes (identified from baseline)
- [ ] Reference answers are explicit and complete
- [ ] No leakage (questions don't reveal answers)

### Stage 3: Vibe-Eval (Interactive Testing)

**Test agent WITHOUT showing ground truth.**

```bash
# Setup case context (agent CAN see this)
export CASE_REF="rem-001"
rem process files experiments/$CASE_REF/inputs/specs/*.yaml --case-ref $CASE_REF

# Test agent interactively
rem ask ask_rem "LOOKUP person:sarah-chen" --case-ref $CASE_REF

# Compare output to ground truth (YOU are the judge)
# - Does output match validation/golden-set/sarah-chen.json?
# - Are all fields present?
# - Any hallucinations?
```

**Fix and Iterate:**
```bash
# If agent fails:
# 1. Check tool usage
cat .fs/cases/$CASE_REF/scratchpad/deltas/*.yaml

# 2. Fix agent schema (prompt, tools, output format)
vim schemas/agents/ask-rem.yaml

# 3. Re-test
rem ask ask_rem "LOOKUP person:sarah-chen" --case-ref $CASE_REF

# 4. Repeat until stable
```

**Exit Criteria for Vibe-Eval:**
- Agent correctly answers 8/10 diverse test questions
- No obvious hallucinations
- Tool usage is appropriate
- Output format is consistent

### Stage 4: Phoenix Formalization

**Create Phoenix artifacts AFTER Vibe-Eval passes.**

```bash
# 1. Create golden dataset
rem experiments dataset create rem-lookup-ask_rem-golden \
  --from-csv experiments/rem-001/outputs/questions.csv \
  --input-keys input \
  --output-keys reference \
  --description "Golden set for LOOKUP query evaluation"

# 2. Create evaluator schema
# Edit schemas/evaluators/ask_rem-correctness.yaml

# 3. Run baseline experiment
rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-lookup-ask_rem-v1 \
  --agent ask_rem \
  --evaluator ask_rem-correctness \
  --description "Baseline evaluation after Vibe-Eval"
```

### Stage 5: Iteration and Tracking

**Track improvements over time.**

```bash
# V1 baseline
rem experiments experiment run ... --experiment rem-lookup-ask_rem-v1

# V2 after prompt improvements
rem experiments experiment run ... --experiment rem-lookup-ask_rem-v2

# V3 after tool fixes
rem experiments experiment run ... --experiment rem-lookup-ask_rem-v3

# Compare in Phoenix UI
open http://localhost:6006
```

---

## Data Sources

### 1. SME Examples (Expert Knowledge)

**What**: Reference answers created by domain experts.

**Use Cases**:
- API mapper evaluation (Postman collections)
- CDA mapper evaluation (expert-provided mappings)
- Complex reasoning tasks (SME-validated outputs)

**Workflow**:
```bash
# SME provides examples
validation/sme-examples/postman-collection.json
validation/sme-examples/expert-mappings.yaml

# Extract test questions
# Question: "Show complete API request for POST /orders/create"
# Reference: <exact request from Postman>
```

**Pros**: High quality, domain-accurate
**Cons**: Manual effort, doesn't scale

### 2. Production Data (Real-World Validated)

**What**: Queries and responses from production that have been manually validated.

**Use Cases**:
- Regression testing (ensure new versions don't break existing functionality)
- Coverage testing (test against real user query patterns)
- Edge case discovery (find unusual queries users actually make)

**Workflow**:
```bash
# Export production traces
rem experiments trace list --project rem-production --days 30 --limit 1000 \
  --output prod-traces.csv

# Manual curation (validate correctness)
# Keep only queries with verified correct outputs

# Create test dataset
rem experiments dataset create rem-production-regression \
  --from-csv curated-prod-queries.csv \
  --input-keys query \
  --output-keys expected_output
```

**Pros**: Real-world coverage, user patterns
**Cons**: Requires validation, may contain errors

### 3. Engrams (Generated Test Data)

**What**: Synthetic datasets generated by REM's dreaming worker from memory system.

**Unique to REM**: Engrams are created through multi-stage "dreaming":
- **Stage 1**: Entity extraction from resources
- **Stage 2**: Moment generation (temporal narratives)
- **Stage 3**: Affinity matching (semantic clustering)
- **Stage 4**: Multiple dreaming cycles (rich interconnections)

**Use Cases**:
- Scale testing (generate thousands of test cases)
- Diverse scenario coverage (different entity types, query patterns)
- Controlled difficulty (easy vs hard examples)
- Stress testing (edge cases, missing data)

**Engram Quality Levels**:
```
Level 0 (Raw):      Resources only, minimal structure
Level 1 (Entities): Entities extracted, basic LOOKUP works
Level 2 (Moments):  Temporal narratives, time-based queries work
Level 3 (Affinities): Semantic clustering, SEARCH works well
Level 4 (Mature):   Multiple cycles, full query capabilities
```

**Workflow**:
```bash
# Generate engrams from REM data
rem dreaming full \
  --user-id test-user \
   \
  --generate-test-cases \
  --quality-level 3

# List available engrams
rem engram list \
  --quality high \
  --entity-type person,project \
  --limit 100

# Export to golden set
rem engram export rem-engrams-high-quality \
  --output engrams.csv \
  --format phoenix

# Create dataset
rem experiments dataset create rem-search-ask_rem-golden \
  --from-engrams engrams.csv \
  --input-keys query,context \
  --output-keys entities,relationships \
  --description "High-quality engrams for SEARCH evaluation"
```

**Pros**: Scalable, diverse, controllable difficulty
**Cons**: Synthetic (may not reflect real usage), requires curation

### 4. Hybrid Approach (Recommended)

**Combine all three sources** for comprehensive coverage:

```
Golden Set Composition:
├── 20% SME Examples     (high-quality, domain-accurate)
├── 30% Production Data  (real-world patterns)
└── 50% Curated Engrams  (scale, diversity, edge cases)
```

**Workflow**:
```bash
# 1. Collect SME examples
cp sme-examples/*.json validation/sme-examples/

# 2. Export production data
rem experiments trace list --project rem-prod --output prod.csv

# 3. Generate engrams
rem engram export rem-high-quality --output engrams.csv

# 4. Merge into single golden set
python scripts/merge_golden_sets.py \
  --sme validation/sme-examples/ \
  --production prod.csv \
  --engrams engrams.csv \
  --output golden-set.csv

# 5. Create Phoenix dataset
rem experiments dataset create rem-comprehensive-golden \
  --from-csv golden-set.csv \
  --input-keys query,context \
  --output-keys reference
```

---

## Naming Conventions

### Deterministic Naming Pattern

**Goal**: Prevent Phoenix dataset proliferation, enable traceability.

### Datasets

**Golden Sets (Ground Truth)**:
```
Pattern: {task}-{agent}-golden
Examples:
- rem-lookup-ask_rem-golden
- rem-search-ask_rem-golden
- rem-traverse-ask_rem-golden
```

**Agent Results (Experiment Outputs)**:
```
Pattern: {task}-{agent}-results
Examples:
- rem-lookup-ask_rem-results  (auto-created by Phoenix)
```

**Engram Datasets**:
```
Pattern: rem-engrams-{quality}-{entity-type}
Examples:
- rem-engrams-high-person
- rem-engrams-medium-project
- rem-engrams-mature-mixed
```

### Experiments

**Pattern**: `{task}-{agent}-v{index}`

```
Examples:
- rem-lookup-ask_rem-v1     (baseline)
- rem-lookup-ask_rem-v2     (after prompt improvements)
- rem-lookup-ask_rem-v3     (after tool fixes)
```

**Metadata** (auto-stored):
```json
{
  "task": "rem-lookup",
  "agent": "ask_rem",
  "index": "v1",
  "model": "claude-sonnet-4-5",
  "dataset_id": "RGF0YXNldDo...",
  "timestamp": "2025-11-21T10:30:00Z",
  "hypothesis": "Baseline evaluation after Vibe-Eval"
}
```

### Evaluators

**Pattern**: `{agent}-{dimension}`

```
Examples:
- ask_rem-correctness
- ask_rem-completeness
- ask_rem-faithfulness
- ask_rem-retrieval-precision
```

### Labels

**Standard Labels**:
```
- rem              (always added)
- golden-set       (for curated datasets)
- experiment       (for experiment runs)
- engram           (for generated datasets)
- production       (for production data)
- {task-name}      (e.g., rem-lookup, rem-search)
```

**Usage**:
```bash
# Automatic labeling
rem experiments dataset create rem-lookup-ask_rem-golden ...
# Labels: rem, golden-set, rem-lookup (auto-applied)

# Custom labels
rem experiments dataset create ... --labels production,high-priority
```

---

## Vibe-Eval Methodology

**Interactive test/fix cycle** using CLI tools before formal Phoenix tracking.

### Phase 0: Setup Case Context

**Parse documents to create case structure.**

```bash
export CASE_REF="rem-001"

# Parse specs/docs (agent CAN read these)
rem process files experiments/$CASE_REF/inputs/specs/*.yaml \
  --case-ref $CASE_REF \
  --wait

# Creates:
# .fs/cases/rem-001/
# ├── spec.yaml           # Original file
# ├── spec.yaml.md        # Parsed markdown (agent reads this)
# ├── spec.yaml.json      # Parse metadata
# └── scratchpad/         # Agent memory (created on first call)
```

### Phase 1: Interactive Testing

**Test agent with questions WITHOUT showing ground truth.**

```bash
# Question 1: LOOKUP query
rem ask ask_rem "LOOKUP person:sarah-chen" --case-ref $CASE_REF \
  --output experiments/$CASE_REF/agent-responses/q1.json

# Judge manually (compare to validation/golden-set/)
# - Does output match validation/sarah-chen.json?
# - Are all fields present (label, type, properties)?
# - Any hallucinated information?
# - Tool usage appropriate?

# Question 2: SEARCH query
rem ask ask_rem "SEARCH for API design projects" --case-ref $CASE_REF \
  --output experiments/$CASE_REF/agent-responses/q2.json

# Judge manually
# - Are returned entities relevant?
# - Is ranking quality good?
# - Any missing expected entities?
```

### Phase 2: Failure Analysis

**When agent fails, diagnose root cause.**

```bash
# Check tool usage
cat .fs/cases/$CASE_REF/scratchpad/deltas/*.yaml

# Did agent call tools?
# - If NO: Prompt unclear? Tool descriptions inadequate?
# - If YES: Are tool outputs correct? Is agent interpreting results correctly?

# Check agent reasoning
cat experiments/$CASE_REF/agent-responses/q1.json

# Look for:
# - Hallucinations (making up entities that don't exist)
# - Missing fields (incomplete output)
# - Type confusion (wrong entity type)
# - Tool misuse (calling wrong tools or with wrong parameters)
```

### Phase 3: Fix and Iterate

**Fix root cause and re-test.**

```bash
# Example: Fix prompt clarity
vim schemas/agents/ask-rem.yaml

# Add explicit instructions:
# "When answering LOOKUP queries:
# 1. ALWAYS call ask_rem tool with exact query
# 2. Return entity label, type, and ALL properties
# 3. NEVER invent entities not returned by tool"

# Re-test
rem ask ask_rem "LOOKUP person:sarah-chen" --case-ref $CASE_REF

# Compare to ground truth again
# - Fixed? Continue to next test
# - Still broken? Iterate again
```

### Phase 4: Coverage Testing

**Test diverse scenarios.**

```bash
# Test matrix
Tests:
├── Easy queries        (exact matches, common patterns)
├── Medium queries      (fuzzy matches, disambiguation)
├── Hard queries        (complex traversals, missing data)
└── Edge cases          (empty results, malformed queries)

# Run through all test questions
for question in experiments/$CASE_REF/outputs/questions.txt; do
  rem ask ask_rem "$question" --case-ref $CASE_REF
  # Judge each manually
done
```

### Phase 5: Exit Criteria

**When to move to Phoenix:**

- [ ] Agent answers 80%+ of test questions correctly
- [ ] No systematic hallucinations
- [ ] Tool usage is appropriate and consistent
- [ ] Output format is stable
- [ ] No obvious prompt issues
- [ ] Ready for automated tracking

**Document Findings**:
```markdown
# Vibe-Eval Summary (rem-001)

## Test Results
- Total questions: 25
- Correct: 21 (84%)
- Partial: 3 (12%)
- Wrong: 1 (4%)

## Key Findings
- ✅ LOOKUP queries work reliably
- ✅ Tool usage is appropriate
- ⚠️  TRAVERSE queries sometimes miss indirect paths
- ❌ Ambiguous entity names cause confusion

## Fixes Applied
1. Updated prompt to emphasize exact tool usage
2. Added examples for TRAVERSE queries
3. Improved entity disambiguation instructions

## Ready for Phoenix
Agent is stable enough for formal Phoenix tracking.
```

---

## Phoenix Integration

**After Vibe-Eval passes**, create Phoenix artifacts for systematic tracking.

### Step 1: Create Golden Dataset

```bash
rem experiments dataset create rem-lookup-ask_rem-golden \
  --from-csv experiments/rem-001/outputs/questions.csv \
  --input-keys input \
  --output-keys reference \
  --metadata-keys difficulty,query_type \
  --description "Golden set for LOOKUP queries (curated from SME + engrams)"
```

### Step 2: Create Evaluator Schema

Create `schemas/evaluators/ask_rem-correctness.yaml`:

```yaml
---
type: object
description: |
  Evaluate REM ask_rem agent responses for LOOKUP queries.

  You are an expert evaluator judging agent responses against ground truth.

  Scoring Rubric:
  - Correctness (0-1): Does output match expected entity?
  - Completeness (0-1): Are all required fields present?
  - Hallucination (0-1): Any invented information? (1 = none, 0 = severe)

  Pass threshold: Average score >= 0.75

properties:
  correctness:
    type: number
    minimum: 0.0
    maximum: 1.0
    description: |
      1.0: Entity label and type match exactly
      0.8: Minor label variation (e.g., "sarah-chen" vs "Sarah Chen")
      0.5: Correct type, wrong label
      0.2: Wrong type, partial info
      0.0: Completely wrong or missing

  completeness:
    type: number
    minimum: 0.0
    maximum: 1.0
    description: |
      1.0: All expected fields present (label, type, properties)
      0.7: Missing optional fields only
      0.5: Missing required fields
      0.0: Minimal information returned

  hallucination_score:
    type: number
    minimum: 0.0
    maximum: 1.0
    description: |
      1.0: No invented information
      0.8: Minor embellishments
      0.5: Some invented fields
      0.2: Significant hallucination
      0.0: Entirely made up

  pass:
    type: boolean
    description: True if average score >= 0.75

  explanation:
    type: string
    description: Detailed explanation of scoring

required:
  - correctness
  - completeness
  - hallucination_score
  - pass
  - explanation

json_schema_extra:
  evaluator_type: llm-as-judge
  provider_configs:
    - provider_name: openai
      model_name: gpt-4.1
  input_schema:
    query: string (the LOOKUP query)
  output_schema:
    label: string (entity label returned)
    type: string (entity type)
    properties: dict (entity properties)
  expected_schema:
    label: string (expected entity label)
    type: string (expected entity type)
    properties: dict (expected properties)
```

### Step 3: Run Baseline Experiment

```bash
rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-lookup-ask_rem-v1 \
  --agent ask_rem \
  --evaluator ask_rem-correctness \
  --model claude-sonnet-4-5 \
  --description "Baseline evaluation after Vibe-Eval (v1.0)"
```

### Step 4: View Results

```bash
# Open Phoenix UI
open http://localhost:6006

# Navigate to experiments
# Compare metrics:
# - Correctness: 0.87 (target: >= 0.85)
# - Completeness: 0.79 (target: >= 0.80)
# - Hallucination: 0.92 (target: >= 0.90)
# - Pass rate: 84% (21/25)
```

### Step 5: Iterate

```bash
# After improvements (v2)
rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-lookup-ask_rem-v2 \
  --agent ask_rem \
  --evaluator ask_rem-correctness \
  --description "After prompt improvements"

# Compare v1 vs v2 in Phoenix UI
# - Correctness: 0.87 → 0.94 (+7%)
# - Completeness: 0.79 → 0.88 (+9%)
# - Pass rate: 84% → 92% (+8%)
```

---

## Re-Evaluation Patterns

**Run evaluators on existing agent outputs** without re-executing agents.

### Use Case: Test New Evaluator

**Scenario**: You created a new evaluator and want to test it on previous experiment outputs.

```bash
# Step 1: Export previous experiment results
rem experiments experiment export rem-lookup-ask_rem-v1 \
  --output /tmp/v1-results.csv

# Step 2: Run new evaluator on exported results
rem experiments experiment run \
  --from-results /tmp/v1-results.csv \
  --experiment rem-lookup-ask_rem-v1-reeval \
  --evaluator ask_rem-completeness-v2 \
  --description "Re-evaluate v1 with improved completeness evaluator"
```

### Use Case: Compare Evaluator Versions

**Scenario**: You improved an evaluator and want to compare scores on same agent outputs.

```bash
# Baseline (old evaluator)
rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-eval-comparison-v1 \
  --agent ask_rem \
  --evaluator ask_rem-correctness-v1

# Export results
rem experiments experiment export rem-eval-comparison-v1 \
  --output /tmp/agent-outputs.csv

# Re-evaluate with new evaluator
rem experiments experiment run \
  --from-results /tmp/agent-outputs.csv \
  --experiment rem-eval-comparison-v2 \
  --evaluator ask_rem-correctness-v2

# Compare in Phoenix UI
# - v1 evaluator: 87% pass rate
# - v2 evaluator: 92% pass rate
# - Conclusion: v2 evaluator is more lenient (or v1 was too strict)
```

### Use Case: Multi-Evaluator Analysis

**Scenario**: Run multiple evaluators on same agent outputs to analyze different dimensions.

```bash
# Run agent once
rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-multi-eval-baseline \
  --agent ask_rem

# Export results
rem experiments experiment export rem-multi-eval-baseline \
  --output /tmp/baseline.csv

# Re-evaluate with different evaluators
rem experiments experiment run --from-results /tmp/baseline.csv \
  --experiment rem-correctness-eval \
  --evaluator ask_rem-correctness

rem experiments experiment run --from-results /tmp/baseline.csv \
  --experiment rem-completeness-eval \
  --evaluator ask_rem-completeness

rem experiments experiment run --from-results /tmp/baseline.csv \
  --experiment rem-faithfulness-eval \
  --evaluator ask_rem-faithfulness

# Compare dimension scores in Phoenix UI
```

---

## Best Practices

### Golden Set Quality

**Diversity**:
```
✅ Mix of easy, medium, hard examples (30/50/20 split)
✅ Diverse entity types (person, project, document, etc.)
✅ Different query patterns (exact, fuzzy, semantic)
✅ Edge cases (empty results, ambiguous, malformed)

❌ All easy examples
❌ Single entity type
❌ Repetitive queries
❌ No edge cases
```

**Metadata**:
```csv
input,reference,difficulty,query_type,entity_type
"LOOKUP person:sarah-chen","...",easy,exact,person
"SEARCH API projects","...",medium,semantic,project
"TRAVERSE sarah-chen depth=3","...",hard,graph,mixed
```

**Versioning**:
```bash
# Version golden sets when making significant changes
rem experiments dataset create rem-lookup-golden-v1 ...  # Initial
rem experiments dataset create rem-lookup-golden-v2 ...  # Added edge cases
rem experiments dataset create rem-lookup-golden-v3 ...  # Production failures
```

### Evaluator Design

**Multi-Dimensional Scoring**:
```yaml
# Good: Multiple dimensions
properties:
  correctness: {type: number}
  completeness: {type: number}
  relevance: {type: number}
  hallucination_score: {type: number}

# Bad: Single score
properties:
  score: {type: number}
```

**Clear Rubrics**:
```yaml
# Good: Explicit scoring criteria
description: |
  1.0: Perfect match
  0.8: Minor variations
  0.5: Partially correct
  0.2: Mostly wrong
  0.0: Completely wrong

# Bad: Vague
description: "Score the output"
```

**Strict Grading**:
```yaml
# Good: Catches subtle issues
hallucination_score: 1.0 only if NO invented information

# Bad: Too lenient
hallucination_score: 0.8 if "mostly accurate"
```

### Experiment Metadata

**Track Important Context**:
```python
metadata = {
    "task": "rem-lookup",
    "agent": "ask_rem",
    "index": "v3",
    "model": "claude-sonnet-4-5",
    "prompt_version": "2025-11-21",
    "hypothesis": "Fixed entity type confusion",
    "baseline_score": 0.87,
    "target_score": 0.92,
    "changed_files": ["schemas/agents/ask-rem.yaml"],
}
```

### Progressive Testing

**Start Small, Scale Up**:
```
Phase 1: Vibe-Eval (5-10 examples, interactive)
Phase 2: Phoenix Baseline (25 examples, full evaluators)
Phase 3: Comprehensive (100+ examples, all dimensions)
Phase 4: Production (1000+ examples, continuous)
```

---

## Example Workflows

### Workflow 1: Testing LOOKUP Query Agent

**Goal**: Ensure LOOKUP queries return correct entities with complete information.

```bash
# 1. Collect ground truth
mkdir -p experiments/rem-lookup-001/validation/golden-set/
cp sme-examples/entities/*.json experiments/rem-lookup-001/validation/golden-set/

# 2. Create test questions
cat > experiments/rem-lookup-001/outputs/questions.csv <<EOF
input,reference
"LOOKUP person:sarah-chen","{""label"": ""sarah-chen"", ""type"": ""person""}"
"LOOKUP project:api-design-v2","{""label"": ""api-design-v2"", ""type"": ""project""}"
EOF

# 3. Vibe-Eval
export CASE_REF="rem-lookup-001"
rem ask ask_rem "LOOKUP person:sarah-chen" --case-ref $CASE_REF
# Judge: Does it match validation/golden-set/sarah-chen.json?

# 4. Phoenix
rem experiments dataset create rem-lookup-ask_rem-golden \
  --from-csv experiments/rem-lookup-001/outputs/questions.csv \
  --input-keys input --output-keys reference

rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-lookup-ask_rem-v1 \
  --agent ask_rem \
  --evaluator ask_rem-correctness
```

### Workflow 2: Testing with Engrams

**Goal**: Scale testing using generated engrams.

```bash
# 1. Generate high-quality engrams
rem dreaming full  --generate-test-cases --quality-level 4

# 2. Export engrams
rem engram export rem-engrams-mature-mixed --output engrams.csv --format phoenix

# 3. Create dataset
rem experiments dataset create rem-search-ask_rem-golden \
  --from-engrams engrams.csv \
  --input-keys query,context \
  --output-keys entities,relationships

# 4. Run experiment
rem experiments experiment run rem-search-ask_rem-golden \
  --experiment rem-search-ask_rem-v1 \
  --agent ask_rem \
  --evaluator ask_rem-retrieval-precision,ask_rem-retrieval-recall
```

### Workflow 3: Re-Evaluation After Prompt Change

**Goal**: Test if prompt improvements increased accuracy without re-running agent.

```bash
# 1. Baseline experiment (already run)
# rem experiments experiment run ... --experiment rem-v1

# 2. Export baseline results
rem experiments experiment export rem-lookup-ask_rem-v1 --output /tmp/v1.csv

# 3. Update prompt
vim schemas/agents/ask-rem.yaml

# 4. Test new prompt via Vibe-Eval (spot check)
rem ask ask_rem "LOOKUP person:sarah-chen" --case-ref rem-test

# 5. Run full experiment with new prompt
rem experiments experiment run rem-lookup-ask_rem-golden \
  --experiment rem-lookup-ask_rem-v2 \
  --agent ask_rem \
  --evaluator ask_rem-correctness

# 6. Compare v1 vs v2 in Phoenix UI
```

### Workflow 4: Hybrid Golden Set (SME + Engrams + Production)

**Goal**: Comprehensive evaluation combining all data sources.

```bash
# 1. Collect SME examples
cp sme-postman-collection.json validation/sme-examples/

# 2. Export production data
rem experiments trace list --project rem-prod --days 30 --output prod.csv

# 3. Generate engrams
rem engram export rem-high-quality --output engrams.csv

# 4. Merge sources
python scripts/merge_golden_sets.py \
  --sme validation/sme-examples/ \
  --production prod.csv \
  --engrams engrams.csv \
  --weights 0.2,0.3,0.5 \
  --output golden-hybrid.csv

# 5. Create Phoenix dataset
rem experiments dataset create rem-comprehensive-golden \
  --from-csv golden-hybrid.csv \
  --input-keys query,context \
  --output-keys reference \
  --metadata-keys source,difficulty

# 6. Run experiment
rem experiments experiment run rem-comprehensive-golden \
  --experiment rem-comprehensive-v1 \
  --agent ask_rem \
  --evaluator ask_rem-correctness,ask_rem-completeness,ask_rem-faithfulness
```

---

## Summary

REM's experiment design framework provides:

✅ **Clear methodology**: Vibe-Eval → Phoenix → Iteration
✅ **Multiple data sources**: SME + Production + Engrams
✅ **Deterministic naming**: Prevent Phoenix proliferation
✅ **Re-evaluation support**: Test new evaluators on old results
✅ **Data-driven design**: Use real patterns to build better agents
✅ **Systematic tracking**: Phoenix integration for long-term analysis

**Key Takeaways**:

1. **Ground truth first**: Start with the answer key, not questions
2. **Separation of concerns**: Agent NEVER sees validation folder
3. **Vibe-Eval before Phoenix**: Interactive testing catches issues early
4. **Use engrams for scale**: Generated data covers diverse scenarios
5. **Track everything**: Metadata enables comparison over time

**Next Steps**:

1. Define your first experiment (problem, metrics, hypothesis)
2. Collect ground truth (SME + production + engrams)
3. Run Vibe-Eval until stable
4. Formalize with Phoenix experiments
5. Iterate and track improvements

---

## Related Documentation

- [Phoenix README](./README.md) - Phoenix service overview
- [CLAUDE.md](../../../CLAUDE.md) - REM architecture
- [Evaluator Schemas](../../../schemas/evaluators/) - Pre-built evaluators
- [Dreaming Worker](../../workers/dreaming.py) - Engram generation
