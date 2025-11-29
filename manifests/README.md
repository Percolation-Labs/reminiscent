# REM Kubernetes Manifests

Kubernetes deployment manifests for the REM platform. These manifests are bundled with `remdb` releases and can be deployed using the `rem` CLI.

## Overview

REM uses a two-cluster architecture:

| Cluster | Purpose | Status |
|---------|---------|--------|
| **Application Cluster** | Runs REM workloads (API, workers, PostgreSQL) | ✅ Ready |
| **Management Cluster** | Runs ArgoCD, manages application clusters | 🚧 WIP |

Currently, the application cluster includes ArgoCD for self-management. The management cluster pattern (hub-spoke) is planned for multi-cluster deployments.

## Quick Start

### Using CDK (Recommended)

CDK deploys everything: EKS cluster, ArgoCD, SSM parameters, and all addons.

```bash
# 1. Configure .env file
cd manifests/infra/cdk-eks
cp .env.example .env
# Edit .env with your AWS account, API keys, etc.

# Required in .env:
#   AWS_ACCOUNT_ID=your-account-id
#   AWS_PROFILE=rem
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=sk-proj-...

# 2. Deploy infrastructure (includes ArgoCD + SSM params)
npm install
npx cdk deploy --all --profile rem

# 3. Configure kubectl
aws eks update-kubeconfig --name <cluster-name> --region us-east-1 --profile rem

# 4. Deploy ArgoCD applications
rem cluster apply
```

**That's it!** CDK creates:
- EKS cluster with Karpenter autoscaling
- ArgoCD (optional, disable with `ENABLE_ARGOCD=false`)
- SSM parameters for secrets (optional, disable with `ENABLE_SSM_PARAMETERS=false`)
- All platform addons (ALB controller, External Secrets, etc.)

### Destroy and Recreate

To tear down and rebuild the entire stack:

```bash
# 1. Delete ArgoCD applications first
kubectl delete application --all -n argocd

# 2. Destroy CDK stack
cd manifests/infra/cdk-eks
npx cdk destroy --all --profile rem

# 3. Recreate (follow Quick Start steps 4-9)
```

## Manifest Distribution

Manifests are versioned and distributed in two ways:

### 1. Bundled with rem releases

When you run `rem cluster init`, manifests are automatically downloaded from GitHub releases:

```bash
# Download latest manifests
rem cluster init -y

# Download specific version
rem cluster init --manifest-version v0.5.0 -y
```

The tarball (`manifests.tar.gz`) is attached to each GitHub release.

### 2. In this repository (for development)

For testing and development, manifests live in this repo. Changes here are bundled into releases.

## Directory Structure

```
manifests/
├── README.md                # This file
├── TROUBLESHOOTING.md       # Deployment guide and common issues
├── cluster-config.yaml      # Deployment configuration template
│
├── infra/                   # Infrastructure layer
│   └── cdk-eks/            # AWS CDK for EKS + supporting resources
│
├── platform/                # Platform services (deployed via ArgoCD)
│   ├── argocd/             # ArgoCD app-of-apps pattern
│   │   └── applications/   # Platform operator applications
│   ├── cert-manager/       # Certificate management
│   ├── external-secrets/   # AWS SSM integration
│   └── ...                 # Other platform components
│
├── application/             # Application workloads
│   └── rem-stack/          # REM application stack
│       ├── components/     # Base components (API, workers, postgres)
│       └── overlays/       # Environment configs (staging, prod)
│
└── local/                   # Local development (docker-compose)
```

## CLI Commands Reference

| Command | Purpose |
|---------|---------|
| `rem cluster init` | Initialize config and download manifests |
| `rem cluster validate` | Check prerequisites (tools, AWS, K8s, ArgoCD) |
| `rem cluster validate --pre-argocd` | Check only pre-deployment prerequisites |
| `rem cluster generate` | Regenerate manifests from config |
| `rem cluster apply` | Deploy ArgoCD applications |
| `rem cluster apply --dry-run` | Preview deployment |

**Note:** SSM parameters are now created by CDK automatically. The `rem cluster setup-ssm` command is still available for manual use if needed.

## Configuration

### cluster-config.yaml

The main configuration file for your deployment:

```yaml
project:
  name: rem
  namespace: rem
  environment: staging

git:
  repoURL: https://github.com/YOUR_ORG/YOUR_REPO.git
  targetRevision: main

aws:
  region: us-east-1
  ssmPrefix: /rem
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `GITHUB_REPO_URL` | Yes | Git repository URL |
| `GITHUB_PAT` | Yes | GitHub Personal Access Token |
| `GITHUB_USERNAME` | Yes | GitHub username |
| `GOOGLE_CLIENT_ID` | No | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | No | Google OAuth client secret |
| `AWS_PROFILE` | No | AWS profile (default: rem) |

## Architecture

### Application Cluster

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Cluster                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   ArgoCD    │  │ cert-manager│  │ external-secrets    │  │
│  │ (GitOps)    │  │ (certs)     │  │ (AWS SSM)           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐│
│  │                    rem namespace                         ││
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌───────────┐  ││
│  │  │ rem-api │  │ workers │  │ phoenix │  │ postgres  │  ││
│  │  │ (HPA)   │  │ (KEDA)  │  │ (OTEL)  │  │ (CNPG)    │  ││
│  │  └─────────┘  └─────────┘  └─────────┘  └───────────┘  ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### Management Cluster (WIP)

The management cluster pattern enables:
- Centralized ArgoCD managing multiple clusters
- Separate blast radius for control plane
- Multi-region/multi-account deployments

```
┌─────────────────────┐
│ Management Cluster  │
│  ┌───────────────┐  │       ┌─────────────────┐
│  │    ArgoCD     │──────────│ App Cluster A   │
│  │   (central)   │  │       └─────────────────┘
│  └───────────────┘  │       ┌─────────────────┐
│                     │───────│ App Cluster B   │
└─────────────────────┘       └─────────────────┘
```

This is planned for future releases.

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for:
- Deployment checklist
- Common issues and fixes
- Session notes from deployments

## Related Documentation

| Component | Location |
|-----------|----------|
| CDK Infrastructure | `infra/cdk-eks/README.md` |
| Platform Services | `platform/README.md` |
| Application Stack | `application/README.md` |
| REM Package | `../rem/README.md` |
