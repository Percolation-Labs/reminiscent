# REMStack

Cloud-native REM (Reactive Event-driven Model) system for agentic AI workloads on AWS EKS.

## Stack Components

### Infrastructure
- AWS EKS cluster via Pulumi
- Karpenter for intelligent node provisioning
- Spot instances for stateless workloads
- On-demand instances for stateful workloads

### Platform
- ArgoCD for GitOps continuous delivery
- OpenTelemetry for distributed tracing
- CloudNativePG with PostgreSQL 18 and pgvector
- Arize Phoenix for LLM observability

### Application
- FastAPI server with MCP mounted at `/api/v1/mcp` (not separate)
- Multi-provider OAuth (Google, Microsoft Entra ID, custom)
- Pydantic AI for agent orchestration

**Important**: The MCP (Model Context Protocol) server is not a separate deployment.
It is mounted as part of the rem-api FastAPI application.

## Key Technologies

- Pydantic 2.0 models for all data structures
- OCI registries for all images and Helm charts
- External Secrets Operator for credential management
- IRSA for AWS permissions
- OpenTelemetry Protocol (OTLP) for observability

## Architecture Layers

```
application/     FastAPI with MCP, auth providers (rem-app namespace)
platform/        ArgoCD, OTel, CloudNativePG, Phoenix
infra/           Pulumi (EKS), Karpenter NodePools
```

## Namespace Structure

- **rem-app**: 2 deployments (rem-api, file-processor)
- **postgres**: PostgreSQL cluster (CloudNativePG)
- **observability**: OpenTelemetry collector (optional, future)

## Design Principles

- Stubs-first development
- Separation of concerns
- No backward compatibility hacks
- DRY code
- Immutable infrastructure
- Schema evolution via Pydantic models

## Deployment Strategy

- OCI Helm charts for platform components
- GitOps via ArgoCD
- Declarative Kubernetes manifests
- No mutable tags in production

## Database

- CloudNativePG operator
- PostgreSQL 18 with pgvector extension
- Vector embeddings for semantic search
- Streaming replication for HA
- No external RDS dependency

## Observability

- OpenTelemetry instrumentation
- Arize Phoenix for LLM tracing
- Structured JSON logging
- Correlation between metrics and traces

## Authentication

- JWT-based authentication
- Multiple OAuth providers
- Token refresh handling
- RBAC integration

## Development Workflow

1. Define Pydantic models
2. Create component stubs
3. Implement incrementally
4. Test with real workloads
5. Deploy via GitOps

## Security

- IRSA for AWS access
- External Secrets for credentials
- Pod Security Standards
- Network policies
- No hardcoded secrets

## Future

- Alembic migrations (when needed)
- Multi-cluster support
- Custom CRDs for REM agents
- Advanced RBAC policies
