# REM EKS Infrastructure - Batteries Included

Minimal Pulumi YAML implementation using the **batteries-included** `eks:Cluster` component from Pulumi's official examples.

## What is Batteries-Included EKS?

The `eks:Cluster` component from Pulumi handles all AWS EKS infrastructure automatically with sensible defaults:

- ✅ **VPC**: Uses your default VPC (or specify custom VPC ID)
- ✅ **Subnets**: Auto-discovers subnets in your VPC
- ✅ **Worker Nodes**: Creates managed node group with auto-scaling (t3.medium by default)
- ✅ **IAM Roles**: Service roles for cluster and node instances
- ✅ **OIDC Provider**: For IAM Roles for Service Accounts (IRSA)
- ✅ **Security Groups**: Cluster and node security groups
- ✅ **CoreDNS, kube-proxy, aws-cni**: Essential add-ons
- ✅ **Kubeconfig**: Automatically generated

**Result**: Just 37 lines vs 240+ lines of manual configuration.

## Structure

```
eks-yaml/
├── Pulumi.yaml                  # Minimal EKS cluster (37 lines)
├── Pulumi.dev.yaml              # Stack configuration (AWS region)
└── README.md                    # This file
```

## The Complete Configuration

Here's the entire `Pulumi.yaml`:

```yaml
name: rem-eks-infra
runtime: yaml
description: REM EKS cluster using batteries-included defaults

variables:
  vpcId:
    fn::invoke:
      function: aws:ec2:getVpc
      arguments:
        default: true
      return: id
  subnetIds:
    fn::invoke:
      function: aws:ec2:getSubnets
      arguments:
        filters:
          - name: vpc-id
            values:
              - ${vpcId}
      return: ids

resources:
  cluster:
    type: eks:Cluster
    properties:
      name: rem-cluster
      version: "1.32"
      authenticationMode: API_AND_CONFIG_MAP
      vpcId: ${vpcId}
      subnetIds: ${subnetIds}
      desiredCapacity: 2
      minSize: 1
      maxSize: 3
      createOidcProvider: true

outputs:
  kubeconfig: ${cluster.kubeconfig}
  cluster_name: ${cluster.eksCluster.name}
  cluster_endpoint: ${cluster.eksCluster.endpoint}
  oidc_provider_arn: ${cluster.core.oidcProvider.arn}
```

That's it! No manual VPC resources, no subnets, no NAT gateways, no route tables.

## Deployment

### Prerequisites

Set environment variables (add to `~/.bash_profile`):
```bash
export AWS_PROFILE=rem
export PULUMI_CONFIG_PASSPHRASE="pul0101ce62e86ca730724c3d6a90c5d3cf565b"
```

### Deploy Infrastructure

```bash
cd manifests/infra/eks-yaml

# Initialize or select stack
pulumi stack select dev

# Preview changes
pulumi preview

# Deploy infrastructure (~15-20 minutes)
pulumi up

# Get kubeconfig
pulumi stack output kubeconfig --show-secrets > ~/.kube/rem-cluster.yaml
export KUBECONFIG=~/.kube/rem-cluster.yaml

# Verify cluster
kubectl get nodes
```

## Outputs

After deployment, access these values:

```bash
pulumi stack output cluster_name          # rem-cluster
pulumi stack output cluster_endpoint      # https://xxx.eks.amazonaws.com
pulumi stack output kubeconfig            # Complete kubeconfig
pulumi stack output oidc_provider_arn     # For IRSA setup
```

## What Gets Created Automatically?

When you run `pulumi up`, the `eks:Cluster` component creates:

1. **EKS Control Plane**: Managed Kubernetes control plane (version 1.32)
2. **Managed Node Group**:
   - Instance type: `t3.medium` (default)
   - Desired: 2 nodes
   - Min: 1 node
   - Max: 3 nodes
   - Auto-scaling group
3. **IAM Roles**:
   - EKS cluster service role
   - Node instance role with required policies
   - OIDC provider for IRSA
4. **Security Groups**:
   - Cluster security group
   - Node security group
   - Proper ingress/egress rules
5. **Launch Template**: For node group with EKS-optimized AMI
6. **Add-ons**: CoreDNS, kube-proxy, aws-cni

## Customization

To customize the cluster, modify properties in `Pulumi.yaml`:

```yaml
resources:
  cluster:
    type: eks:Cluster
    properties:
      name: rem-cluster
      version: "1.32"                    # Kubernetes version
      instanceType: "t3.large"           # Node instance type
      desiredCapacity: 3                 # Number of nodes
      minSize: 2                         # Min nodes
      maxSize: 5                         # Max nodes
      nodePublicKey: "ssh-rsa ..."       # SSH key for nodes
      enabledClusterLogTypes:            # Control plane logs
        - api
        - audit
        - authenticator
```

## Troubleshooting

### First-Time Provider Initialization
- **First run**: Provider download/initialization can take 20-30 minutes (one-time)
- **Subsequent runs**: Fast (<2 minutes)

### Cluster Access
```bash
# Update kubeconfig
pulumi stack output kubeconfig --show-secrets > ~/.kube/rem-cluster.yaml
export KUBECONFIG=~/.kube/rem-cluster.yaml
kubectl get nodes
```

### Destroy Infrastructure
```bash
# Delete all Kubernetes resources first
kubectl delete --all deployments,services,pods --all-namespaces

# Then destroy infrastructure
pulumi destroy
```

## Why Batteries-Included?

| Aspect | Manual (240+ lines) | Batteries-Included (37 lines) |
|--------|---------------------|-------------------------------|
| VPC Setup | 40+ resources | Auto-discovery |
| Node Groups | Manual launch template | Managed node group |
| IAM Roles | Manual policies | Auto-created |
| Security Groups | Manual rules | Best practices |
| Maintenance | High complexity | Low complexity |
| Preview Time | Prone to hangs | Fast & reliable |
| Error Prone | Yes | No |

## Next Steps

After infrastructure is deployed:

1. **Install Karpenter** (optional): For advanced node autoscaling
2. **Platform Layer**: Deploy ArgoCD, OpenTelemetry, CloudNativePG (see `manifests/platform/`)
3. **Application Layer**: Deploy REM API and MCP servers (see `manifests/application/`)
4. **Configure DNS**: Point your domain to the load balancer
5. **Set up monitoring**: Configure Arize Phoenix for LLM observability

## Resources

- [Pulumi EKS Cluster Component](https://www.pulumi.com/registry/packages/eks/api-docs/cluster/)
- [Official Pulumi EKS YAML Example](https://github.com/pulumi/examples/tree/master/aws-yaml-eks)
- [Pulumi Crosswalk for AWS](https://www.pulumi.com/docs/iac/clouds/aws/guides/)
- [AWS EKS Best Practices](https://aws.github.io/aws-eks-best-practices/)
