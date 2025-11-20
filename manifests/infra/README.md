# Infrastructure Layer

The infrastructure layer is provisioned using **Pulumi YAML**, not Kubernetes manifests or Python code.

## Pulumi YAML Stack

**Location**: `manifests/infra/pulumi/eks-yaml/`

### Why Pulumi YAML?

1. **No virtualenv issues** - YAML runtime doesn't need Python packages
2. **Declarative** - Clearer intent, easier to review than Python
3. **Single file** - All infrastructure in `Pulumi.yaml`
4. **Proven pattern** - Based on working production implementation
5. **Type-safe configuration** - Config schema with defaults

## What Gets Provisioned

### VPC & Networking
- Custom VPC (10.0.0.0/16)
- 3 public subnets across AZs (for load balancers)
- 3 private subnets across AZs (for nodes)
- Internet Gateway
- NAT Gateways (one per AZ for HA)
- Route tables with proper associations
- EKS discovery tags on subnets
- Karpenter discovery tags on private subnets

### EKS Cluster
- EKS 1.32 cluster using `eks:Cluster` component
- OIDC provider for IRSA (automatic)
- Control plane logging enabled
- Private + public endpoint access
- No default node group (Karpenter manages all nodes)
- Cluster security group

### IAM Roles
- **EKS Cluster Role**: For EKS control plane
- **Karpenter Node Role**: For EC2 instances provisioned by Karpenter
  - EKS Worker Node Policy
  - EKS CNI Policy
  - ECR Read-Only
  - SSM Managed Instance Core
- **Karpenter Controller Role (IRSA)**: For Karpenter controller pod
  - EC2 instance management
  - IAM PassRole
  - SSM pricing data access
  - SQS interruption queue access
  - EKS cluster describe

### Karpenter Setup
- **SQS Queue**: For spot interruption notifications
- **EventBridge Rules**:
  - EC2 Spot Instance Interruption Warning
  - EC2 Instance Rebalance Recommendation
  - AWS Health Events
- **Helm Chart**: Karpenter v1.1.0 installed via Kubernetes provider
- **ServiceAccount**: Annotated with IRSA role ARN
- **Tolerations**: Runs on karpenter-controller nodes

### Karpenter NodePools (Applied Separately)
After Pulumi deployment, apply `karpenter-nodepools.yaml`:
- **stateful**: On-demand instances for databases
- **stateless**: Spot instances for API/MCP
- **gpu**: GPU instances for ML inference

## Deployment

**Prerequisites**: Add to your `~/.bash_profile` or `~/.zshrc`:
```bash
export AWS_PROFILE=rem
export PULUMI_CONFIG_PASSPHRASE="your-passphrase-here"
```

Then deploy:

```bash
cd manifests/infra/pulumi/eks-yaml

# Select stack (if already initialized)
pulumi stack select dev

# Or initialize new stack
# pulumi stack init dev

# Preview changes
pulumi preview

# Deploy
pulumi up

# Get kubeconfig
pulumi stack output kubeconfig > ~/.kube/rem-cluster-config
export KUBECONFIG=~/.kube/rem-cluster-config

# Verify cluster
kubectl get nodes

# Apply Karpenter NodePools
kubectl apply -f karpenter-nodepools.yaml

# Verify Karpenter
kubectl get nodepools -n karpenter
kubectl get ec2nodeclasses -n karpenter
```

## Configuration

Override defaults via `Pulumi.dev.yaml` or CLI:

```bash
# Change cluster version
pulumi config set cluster_version "1.33"

# Smaller nodes for dev
pulumi config set node_instance_type "t3.small"
pulumi config set node_desired_size 1

# Change Karpenter version
pulumi config set karpenter_version "1.2.0"
```

## Stack Outputs

- `cluster_name`: EKS cluster name
- `cluster_endpoint`: EKS API endpoint
- `cluster_arn`: Cluster ARN
- `kubeconfig`: Ready-to-use kubeconfig
- `oidc_provider_arn`: For creating additional IRSA roles
- `oidc_provider_url`: OIDC issuer URL
- `vpc_id`: VPC ID
- `private_subnet_ids`: Private subnet IDs
- `public_subnet_ids`: Public subnet IDs
- `karpenter_node_role_arn`: IAM role ARN for Karpenter nodes
- `karpenter_controller_role_arn`: IAM role ARN for Karpenter controller
- `karpenter_interruption_queue_name`: SQS queue name

## Why Separate from Platform/Apps?

1. **Single Source of Truth**: Infrastructure state managed by Pulumi
2. **Immutable Infrastructure**: Recreate clusters from code
3. **Proper Layering**: Infra → Platform → Apps
4. **Clear Boundaries**: ArgoCD doesn't manage AWS resources
5. **Disaster Recovery**: Pulumi stack = full cluster rebuild

## Next Steps

After infrastructure deployment:

1. Install platform components (ArgoCD, External Secrets, etc.) - see `manifests/platform/`
2. Deploy applications - see `manifests/application/`
3. Configure observability (Phoenix, OTel)

## Migration from Python Pulumi

The old Python-based Pulumi stack (`manifests/infra/pulumi/`) has been replaced with this YAML-based approach. The YAML version:

- Is simpler and more declarative
- Has no Python dependency issues
- Uses proven patterns from production
- Includes Karpenter installation in the stack (not via ArgoCD)
