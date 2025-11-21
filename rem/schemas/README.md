# REM Agent and Evaluator Schemas

This directory contains versioned agent and evaluator schemas for the REM system. Git is used for version control - schemas are tagged with semantic versions (v1.0.0, v2.0.0, etc.) and loaded via the GitProvider.

## Directory Structure

```
schemas/
├── agents/              # Agent schemas (one current version per agent)
│   ├── cv-parser.yaml
│   ├── contract-analyzer.yaml
│   ├── hello-world.yaml
│   ├── query.yaml
│   ├── rem.yaml
│   └── simple.yaml
│
└── evaluators/          # Evaluator schemas organized by agent name
    ├── hello-world/
    │   └── default.yaml
    └── rem/
        ├── faithfulness.yaml
        ├── lookup-correctness.yaml
        ├── retrieval-precision.yaml
        ├── retrieval-recall.yaml
        └── search-correctness.yaml
```

## Naming Conventions

### Agents (`agents/`)

- **Location**: `schemas/agents/{agent-name}.yaml`
- **Naming**: Use lowercase with hyphens (kebab-case)
- **No "agent" suffix**: Files should NOT include `-agent` suffix
- **No version in filename**: Git tags handle versioning (not `cv-parser-v1.yaml`)
- **One current version**: Only the latest version exists in the repo

**Examples**:
- ✅ `cv-parser.yaml`
- ✅ `contract-analyzer.yaml`
- ✅ `hello-world.yaml`
- ❌ `cv-parser-agent.yaml` (no `-agent` suffix)
- ❌ `cv-parser-v1.yaml` (no version in filename)

### Evaluators (`evaluators/`)

- **Location**: `schemas/evaluators/{agent-name}/{evaluator-name}.yaml`
- **Organization**: Group by agent name (the agent being evaluated)
- **Default evaluator**: Use `default.yaml` for the primary evaluator
- **Multiple evaluators**: Use descriptive names for specialized evaluators
- **No "agent" suffix**: Directory names should NOT include `-agent` suffix

**Examples**:
- ✅ `evaluators/hello-world/default.yaml`
- ✅ `evaluators/rem/lookup-correctness.yaml`
- ✅ `evaluators/rem/faithfulness.yaml`
- ❌ `evaluators/hello-world-agent/default.yaml` (no `-agent` suffix)
- ❌ `evaluators/rem-lookup-correctness.yaml` (must be in subdirectory)

## Git Versioning Workflow

### Creating a New Schema

1. Create the schema file following naming conventions
2. Commit the schema with a descriptive message
3. Tag the commit with semantic version

```bash
# Create schema
vim schemas/agents/my-new-agent.yaml

# Commit and tag
git add schemas/agents/my-new-agent.yaml
git commit -m "feat: Add my-new-agent v1.0.0"
git tag -a v1.0.0 -m "my-new-agent v1.0.0: Initial release"
git push origin main --tags
```

### Updating an Existing Schema

1. Modify the schema file
2. Commit the changes
3. Tag with incremented version

```bash
# Modify schema
vim schemas/agents/my-new-agent.yaml

# Commit and tag
git add schemas/agents/my-new-agent.yaml
git commit -m "feat: Add confidence scoring to my-new-agent v2.0.0"
git tag -a v2.0.0 -m "my-new-agent v2.0.0: Add confidence scoring"
git push origin main --tags
```

### Semantic Versioning Rules

Follow [semver](https://semver.org/) conventions:

- **MAJOR** (v2.0.0): Breaking changes (removed fields, changed types, different behavior)
- **MINOR** (v1.1.0): New features (added fields, new optional properties)
- **PATCH** (v1.0.1): Bug fixes (typos, documentation, no schema changes)

## Agent Schema Format

All agent schemas must follow this JSON Schema structure:

```yaml
---
type: object
description: |
  System prompt describing agent behavior and instructions.

  This is shown to the LLM as the system prompt.
  Provide clear, detailed instructions.

properties:
  answer:
    type: string
    description: The answer field

  confidence:
    type: number
    minimum: 0
    maximum: 1
    description: Confidence score (0.0-1.0)

required:
  - answer
  - confidence

json_schema_extra:
  fully_qualified_name: "rem.agents.MyAgent"
  version: "1.0.0"
  tags: [domain, category]

  # Optional: MCP tool configurations
  tools: []

  # Optional: MCP resource configurations
  resources: []

  # Optional: Multi-provider testing
  provider_configs:
    - provider_name: anthropic
      model_name: claude-sonnet-4-5-20250929
    - provider_name: openai
      model_name: gpt-4o

  # Optional: Fields to embed for semantic search
  embedding_fields:
    - field1
    - field2
    - nested.field3
```

## Evaluator Schema Format

Evaluators use the same JSON Schema structure as agents, but with evaluation-specific properties:

```yaml
---
type: object
description: |
  You are THE JUDGE evaluating an agent's response.

  Provide strict, objective evaluation without celebration.
  Grade based on correctness, completeness, and accuracy.

properties:
  correctness:
    type: number
    minimum: 0
    maximum: 1
    description: How correct is the response (0.0-1.0)

  completeness:
    type: number
    minimum: 0
    maximum: 1
    description: How complete is the response (0.0-1.0)

  explanation:
    type: string
    description: Detailed explanation of the evaluation

required:
  - correctness
  - completeness
  - explanation

json_schema_extra:
  fully_qualified_name: "rem.evaluators.MyEvaluator"
  version: "1.0.0"
  tags: [evaluation, correctness]
```

## Loading Schemas with GitService

### From Python Code

```python
from rem.services.git import GitService

git_svc = GitService()

# Load latest version
schema = git_svc.load_schema("cv-parser")

# Load specific version
schema = git_svc.load_schema("cv-parser", version="v2.0.0")

# List all versions
versions = git_svc.list_schema_versions("cv-parser")
# [{"tag": "v2.0.0", "version": (2,0,0), "commit": "abc123", ...}, ...]

# Compare versions
diff = git_svc.compare_schemas("cv-parser", "v1.0.0", "v2.0.0")

# Check for breaking changes
has_breaking = git_svc.has_breaking_changes("cv-parser", "v1.0.0", "v2.0.0")
```

### From CLI

```bash
# List schema versions
rem git schema list cv-parser

# Compare versions
rem git schema diff cv-parser v1.0.0 v2.0.0

# Load schema at version
rem git schema show cv-parser --version v2.0.0

# Sync repo (pull latest changes)
rem git sync
```

### From Kubernetes

Schemas are loaded from Git repositories using GitProvider with IRSA authentication:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rem-git-secret
type: Opaque
stringData:
  ssh: |
    -----BEGIN OPENSSH PRIVATE KEY-----
    ...
    -----END OPENSSH PRIVATE KEY-----
  known_hosts: |
    github.com ssh-rsa AAAA...

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rem-api
spec:
  template:
    spec:
      containers:
      - name: api
        env:
        - name: GIT__ENABLED
          value: "true"
        - name: GIT__DEFAULT_REPO_URL
          value: "git@github.com:org/repo.git"
        - name: GIT__SSH_KEY_PATH
          value: "/etc/git-secret/ssh"
        - name: GIT__KNOWN_HOSTS_PATH
          value: "/etc/git-secret/known_hosts"
        volumeMounts:
        - name: git-secret
          mountPath: /etc/git-secret
          readOnly: true
      volumes:
      - name: git-secret
        secret:
          secretName: rem-git-secret
          defaultMode: 0400
```

## Schema Types

### Core Agents

**hello-world**: Simple test agent for verification
**simple**: Basic conversational agent
**query**: REM query agent (LOOKUP, SEARCH, TRAVERSE)
**rem**: REM system expert agent

### Domain-Specific Agents

**cv-parser**: Extract structured data from resumes/CVs
**contract-analyzer**: Analyze legal contracts and agreements

### Evaluators

**default**: Primary evaluator for an agent
**lookup-correctness**: Evaluate LOOKUP query correctness
**search-correctness**: Evaluate SEARCH query correctness
**faithfulness**: Evaluate response faithfulness to context
**retrieval-precision**: Evaluate retrieval precision
**retrieval-recall**: Evaluate retrieval recall

## Adding New Agent Types

### Ontology Extractors

Ontology extractors are domain-specific agents that extract structured knowledge from files. They follow the same conventions as regular agents but include additional metadata:

```yaml
json_schema_extra:
  fully_qualified_name: "rem.agents.MyExtractor"
  version: "1.0.0"
  tags: [domain, ontology-extractor]  # Include 'ontology-extractor' tag

  # Multi-provider testing
  provider_configs:
    - provider_name: anthropic
      model_name: claude-sonnet-4-5-20250929
    - provider_name: openai
      model_name: gpt-4o

  # Fields to embed for semantic search
  embedding_fields:
    - candidate_name
    - skills
    - experience
```

**Extraction workflow**:
1. Files uploaded to S3
2. File processor extracts content
3. Dreaming worker finds matching OntologyConfig
4. Loads agent schema from database (or Git)
5. Runs extraction agent
6. Stores results in Ontology table with embeddings

## Testing

### Unit Tests

Test individual schemas for validity:

```python
from rem.agentic.factory import create_pydantic_ai_agent
from rem.services.git import GitService

git_svc = GitService()

# Load schema
schema = git_svc.load_schema("cv-parser", version="v1.0.0")

# Create agent
agent = create_pydantic_ai_agent(schema)

# Test execution
result = await agent.run("Extract from this CV: ...")
assert result.output.candidate_name == "John Doe"
```

### Integration Tests

Test with Git provider:

```python
from rem.services.git import GitService

git_svc = GitService()

# List versions
versions = git_svc.list_schema_versions("cv-parser")
assert len(versions) > 0
assert versions[0]["tag"] == "v2.0.0"

# Load and compare
v1_schema = git_svc.load_schema("cv-parser", version="v1.0.0")
v2_schema = git_svc.load_schema("cv-parser", version="v2.0.0")
diff = git_svc.compare_schemas("cv-parser", "v1.0.0", "v2.0.0")
assert "confidence_score" in diff  # New field added in v2.0.0
```

## Migration Guide

### Updating Tests After Refactor

After removing `-agent` suffix from filenames, update test files:

```python
# Before
schema = git_svc.load_schema("cv-parser-agent")
agent = create_pydantic_ai_agent("cv-parser-agent.yaml")

# After
schema = git_svc.load_schema("cv-parser")
agent = create_pydantic_ai_agent("cv-parser.yaml")
```

Search for references in tests:

```bash
# Find test files referencing old names
grep -r "cv-parser-agent" tests/
grep -r "hello-world-agent" tests/
grep -r "rem-agent" tests/

# Update references
sed -i 's/cv-parser-agent/cv-parser/g' tests/**/*.py
```

## Contributing

When adding new schemas:

1. **Follow naming conventions** (no `-agent` suffix, no version in filename)
2. **Include comprehensive docstrings** in the `description` field
3. **Add examples** in the system prompt
4. **Tag appropriately** (domain, category, ontology-extractor, etc.)
5. **Test thoroughly** before tagging
6. **Document changes** in git commit messages
7. **Use semantic versioning** for tags

## Experiments

Experiments are stored alongside schemas in the repository using the **`.experiments/` directory convention**. See [../.experiments/README.md](../.experiments/README.md) for complete documentation.

### Quick Start

```bash
# Create experiment
rem experiments create my-experiment \
  --agent cv-parser \
  --evaluator default \
  --description "Test CV parsing accuracy"

# Generated structure:
.experiments/my-experiment/
├── experiment.yaml          # Configuration (ExperimentConfig model)
├── README.md                # Auto-generated docs
└── datasets/                # Optional: small datasets

# Run experiment
# Note: REM typically runs on Kubernetes with Phoenix
# Production (on cluster):
export PHOENIX_BASE_URL=http://phoenix-svc.observability.svc.cluster.local:6006
export PHOENIX_API_KEY=<your-key>
kubectl exec -it deployment/rem-api -- rem experiments run my-experiment

# Development (port-forward):
kubectl port-forward -n observability svc/phoenix-svc 6006:6006
export PHOENIX_API_KEY=<your-key>
rem experiments run my-experiment

# Commit to Git
git add .experiments/my-experiment/
git commit -m "feat: Add my-experiment v1.0.0"
git tag -a experiments/my-experiment/v1.0.0 \
  -m "my-experiment v1.0.0: Initial experiment"
```

### Storage Convention: Git + S3 Hybrid

| Type | Git (`.experiments/`) | S3 (`s3://bucket/experiments/`) |
|------|----------------------|----------------------------------|
| Configuration | ✅ `experiment.yaml` | ❌ |
| Documentation | ✅ `README.md` | ❌ |
| Small datasets (<1MB) | ✅ `datasets/*.csv` | ❌ |
| Large datasets (>1MB) | ❌ | ✅ `datasets/*.parquet` |
| Metrics summary | ✅ `results/metrics.json` | ❌ |
| Full traces | ❌ | ✅ `results/run-*/traces.jsonl` |

### Experiment Versioning

Experiments follow semantic versioning like schemas:

- **Tag Format**: `experiments/{experiment-name}/vMAJOR.MINOR.PATCH`
- **Example**: `experiments/cv-parser-accuracy/v1.0.0`
- **GitProvider**: Load versioned experiments via GitService

```python
from rem.services.git import GitService
from rem.models.core.experiment import ExperimentConfig

git_svc = GitService()

# Load experiment at specific version
exp_yaml = git_svc.fs.read(
    "git://rem/.experiments/my-experiment/experiment.yaml?ref=experiments/my-experiment/v1.0.0"
)
config = ExperimentConfig(**exp_yaml)
```

## Resources

- [GitProvider Documentation](../src/rem/services/git/README.md)
- [Experiments Documentation](../.experiments/README.md)
- [ExperimentConfig Model](../src/rem/models/core/experiment.py)
- [Pydantic AI Documentation](https://ai.pydantic.dev/)
- [JSON Schema Reference](https://json-schema.org/)
- [Semantic Versioning](https://semver.org/)
- [REM Architecture](../CLAUDE.md)
