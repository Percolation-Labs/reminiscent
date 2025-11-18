"""
REM EKS Infrastructure with Karpenter

Architecture (2025 Best Practices):
- EKS v1.31+ with managed node group for Karpenter controller
- Karpenter v1.1+ for workload autoscaling
- VPC with public + private subnets across 3 AZs
- IRSA (IAM Roles for Service Accounts) for pod-level permissions
- Private API endpoint with optional public access
- AL2023 (Amazon Linux 2023) for node AMIs
- VPC CNI as EKS addon
- CloudWatch logging enabled

References:
- https://www.pulumi.com/docs/iac/clouds/aws/guides/eks/
- https://docs.aws.amazon.com/eks/latest/best-practices/karpenter.html
- https://karpenter.sh/docs/
"""

import json

import pulumi
import pulumi_aws as aws
import pulumi_eks as eks
import pulumi_kubernetes as k8s
from pulumi import Config, Output, export

# ==============================================================================
# Configuration
# ==============================================================================

config = Config()
aws_config = Config("aws")

# Cluster settings
CLUSTER_NAME = config.get("cluster_name") or "rem-cluster"
CLUSTER_VERSION = config.get("cluster_version") or "1.31"
AWS_REGION = aws_config.get("region") or "us-east-1"

# VPC settings
VPC_CIDR = config.get("vpc_cidr") or "10.0.0.0/16"

# API endpoint settings
ENABLE_PRIVATE_ENDPOINT = config.get_bool("enable_private_endpoint") or True
ENABLE_PUBLIC_ENDPOINT = config.get_bool("enable_public_endpoint") or True

# Karpenter
KARPENTER_VERSION = config.get("karpenter_version") or "1.1.0"

# Logging
ENABLE_CLUSTER_LOGGING = config.get_bool("enable_cluster_logging") or True

# Tags
TAGS = {
    "Project": "REM",
    "ManagedBy": "Pulumi",
    "Environment": pulumi.get_stack(),
    "Cluster": CLUSTER_NAME,
}

# ==============================================================================
# VPC - Best Practice: Separate public/private subnets across 3 AZs
# ==============================================================================

# Get available AZs
azs = aws.get_availability_zones(state="available")

vpc = aws.ec2.Vpc(
    "rem-vpc",
    cidr_block=VPC_CIDR,
    enable_dns_hostnames=True,
    enable_dns_support=True,
    tags={**TAGS, "Name": f"{CLUSTER_NAME}-vpc"},
)

# Internet Gateway for public subnets
igw = aws.ec2.InternetGateway(
    "rem-igw",
    vpc_id=vpc.id,
    tags={**TAGS, "Name": f"{CLUSTER_NAME}-igw"},
)

# Public subnets (for NAT gateways and optional public load balancers)
public_subnet_cidrs = ["10.0.0.0/20", "10.0.16.0/20", "10.0.32.0/20"]
public_subnets = []

for i, cidr in enumerate(public_subnet_cidrs):
    subnet = aws.ec2.Subnet(
        f"rem-public-subnet-{i}",
        vpc_id=vpc.id,
        cidr_block=cidr,
        availability_zone=azs.names[i],
        map_public_ip_on_launch=True,
        tags={
            **TAGS,
            "Name": f"{CLUSTER_NAME}-public-{azs.names[i]}",
            "kubernetes.io/role/elb": "1",  # For AWS Load Balancer Controller
            f"kubernetes.io/cluster/{CLUSTER_NAME}": "owned",
        },
    )
    public_subnets.append(subnet)

# Public route table
public_rt = aws.ec2.RouteTable(
    "rem-public-rt",
    vpc_id=vpc.id,
    routes=[
        aws.ec2.RouteTableRouteArgs(
            cidr_block="0.0.0.0/0",
            gateway_id=igw.id,
        )
    ],
    tags={**TAGS, "Name": f"{CLUSTER_NAME}-public-rt"},
)

# Associate public subnets with public route table
for i, subnet in enumerate(public_subnets):
    aws.ec2.RouteTableAssociation(
        f"rem-public-rta-{i}",
        subnet_id=subnet.id,
        route_table_id=public_rt.id,
    )

# NAT Gateways (one per AZ for high availability)
nat_gateways = []
for i, subnet in enumerate(public_subnets):
    eip = aws.ec2.Eip(
        f"rem-nat-eip-{i}",
        domain="vpc",
        tags={**TAGS, "Name": f"{CLUSTER_NAME}-nat-eip-{i}"},
    )

    nat = aws.ec2.NatGateway(
        f"rem-nat-{i}",
        subnet_id=subnet.id,
        allocation_id=eip.id,
        tags={**TAGS, "Name": f"{CLUSTER_NAME}-nat-{i}"},
    )
    nat_gateways.append(nat)

# Private subnets (for EKS nodes and pods)
private_subnet_cidrs = ["10.0.128.0/20", "10.0.144.0/20", "10.0.160.0/20"]
private_subnets = []

for i, cidr in enumerate(private_subnet_cidrs):
    subnet = aws.ec2.Subnet(
        f"rem-private-subnet-{i}",
        vpc_id=vpc.id,
        cidr_block=cidr,
        availability_zone=azs.names[i],
        tags={
            **TAGS,
            "Name": f"{CLUSTER_NAME}-private-{azs.names[i]}",
            "kubernetes.io/role/internal-elb": "1",  # For internal load balancers
            f"kubernetes.io/cluster/{CLUSTER_NAME}": "owned",
            "karpenter.sh/discovery": CLUSTER_NAME,  # For Karpenter node discovery
        },
    )
    private_subnets.append(subnet)

# Private route tables (one per AZ for isolated failure domains)
for i, subnet in enumerate(private_subnets):
    private_rt = aws.ec2.RouteTable(
        f"rem-private-rt-{i}",
        vpc_id=vpc.id,
        routes=[
            aws.ec2.RouteTableRouteArgs(
                cidr_block="0.0.0.0/0",
                nat_gateway_id=nat_gateways[i].id,
            )
        ],
        tags={**TAGS, "Name": f"{CLUSTER_NAME}-private-rt-{i}"},
    )

    aws.ec2.RouteTableAssociation(
        f"rem-private-rta-{i}",
        subnet_id=subnet.id,
        route_table_id=private_rt.id,
    )

# ==============================================================================
# EKS Cluster with 2025 Best Practices
# ==============================================================================

# Cluster IAM role
cluster_role = aws.iam.Role(
    "rem-eks-cluster-role",
    assume_role_policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "eks.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    ),
    tags=TAGS,
)

# Attach required policies
aws.iam.RolePolicyAttachment(
    "rem-eks-cluster-policy",
    role=cluster_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEKSClusterPolicy",
)

aws.iam.RolePolicyAttachment(
    "rem-eks-vpc-resource-controller",
    role=cluster_role.name,
    policy_arn="arn:aws:iam::aws:policy/AmazonEKSVPCResourceController",
)

# EKS Cluster
cluster = eks.Cluster(
    "rem-eks-cluster",
    name=CLUSTER_NAME,
    version=CLUSTER_VERSION,
    vpc_id=vpc.id,
    public_subnet_ids=[s.id for s in public_subnets],
    private_subnet_ids=[s.id for s in private_subnets],
    endpoint_private_access=ENABLE_PRIVATE_ENDPOINT,
    endpoint_public_access=ENABLE_PUBLIC_ENDPOINT,
    service_role=cluster_role,
    create_oidc_provider=True,  # Required for IRSA
    enabled_cluster_log_types=[
        "api",
        "audit",
        "authenticator",
        "controllerManager",
        "scheduler",
    ]
    if ENABLE_CLUSTER_LOGGING
    else [],
    # Skip default node group - we'll create a dedicated one for Karpenter
    skip_default_node_group=True,
    # Use AL2023 as default (AL2 reaches EOL June 2025)
    default_node_group_ami_id="AL2023_x86_64_STANDARD",
    tags=TAGS,
)

# ==============================================================================
# Karpenter Prerequisites: Dedicated Node Group for Controller
# ==============================================================================

# Best Practice: Run Karpenter controller on a dedicated managed node group
# This prevents Karpenter from managing its own nodes (chicken-and-egg problem)

karpenter_node_role = aws.iam.Role(
    "rem-karpenter-node-role",
    assume_role_policy=json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "ec2.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    ),
    tags={**TAGS, "Name": f"{CLUSTER_NAME}-karpenter-node-role"},
)

# Attach required node policies
for policy in [
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",  # For Systems Manager access
]:
    aws.iam.RolePolicyAttachment(
        f"rem-karpenter-node-policy-{policy.split('/')[-1]}",
        role=karpenter_node_role.name,
        policy_arn=policy,
    )

# Instance profile for Karpenter nodes
karpenter_instance_profile = aws.iam.InstanceProfile(
    "rem-karpenter-instance-profile",
    role=karpenter_node_role.name,
    tags=TAGS,
)

# Dedicated managed node group for Karpenter controller (on-demand, small, fixed size)
karpenter_node_group = eks.ManagedNodeGroup(
    "rem-karpenter-controller-ng",
    cluster=cluster,
    node_role=karpenter_node_role,
    subnet_ids=[s.id for s in private_subnets],
    instance_types=["t3.medium"],  # Small instance for controller
    scaling_config=aws.eks.NodeGroupScalingConfigArgs(
        desired_size=2,  # HA for controller
        min_size=2,
        max_size=2,  # Fixed size - not managed by Karpenter
    ),
    labels={
        "role": "karpenter-controller",
        "workload": "system",
    },
    taints=[
        aws.eks.NodeGroupTaintArgs(
            key="CriticalAddonsOnly",
            value="true",
            effect="NO_SCHEDULE",
        )
    ],
    tags={**TAGS, "Name": f"{CLUSTER_NAME}-karpenter-ng"},
)

# ==============================================================================
# Karpenter IAM Role (IRSA)
# ==============================================================================

# Karpenter controller IAM role using IRSA
karpenter_controller_policy = aws.iam.Policy(
    "rem-karpenter-controller-policy",
    policy=Output.all(cluster.core.cluster.arn, cluster.core.cluster.name).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:CreateFleet",
                            "ec2:CreateLaunchTemplate",
                            "ec2:CreateTags",
                            "ec2:DescribeAvailabilityZones",
                            "ec2:DescribeImages",
                            "ec2:DescribeInstances",
                            "ec2:DescribeInstanceTypeOfferings",
                            "ec2:DescribeInstanceTypes",
                            "ec2:DescribeLaunchTemplates",
                            "ec2:DescribeSecurityGroups",
                            "ec2:DescribeSpotPriceHistory",
                            "ec2:DescribeSubnets",
                            "ec2:DeleteLaunchTemplate",
                            "ec2:RunInstances",
                            "ec2:TerminateInstances",
                        ],
                        "Resource": "*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": "ec2:RunInstances",
                        "Resource": [
                            f"arn:aws:ec2:{AWS_REGION}::image/*",
                            f"arn:aws:ec2:{AWS_REGION}::snapshot/*",
                            f"arn:aws:ec2:{AWS_REGION}:*:security-group/*",
                            f"arn:aws:ec2:{AWS_REGION}:*:subnet/*",
                        ],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["ssm:GetParameter"],
                        "Resource": f"arn:aws:ssm:{AWS_REGION}::parameter/aws/service/*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["eks:DescribeCluster"],
                        "Resource": args[0],
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["iam:PassRole"],
                        "Resource": karpenter_node_role.arn,
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["pricing:GetProducts"],
                        "Resource": "*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "sqs:DeleteMessage",
                            "sqs:GetQueueAttributes",
                            "sqs:GetQueueUrl",
                            "sqs:ReceiveMessage",
                        ],
                        "Resource": f"arn:aws:sqs:{AWS_REGION}:*:Karpenter-{args[1]}-*",
                    },
                ],
            }
        )
    ),
    tags=TAGS,
)

# IRSA role for Karpenter controller
karpenter_controller_role = aws.iam.Role(
    "rem-karpenter-controller-role",
    assume_role_policy=cluster.core.oidc_provider.apply(
        lambda oidc: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Federated": oidc.arn,
                        },
                        "Action": "sts:AssumeRoleWithWebIdentity",
                        "Condition": {
                            "StringEquals": {
                                f"{oidc.url}:aud": "sts.amazonaws.com",
                                f"{oidc.url}:sub": "system:serviceaccount:karpenter:karpenter",
                            }
                        },
                    }
                ],
            }
        )
    ),
    tags={**TAGS, "Name": f"{CLUSTER_NAME}-karpenter-controller"},
)

aws.iam.RolePolicyAttachment(
    "rem-karpenter-controller-policy-attach",
    role=karpenter_controller_role.name,
    policy_arn=karpenter_controller_policy.arn,
)

# ==============================================================================
# SQS Queue for Karpenter Interruption Handling
# ==============================================================================

# Best Practice: Use SQS for spot interruption and scheduled maintenance handling
karpenter_queue = aws.sqs.Queue(
    "rem-karpenter-queue",
    name=cluster.core.cluster.name.apply(lambda name: f"Karpenter-{name}"),
    message_retention_seconds=300,
    tags=TAGS,
)

# EventBridge rules for interruptions
interruption_events = [
    {
        "name": "ScheduledChange",
        "source": ["aws.health"],
        "detail_type": ["AWS Health Event"],
    },
    {
        "name": "SpotInterruption",
        "source": ["aws.ec2"],
        "detail_type": ["EC2 Spot Instance Interruption Warning"],
    },
    {
        "name": "InstanceRebalance",
        "source": ["aws.ec2"],
        "detail_type": ["EC2 Instance Rebalance Recommendation"],
    },
    {
        "name": "InstanceStateChange",
        "source": ["aws.ec2"],
        "detail_type": ["EC2 Instance State-change Notification"],
    },
]

for event in interruption_events:
    rule = aws.cloudwatch.EventRule(
        f"rem-karpenter-{event['name']}-rule",
        name=cluster.core.cluster.name.apply(
            lambda name: f"Karpenter-{name}-{event['name']}"
        ),
        event_pattern=json.dumps(
            {
                "source": event["source"],
                "detail-type": event["detail_type"],
            }
        ),
        tags=TAGS,
    )

    aws.cloudwatch.EventTarget(
        f"rem-karpenter-{event['name']}-target",
        rule=rule.name,
        arn=karpenter_queue.arn,
    )

# SQS queue policy for EventBridge
karpenter_queue_policy = aws.sqs.QueuePolicy(
    "rem-karpenter-queue-policy",
    queue_url=karpenter_queue.url,
    policy=karpenter_queue.arn.apply(
        lambda arn: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": ["events.amazonaws.com", "sqs.amazonaws.com"]},
                        "Action": "sqs:SendMessage",
                        "Resource": arn,
                    }
                ],
            }
        )
    ),
)

# ==============================================================================
# Install Karpenter via Helm
# ==============================================================================

# Kubernetes provider targeting our cluster
k8s_provider = k8s.Provider(
    "rem-k8s-provider",
    kubeconfig=cluster.kubeconfig,
    enable_server_side_apply=True,
)

# Create karpenter namespace
karpenter_namespace = k8s.core.v1.Namespace(
    "karpenter-namespace",
    metadata=k8s.meta.v1.ObjectMetaArgs(
        name="karpenter",
        labels={"app.kubernetes.io/name": "karpenter"},
    ),
    opts=pulumi.ResourceOptions(provider=k8s_provider),
)

# Install Karpenter Helm chart
karpenter_chart = k8s.helm.v3.Release(
    "karpenter",
    k8s.helm.v3.ReleaseArgs(
        chart="oci://public.ecr.aws/karpenter/karpenter",
        version=KARPENTER_VERSION,
        namespace="karpenter",
        values={
            "settings": {
                "clusterName": cluster.core.cluster.name,
                "clusterEndpoint": cluster.core.cluster.endpoint,
                "interruptionQueue": karpenter_queue.name,
            },
            "serviceAccount": {
                "annotations": {
                    "eks.amazonaws.com/role-arn": karpenter_controller_role.arn,
                }
            },
            "tolerations": [
                {
                    "key": "CriticalAddonsOnly",
                    "operator": "Exists",
                    "effect": "NoSchedule",
                }
            ],
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "role",
                                        "operator": "In",
                                        "values": ["karpenter-controller"],
                                    }
                                ]
                            }
                        ]
                    }
                }
            },
            "replicas": 2,  # HA for production
        },
    ),
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[karpenter_namespace, karpenter_node_group],
    ),
)

# ==============================================================================
# Exports
# ==============================================================================

export("cluster_name", cluster.core.cluster.name)
export("cluster_endpoint", cluster.core.cluster.endpoint)
export("cluster_version", cluster.core.cluster.version)
export("kubeconfig", cluster.kubeconfig)
export("vpc_id", vpc.id)
export("private_subnet_ids", [s.id for s in private_subnets])
export("public_subnet_ids", [s.id for s in public_subnets])
export("karpenter_node_role_arn", karpenter_node_role.arn)
export("karpenter_instance_profile_name", karpenter_instance_profile.name)
export("karpenter_queue_name", karpenter_queue.name)
export("oidc_provider_arn", cluster.core.oidc_provider.arn)
export("oidc_provider_url", cluster.core.oidc_provider.url)
