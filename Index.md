# REM Stack — Documentation Index

Last updated: 2025-12-06

This index groups repository README files by architectural area to help you quickly navigate documentation.

## Architecture & Overview

- [Repository overview: REMStack architecture, features, and quickstart.](./README.md)
- [Package-level documentation: architecture, features, and detailed quick start for the Python package.](./rem/README.md)

## Infrastructure & Manifests

- [Kubernetes manifests overview and deployment guidance (CDK + ArgoCD).](./manifests/README.md)
- [Infrastructure layer overview and local-first CDK guidance.](./manifests/infra/README.md)
- [Detailed AWS CDK EKS infrastructure docs (VPC, storage, ArgoCD, Karpenter).](./manifests/infra/cdk-eks/README.md)
- [rem-stack Kustomize deployment structure and component descriptions.](./manifests/application/rem-stack/README.md)
- [Kustomize-based application manifests and namespace/deployment layout.](./manifests/application/README.md)

## Platform & Addons

- [Platform-level deployment (ArgoCD apps, SSM parameters, fork instructions).](./manifests/platform/README.md)
- [Secrets management strategy: External Secrets Operator and AWS Parameter Store.](./manifests/platform/external-secrets/README.md)
- [KEDA autoscaling patterns and installation notes.](./manifests/platform/keda/README.md)
- [PostgreSQL extension packaging and custom image guidance.](./manifests/application/rem-stack/components/postgres/extensions/README.md)
- [Strategy for restoring PostgreSQL UNLOGGED tables after failover.](./manifests/application/rem-stack/components/unlogged-restorer/README.md)

## API, CLI & Developer UX

- [REM API docs: how to run the FastAPI server, CLI commands, and env vars.](./rem/src/rem/api/README.md)
- [CLI usage and agent testing (rem ask) with examples and flags.](./rem/src/rem/cli/README.md)
- [CLI subcommands reference (db schema, diff, apply) and workflows.](./rem/src/rem/cli/commands/README.md)

## Agents & Schemas

- [Agentic framework overview: JSON Schema agents, runtime and patterns.](./rem/src/rem/agentic/README.md)
- [Built-in agents (e.g., rem-query-agent) and usage examples.](./rem/src/rem/agentic/agents/README.md)
- [Agent and evaluator schema conventions and Git-based versioning.](./rem/src/rem/schemas/README.md)
- [Agent YAML schema organization and core/example agent descriptions.](./rem/src/rem/schemas/agents/README.md)

## Core Services

- [ContentService details: ingestion, parsing state, chunking and storage conventions.](./rem/src/rem/services/content/README.md)
- [PostgresService design: embeddings, KV store, upserts, and index management.](./rem/src/rem/services/postgres/README.md)
- [RemService query engine and REM query dialect (LOOKUP, FUZZY, SEARCH, TRAVERSE).](./rem/src/rem/services/rem/README.md)
- [File system abstraction for S3/local with format detection and Polars support.](./rem/src/rem/services/fs/README.md)
- [Git provider for syncing versioned agent schemas and experiments (semantic versions).](./rem/src/rem/services/git/README.md)
- [Phoenix evaluation framework: two-phase (golden set → automated eval) workflow.](./rem/src/rem/services/phoenix/README.md)
- [Dreaming services: user model updates, moment construction, affinity and orchestration.](./rem/src/rem/services/dreaming/README.md)
- [Audio processing: chunking and transcription pipeline with minimal deps.](./rem/src/rem/services/audio/README.md)
- [Session persistence, compression and reload for chat continuity.](./rem/src/rem/services/session/README.md)

## Workers & Orchestration

- [Worker orchestration and dreaming worker design principles.](./rem/src/rem/workers/README.md)

## Data, Tests & Examples

- [Testing strategy: unit vs integration tests, best practices and examples.](./rem/tests/README.md)
- [Integration test quick start and running examples.](./rem/tests/integration/README.md)
- [Integration test helpers: seed functions and utilities.](./rem/tests/integration/helpers/README.md)
- [Test data layout and sample datasets for tests.](./rem/tests/data/README.md)
- [Test audio files and regeneration instructions.](./rem/tests/data/audio/README.md)
- [Sample PDF documents used for content extraction tests.](./rem/tests/data/content-examples/pdf/README.md)
- [Seed data and scripts for loading sample data into tests/dev.](./rem/tests/data/seed/README.md)

## Utilities & Migrations

- [Alembic migration tooling and workflow (code-as-source-of-truth approach).](./rem/alembic/README.md)
- [Utility modules: SQL type mapping, embeddings helpers, and helper utilities.](./rem/src/rem/utils/README.md)

## Experiments & Evaluations

- [Experiment configuration and Git+S3 storage conventions for Phoenix evaluations.](./rem/.experiments/README.md)
- [Phoenix evaluation framework: two-phase (golden set → automated eval) workflow.](./rem/src/rem/services/phoenix/README.md)

## Local Development

- [Local development with Tilt and docker-compose (quick start, tiers).](./manifests/local/README.md)

---

If you'd like different grouping or fewer/more categories (for example: separate Storage, Observability, or Security), tell me which grouping you'd prefer and I will update `Index.md`.
