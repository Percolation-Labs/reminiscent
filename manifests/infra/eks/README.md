# REM EKS Infrastructure

Production-ready Amazon EKS cluster with Karpenter autoscaling following 2025 best practices.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         AWS Region (us-east-1)                   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    VPC (10.0.0.0/16)                       │ │
│  │                                                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │ │
│  │  │  AZ-1 (us-  │  │  AZ-2 (us-  │  │  AZ-3 (us-  │    │ │
│  │  │  east-1a)   │  │  east-1b)   │  │  east-1c)   │    │ │
│  │  ├──────────────┤  ├──────────────┤  ├──────────────┤    │ │
│  │  │ Public Sub   │  │ Public Sub   │  │ Public Sub   │    │ │
│  │  │ 10.0.0.0/20  │  │ 10.0.16.0/20 │  │ 10.0.32.0/20 │    │ │
│  │  │  - NAT GW    │  │  - NAT GW    │  │  - NAT GW    │    │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │ │
│  │         │                  │                  │            │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │ │
│  │  │ Private Sub  │  │ Private Sub  │  │ Private Sub  │    │ │
│  │  │ 10.0.128/20  │  │ 10.0.144/20  │  │ 10.0.160/20  │    │ │
│  │  │  - EKS Nodes │  │  - EKS Nodes │  │  - EKS Nodes │    │ │
│  │  │  - Karpenter │  │  - Karpenter │  │  - Karpenter │    │ │
│  │  └──────────────┘  └──────────────┘  └──────────────┘    │ │
│  │                                                             │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  EKS Control Plane (v1.31)                                  │ │
│  │  - OIDC Provider (IRSA enabled)                            │ │
│  │  - CloudWatch Logging (api, audit, auth, controller)       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Karpenter Controller (Managed Node Group)                  │ │
│  │  - 2x t3.medium (on-demand, fixed size)                    │ │
│  │  - Tainted for system workloads only                       │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Karpenter NodePools                                        │ │
│  │  ┌─────────────────┬─────────────────┬─────────────────┐  │ │
│  │  │ General Purpose │    Stateful     │      Burst      │  │ │
│  │  │ - Spot/On-demand│ - On-demand only│  - Spot only    │  │ │
│  │  │ - 15+ instances │ - r/m families  │  - Aggressive   │  │ │
│  │  │ - Consolidated  │ - No consolidate│  - consolidation│  │ │
│  │  └─────────────────┴─────────────────┴─────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  SQS + EventBridge (Interruption Handling)                 │ │
│  │  - Spot interruption warnings                              │ │
│  │  - Instance rebalance recommendations                      │ │
│  │  - Scheduled maintenance events                            │ │
│  └─────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

## Features

### ✅ 2025 Best Practices
- **EKS v1.31** - Latest Kubernetes version
- **AL2023 AMIs** - Amazon Linux 2023 (AL2 EOL June 2025)
- **VPC CNI as addon** - Modern networking management
- **IRSA enabled** - IAM Roles for Service Accounts
- **Private API endpoint** - Enhanced security
- **Multi-AZ HA** - 3 availability zones

### 🚀 Karpenter Features
- **Dedicated controller node group** - Prevents chicken-and-egg problem
- **Multi-NodePool strategy** - Separate pools for different workloads
- **Spot diversity** - 15+ instance types for spot reliability
- **Consolidation enabled** - WhenEmptyOrUnderutilized for cost savings
- **Interruption handling** - SQS + EventBridge for graceful spot handling
- **IMDSv2 enforced** - Enhanced security

### 💰 Cost Optimization
- **Spot instances** - Up to 90% cost savings
- **Automatic consolidation** - Remove underutilized nodes
- **Rightsizing** - Karpenter selects optimal instance types
- **Burst capacity** - Scale up only when needed

### 🔒 Security
- **Private subnets** - All nodes in private subnets
- **NAT Gateways** - One per AZ for HA
- **IMDSv2 required** - Metadata service v2 only
- **Encrypted EBS volumes** - All node volumes encrypted
- **IRSA** - Fine-grained IAM permissions per pod
- **Security groups** - Network isolation

## Prerequisites

1. **AWS CLI** configured with credentials
   ```bash
   aws configure
   ```

2. **Pulumi CLI** installed
   ```bash
   curl -fsSL https://get.pulumi.com | sh
   ```

3. **Python 3.12+** with pip
   ```bash
   python --version
   ```

4. **kubectl** for Kubernetes access
   ```bash
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/darwin/arm64/kubectl"
   chmod +x kubectl
   sudo mv kubectl /usr/local/bin/
   ```

5. **aws-iam-authenticator** for EKS authentication
   ```bash
   brew install aws-iam-authenticator
   ```

## Deployment

### 1. Initialize Pulumi Stack

```bash
cd manifests/infra/eks

# Create new stack (dev, staging, prod)
pulumi stack init dev

# Set AWS region
pulumi config set aws:region us-east-1

# (Optional) Customize cluster name
pulumi config set rem:cluster_name rem-dev-cluster
```

### 2. Install Python Dependencies

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Deploy Infrastructure

```bash
# Preview changes
pulumi preview

# Deploy cluster (takes ~15-20 minutes)
pulumi up

# Get kubeconfig
pulumi stack output kubeconfig --show-secrets > ~/.kube/rem-dev-config
export KUBECONFIG=~/.kube/rem-dev-config

# Verify cluster access
kubectl get nodes
kubectl get pods -n karpenter
```

### 4. Deploy Karpenter Resources

After cluster is created, deploy NodePools:

```bash
# Apply Karpenter NodePools and EC2NodeClasses
python karpenter_resources.py

# Verify NodePools
kubectl get nodepools
kubectl get ec2nodeclasses
```

## Configuration Options

### Cluster Settings

```bash
# Kubernetes version
pulumi config set rem:cluster_version 1.31

# Enable/disable public API endpoint
pulumi config set rem:enable_public_endpoint true

# Enable/disable private API endpoint
pulumi config set rem:enable_private_endpoint true

# Enable control plane logging
pulumi config set rem:enable_cluster_logging true
```

### Karpenter Settings

```bash
# Karpenter Helm chart version
pulumi config set rem:karpenter_version 1.1.0
```

### VPC Settings

```bash
# Custom VPC CIDR
pulumi config set rem:vpc_cidr 10.0.0.0/16
```

## NodePool Selection

Workloads are scheduled to appropriate NodePools based on tolerations:

### General Purpose (Default)
```yaml
# No tolerations needed - accepts all workloads
apiVersion: v1
kind: Pod
metadata:
  name: my-app
spec:
  containers:
  - name: app
    image: my-app:latest
    resources:
      requests:
        cpu: "1"
        memory: "2Gi"
```

### Stateful Workloads
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: postgres
spec:
  tolerations:
  - key: workload-type
    value: stateful
    effect: NoSchedule
  containers:
  - name: postgres
    image: postgres:16
    resources:
      requests:
        cpu: "4"
        memory: "16Gi"
```

### Burst Capacity
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: batch-job
spec:
  tolerations:
  - key: workload-type
    value: burst
    effect: NoSchedule
  containers:
  - name: processor
    image: batch-processor:latest
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
```

## Monitoring

### Cluster Health

```bash
# Check control plane components
kubectl get componentstatuses

# Check node status
kubectl get nodes

# Check Karpenter controller
kubectl get pods -n karpenter
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter
```

### Karpenter Metrics

```bash
# View NodePool status
kubectl describe nodepools

# View provisioned nodes
kubectl get nodes -l karpenter.sh/nodepool

# Check pending pods
kubectl get pods --all-namespaces --field-selector=status.phase=Pending
```

### Cost Analysis

```bash
# View node utilization
kubectl top nodes

# View pod resource requests vs limits
kubectl describe nodes | grep -A 5 "Allocated resources"
```

## Troubleshooting

### Karpenter Not Provisioning Nodes

1. Check Karpenter logs:
   ```bash
   kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100
   ```

2. Verify NodePool configuration:
   ```bash
   kubectl describe nodepool general-purpose
   ```

3. Check IAM permissions:
   ```bash
   aws sts get-caller-identity
   kubectl describe sa -n karpenter karpenter
   ```

### Pods Stuck Pending

1. Check pod events:
   ```bash
   kubectl describe pod <pod-name>
   ```

2. Verify resource requests:
   ```bash
   kubectl get pods -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[*].resources.requests}{"\n"}{end}'
   ```

3. Check NodePool limits:
   ```bash
   kubectl get nodepools -o yaml | grep -A 5 "limits:"
   ```

### Spot Interruptions

1. Check SQS queue for interruption messages:
   ```bash
   aws sqs get-queue-attributes --queue-url $(pulumi stack output karpenter_queue_name) --attribute-names All
   ```

2. View node events:
   ```bash
   kubectl get events --all-namespaces --field-selector reason=SpotInterruption
   ```

## Cleanup

```bash
# Destroy all resources
pulumi destroy

# Remove stack
pulumi stack rm dev
```

## Cost Estimates

Based on typical workload (assumes 50% spot usage):

| Component | Monthly Cost (USD) |
|-----------|-------------------|
| EKS Control Plane | $73 |
| Karpenter Controller Nodes (2x t3.medium) | ~$60 |
| NAT Gateways (3x) | ~$97 |
| Workload Nodes (variable) | $200-2000+ |
| Data Transfer | $50-200+ |
| **Estimated Total** | **$480-2430+** |

### Cost Optimization Tips:
- Use spot instances (up to 90% savings)
- Enable consolidation (removes underutilized nodes)
- Set appropriate resource requests (prevents overprovisioning)
- Use burst NodePool for temporary workloads
- Monitor with Kubecost or AWS Cost Explorer

## References

- [Pulumi EKS Guide](https://www.pulumi.com/docs/iac/clouds/aws/guides/eks/)
- [Karpenter Documentation](https://karpenter.sh/docs/)
- [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
- [EKS Karpenter Best Practices](https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html)
- [Pulumi EKS v3 Migration](https://www.pulumi.com/registry/packages/eks/how-to-guides/v3-migration/)
