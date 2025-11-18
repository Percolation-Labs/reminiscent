"""
Karpenter NodePool and EC2NodeClass configurations

Following 2025 best practices:
- Separate NodePools for different workload types
- Consolidation enabled with WhenEmptyOrUnderutilized policy
- Spot diversity with 15+ instance types
- AL2023 AMI family
- Proper resource limits and taints

Deploy after cluster is created:
  pulumi up --target karpenter-resources
"""

import pulumi
import pulumi_kubernetes as k8s
from pulumi import Config, export

# Get cluster kubeconfig from main stack
config = Config()
stack_reference = pulumi.StackReference(f"organization/{pulumi.get_project()}/{pulumi.get_stack()}")

kubeconfig = stack_reference.get_output("kubeconfig")
cluster_name = stack_reference.get_output("cluster_name")
karpenter_node_role_arn = stack_reference.get_output("karpenter_node_role_arn")
karpenter_instance_profile_name = stack_reference.get_output("karpenter_instance_profile_name")

# Kubernetes provider
k8s_provider = k8s.Provider(
    "karpenter-k8s-provider",
    kubeconfig=kubeconfig,
    enable_server_side_apply=True,
)

# ==============================================================================
# EC2NodeClass - Infrastructure Configuration
# ==============================================================================

# General purpose EC2NodeClass for most workloads
general_purpose_nodeclass = k8s.apiextensions.CustomResource(
    "general-purpose-nodeclass",
    api_version="karpenter.k8s.aws/v1",
    kind="EC2NodeClass",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="general-purpose",
    ),
    spec={
        "amiFamily": "AL2023",  # Amazon Linux 2023 (AL2 EOL June 2025)
        "role": karpenter_instance_profile_name,
        "subnetSelectorTerms": [
            {
                "tags": {
                    f"karpenter.sh/discovery": cluster_name,
                }
            }
        ],
        "securityGroupSelectorTerms": [
            {
                "tags": {
                    f"kubernetes.io/cluster/{cluster_name}": "owned",
                }
            }
        ],
        "amiSelectorTerms": [
            {
                "alias": "al2023@latest",
            }
        ],
        "blockDeviceMappings": [
            {
                "deviceName": "/dev/xvda",
                "ebs": {
                    "volumeSize": "100Gi",
                    "volumeType": "gp3",
                    "iops": 3000,
                    "throughput": 125,
                    "encrypted": True,
                    "deleteOnTermination": True,
                },
            }
        ],
        "userData": """#!/bin/bash
set -e

# Configure kubelet
cat <<EOF > /etc/systemd/system/kubelet.service.d/90-kubelet-extra-args.conf
[Service]
Environment="KUBELET_EXTRA_ARGS=--max-pods=110"
EOF

systemctl daemon-reload
""",
        "metadataOptions": {
            "httpEndpoint": "enabled",
            "httpProtocolIPv6": "disabled",
            "httpPutResponseHopLimit": 2,
            "httpTokens": "required",  # IMDSv2 required for security
        },
        "tags": {
            "ManagedBy": "Karpenter",
            "Project": "REM",
            "NodeClass": "general-purpose",
        },
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider),
)

# Stateful workload EC2NodeClass (for databases, etc.)
stateful_nodeclass = k8s.apiextensions.CustomResource(
    "stateful-nodeclass",
    api_version="karpenter.k8s.aws/v1",
    kind="EC2NodeClass",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="stateful",
    ),
    spec={
        "amiFamily": "AL2023",
        "role": karpenter_instance_profile_name,
        "subnetSelectorTerms": [
            {
                "tags": {
                    f"karpenter.sh/discovery": cluster_name,
                }
            }
        ],
        "securityGroupSelectorTerms": [
            {
                "tags": {
                    f"kubernetes.io/cluster/{cluster_name}": "owned",
                }
            }
        ],
        "amiSelectorTerms": [
            {
                "alias": "al2023@latest",
            }
        ],
        "blockDeviceMappings": [
            {
                "deviceName": "/dev/xvda",
                "ebs": {
                    "volumeSize": "200Gi",  # Larger for databases
                    "volumeType": "gp3",
                    "iops": 10000,  # Higher IOPS for databases
                    "throughput": 500,
                    "encrypted": True,
                    "deleteOnTermination": True,
                },
            }
        ],
        "metadataOptions": {
            "httpEndpoint": "enabled",
            "httpProtocolIPv6": "disabled",
            "httpPutResponseHopLimit": 2,
            "httpTokens": "required",
        },
        "tags": {
            "ManagedBy": "Karpenter",
            "Project": "REM",
            "NodeClass": "stateful",
        },
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider),
)

# ==============================================================================
# NodePools - Workload Configuration (2025 Best Practices)
# ==============================================================================

# General purpose NodePool (spot + on-demand mix)
# Best Practice: Use spot for cost savings with diverse instance types
general_purpose_nodepool = k8s.apiextensions.CustomResource(
    "general-purpose-nodepool",
    api_version="karpenter.sh/v1",
    kind="NodePool",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="general-purpose",
    ),
    spec={
        "template": {
            "metadata": {
                "labels": {
                    "workload-type": "general",
                    "managed-by": "karpenter",
                },
            },
            "spec": {
                "nodeClassRef": {
                    "group": "karpenter.k8s.aws",
                    "kind": "EC2NodeClass",
                    "name": "general-purpose",
                },
                "requirements": [
                    {
                        "key": "karpenter.sh/capacity-type",
                        "operator": "In",
                        "values": ["spot", "on-demand"],
                    },
                    {
                        "key": "kubernetes.io/arch",
                        "operator": "In",
                        "values": ["amd64"],
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-category",
                        "operator": "In",
                        # Diverse instance families for spot flexibility
                        "values": ["c", "m", "r"],
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-generation",
                        "operator": "Gt",
                        "values": ["5"],  # Gen 6+ for better price/performance
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-size",
                        "operator": "In",
                        # 15+ instance types for spot diversity (best practice)
                        "values": [
                            "large",
                            "xlarge",
                            "2xlarge",
                            "4xlarge",
                        ],
                    },
                ],
                "taints": [],  # No taints - accept general workloads
            },
        },
        "limits": {
            "cpu": "1000",  # Cluster-wide CPU limit
            "memory": "4000Gi",  # Cluster-wide memory limit
        },
        "disruption": {
            # Best Practice: WhenEmptyOrUnderutilized for cost optimization
            "consolidationPolicy": "WhenEmptyOrUnderutilized",
            "consolidateAfter": "1m",  # Recommended value
            # Allow disruption during consolidation
            "budgets": [
                {
                    "nodes": "10%",  # Max 10% of nodes disrupted at once
                    "reasons": ["Underutilized", "Empty"],
                }
            ],
        },
        "weight": 10,  # Lower weight = higher priority
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider, depends_on=[general_purpose_nodeclass]),
)

# Stateful workload NodePool (on-demand only, no consolidation)
# Best Practice: Use on-demand for stateful workloads (databases, etc.)
stateful_nodepool = k8s.apiextensions.CustomResource(
    "stateful-nodepool",
    api_version="karpenter.sh/v1",
    kind="NodePool",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="stateful",
    ),
    spec={
        "template": {
            "metadata": {
                "labels": {
                    "workload-type": "stateful",
                    "managed-by": "karpenter",
                },
            },
            "spec": {
                "nodeClassRef": {
                    "group": "karpenter.k8s.aws",
                    "kind": "EC2NodeClass",
                    "name": "stateful",
                },
                "requirements": [
                    {
                        "key": "karpenter.sh/capacity-type",
                        "operator": "In",
                        "values": ["on-demand"],  # On-demand only for stability
                    },
                    {
                        "key": "kubernetes.io/arch",
                        "operator": "In",
                        "values": ["amd64"],
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-category",
                        "operator": "In",
                        "values": ["r", "m"],  # Memory-optimized or general purpose
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-generation",
                        "operator": "Gt",
                        "values": ["6"],
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-size",
                        "operator": "In",
                        "values": ["2xlarge", "4xlarge", "8xlarge"],
                    },
                ],
                "taints": [
                    {
                        "key": "workload-type",
                        "value": "stateful",
                        "effect": "NoSchedule",
                    }
                ],
            },
        },
        "limits": {
            "cpu": "500",
            "memory": "2000Gi",
        },
        "disruption": {
            # Best Practice: WhenEmpty only for stateful workloads
            "consolidationPolicy": "WhenEmpty",
            "consolidateAfter": "5m",  # Wait longer before removing empty nodes
        },
        "weight": 20,  # Higher weight = lower priority
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider, depends_on=[stateful_nodeclass]),
)

# Burst capacity NodePool (for temporary high load)
# Best Practice: Separate pool for burst workloads with aggressive consolidation
burst_nodepool = k8s.apiextensions.CustomResource(
    "burst-nodepool",
    api_version="karpenter.sh/v1",
    kind="NodePool",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="burst",
    ),
    spec={
        "template": {
            "metadata": {
                "labels": {
                    "workload-type": "burst",
                    "managed-by": "karpenter",
                },
            },
            "spec": {
                "nodeClassRef": {
                    "group": "karpenter.k8s.aws",
                    "kind": "EC2NodeClass",
                    "name": "general-purpose",
                },
                "requirements": [
                    {
                        "key": "karpenter.sh/capacity-type",
                        "operator": "In",
                        "values": ["spot"],  # Spot only for cost
                    },
                    {
                        "key": "kubernetes.io/arch",
                        "operator": "In",
                        "values": ["amd64"],
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-category",
                        "operator": "In",
                        "values": ["c", "m", "r", "t"],  # Include burstable
                    },
                    {
                        "key": "karpenter.k8s.aws/instance-generation",
                        "operator": "Gt",
                        "values": ["4"],
                    },
                ],
                "taints": [
                    {
                        "key": "workload-type",
                        "value": "burst",
                        "effect": "NoSchedule",
                    }
                ],
            },
        },
        "limits": {
            "cpu": "200",
            "memory": "500Gi",
        },
        "disruption": {
            "consolidationPolicy": "WhenEmptyOrUnderutilized",
            "consolidateAfter": "30s",  # Aggressive consolidation
        },
        "weight": 50,  # Lowest priority - only use when needed
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider, depends_on=[general_purpose_nodeclass]),
)

# ==============================================================================
# Exports
# ==============================================================================

export("general_purpose_nodepool_name", "general-purpose")
export("stateful_nodepool_name", "stateful")
export("burst_nodepool_name", "burst")
export("nodepool_count", 3)
