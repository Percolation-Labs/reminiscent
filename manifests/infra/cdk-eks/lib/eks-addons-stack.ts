import * as cdk from 'aws-cdk-lib';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
import { ClusterConfig } from './config';
import { EksClusterStack } from './eks-cluster-stack';

/**
 * EksAddonsStack - Kubernetes add-ons and manifests
 *
 * This stack creates:
 * - Storage classes (gp3, gp3-postgres, io2-postgres)
 * - Namespaces (rem, observability, postgres-cluster, karpenter)
 * - Service accounts with Pod Identity associations
 * - Karpenter Helm chart, NodePool, and EC2NodeClass
 *
 * This stack is SEPARATE from EksClusterStack so that:
 * - If addon deployment fails, cluster remains intact
 * - Can retry addon deployment without recreating cluster
 *
 * IMPORTANT: Uses eks.KubernetesManifest and eks.HelmChart directly
 * (not cluster.addManifest/addHelmChart) to avoid cross-stack cyclic dependencies.
 *
 * All K8s manifests are chained sequentially to avoid Lambda rate limiting
 * Full chain: gp3 → gp3-postgres → io2-postgres → rem → observability → postgres → karpenter
 */
export interface EksAddonsStackProps extends cdk.StackProps {
  clusterStack: EksClusterStack;
  config: ClusterConfig;
  environment: string;
  clusterName: string;
}

export class EksAddonsStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: EksAddonsStackProps) {
    super(scope, id, props);

    const cluster = props.clusterStack.cluster;

    // ============================================================
    // STORAGE CLASSES (chained sequentially)
    // ============================================================

    // gp3 default storage class
    const gp3StorageClass = new eks.KubernetesManifest(this, 'GP3StorageClass', {
      cluster,
      manifest: [{
        apiVersion: 'storage.k8s.io/v1',
        kind: 'StorageClass',
        metadata: {
          name: 'gp3',
          annotations: { 'storageclass.kubernetes.io/is-default-class': 'true' },
        },
        provisioner: 'ebs.csi.aws.com',
        parameters: {
          type: 'gp3',
          iops: '3000',
          throughput: '125',
          encrypted: 'true',
          fsType: 'ext4',
        },
        volumeBindingMode: 'WaitForFirstConsumer',
        allowVolumeExpansion: true,
        reclaimPolicy: 'Delete',
      }],
    });

    // gp3-postgres storage class
    const gp3PostgresStorageClass = new eks.KubernetesManifest(this, 'GP3PostgresStorageClass', {
      cluster,
      manifest: [{
        apiVersion: 'storage.k8s.io/v1',
        kind: 'StorageClass',
        metadata: { name: 'gp3-postgres' },
        provisioner: 'ebs.csi.aws.com',
        parameters: {
          type: 'gp3',
          iops: '5000',
          throughput: '250',
          encrypted: 'true',
          fsType: 'ext4',
        },
        volumeBindingMode: 'WaitForFirstConsumer',
        allowVolumeExpansion: true,
        reclaimPolicy: 'Delete',
      }],
    });
    gp3PostgresStorageClass.node.addDependency(gp3StorageClass);

    // io2-postgres storage class
    const io2PostgresStorageClass = new eks.KubernetesManifest(this, 'IO2PostgresStorageClass', {
      cluster,
      manifest: [{
        apiVersion: 'storage.k8s.io/v1',
        kind: 'StorageClass',
        metadata: { name: 'io2-postgres' },
        provisioner: 'ebs.csi.aws.com',
        parameters: {
          type: 'io2',
          iops: '10000',
          encrypted: 'true',
          fsType: 'ext4',
        },
        volumeBindingMode: 'WaitForFirstConsumer',
        allowVolumeExpansion: true,
        reclaimPolicy: 'Delete',
      }],
    });
    io2PostgresStorageClass.node.addDependency(gp3PostgresStorageClass);

    // ============================================================
    // HELM CHARTS
    // Pod Identity associations are now in EksClusterStack
    // Order: Karpenter first, then ALB Controller (to avoid webhook timing issues)
    // ============================================================

    // ============================================================
    // KARPENTER HELM + NODEPOOL + NODECLASS
    // Namespace, ServiceAccount, and PodIdentity created in EksClusterStack
    // Installed BEFORE ALB Controller to avoid webhook timing issues
    // ============================================================

    // Use eks.HelmChart directly (not cluster.addHelmChart) to keep it in this stack
    // Note: ServiceAccount created in ClusterStack for Pod Identity
    const karpenter = new eks.HelmChart(this, 'Karpenter', {
      cluster,
      chart: 'karpenter',
      repository: 'oci://public.ecr.aws/karpenter/karpenter',
      namespace: 'karpenter',
      version: '1.0.8',
      values: {
        settings: {
          clusterName: props.clusterName,
          clusterEndpoint: cluster.clusterEndpoint,
          interruptionQueue: props.clusterStack.karpenterQueue.queueName,
        },
        replicas: props.environment === 'production' ? 2 : 1,
        tolerations: [
          {
            key: 'CriticalAddonsOnly',
            operator: 'Exists',
            effect: 'NoSchedule',
          },
        ],
        nodeSelector: { 'node-type': 'karpenter-controller' },
        serviceAccount: {
          create: false,  // SA already created in ClusterStack for Pod Identity
          name: 'karpenter',
        },
      },
    });
    karpenter.node.addDependency(io2PostgresStorageClass);

    // Deploy AWS Load Balancer Controller via Helm
    // Required for Ingress resources and ALB/NLB provisioning
    // Note: ServiceAccount created in ClusterStack for Pod Identity
    // Installed AFTER Karpenter to avoid webhook timing issues
    const albController = new eks.HelmChart(this, 'ALBController', {
      cluster,
      chart: 'aws-load-balancer-controller',
      repository: 'https://aws.github.io/eks-charts',
      namespace: 'kube-system',
      version: '1.14.0',
      wait: true,  // Wait for pods to be ready before marking complete (required for webhook)
      values: {
        clusterName: cluster.clusterName,
        region: this.region,
        vpcId: props.clusterStack.vpc.vpcId,
        serviceAccount: {
          create: false,  // SA already created in ClusterStack for Pod Identity
          name: 'aws-load-balancer-controller',
        },
        enableShield: false,
        enableWaf: false,
        enableWafv2: false,
      },
    });
    albController.node.addDependency(karpenter);

    // Default NodePool
    const defaultNodePool = new eks.KubernetesManifest(this, 'KarpenterDefaultNodePool', {
      cluster,
      manifest: [{
        apiVersion: 'karpenter.sh/v1',
        kind: 'NodePool',
        metadata: { name: 'default' },
        spec: {
          template: {
            spec: {
              requirements: [
                { key: 'kubernetes.io/arch', operator: 'In', values: ['amd64'] },
                { key: 'kubernetes.io/os', operator: 'In', values: ['linux'] },
                {
                  key: 'karpenter.sh/capacity-type',
                  operator: 'In',
                  values: props.environment === 'production' ? ['on-demand'] : ['spot', 'on-demand'],
                },
                { key: 'karpenter.k8s.aws/instance-category', operator: 'In', values: ['c', 'm', 't'] },
                { key: 'karpenter.k8s.aws/instance-generation', operator: 'Gt', values: ['5'] },
              ],
              nodeClassRef: {
                group: 'karpenter.k8s.aws',
                kind: 'EC2NodeClass',
                name: 'default',
              },
              expireAfter: props.environment === 'production' ? '720h' : '168h',
            },
          },
          limits: {
            cpu: props.environment === 'production' ? '1000' : '100',
            memory: props.environment === 'production' ? '1000Gi' : '100Gi',
          },
          disruption: {
            consolidationPolicy: 'WhenEmptyOrUnderutilized',
            consolidateAfter: '1m',
          },
        },
      }],
    });
    defaultNodePool.node.addDependency(karpenter);

    // Default EC2NodeClass
    const defaultNodeClass = new eks.KubernetesManifest(this, 'KarpenterDefaultNodeClass', {
      cluster,
      manifest: [{
        apiVersion: 'karpenter.k8s.aws/v1',
        kind: 'EC2NodeClass',
        metadata: { name: 'default' },
        spec: {
          amiFamily: 'AL2023',
          amiSelectorTerms: [{ alias: 'al2023@latest' }],
          role: props.clusterStack.nodeRole.roleName,
          subnetSelectorTerms: [{ tags: { 'Name': '*Private*' } }],
          securityGroupSelectorTerms: [{ tags: { 'aws:eks:cluster-name': props.clusterName } }],
          userData: cdk.Fn.base64(
            ['#!/bin/bash', 'echo "Running custom user data"', '# Add any custom bootstrapping here'].join('\n')
          ),
          blockDeviceMappings: [
            {
              deviceName: '/dev/xvda',
              ebs: {
                volumeSize: '100Gi',
                volumeType: 'gp3',
                encrypted: true,
                deleteOnTermination: true,
              },
            },
          ],
          metadataOptions: {
            httpEndpoint: 'enabled',
            httpProtocolIPv6: 'disabled',
            httpPutResponseHopLimit: 1,
            httpTokens: 'required',
          },
        },
      }],
    });
    defaultNodeClass.node.addDependency(karpenter);

    // ============================================================
    // SECRETS AND PARAMETERS
    // - Secrets Manager: Random secrets (postgres password, session, phoenix)
    // - SSM Parameters: Config values (API keys, postgres username)
    // External Secrets Operator can read from both stores
    // ============================================================

    if (props.config.enableSsmParameters) {
      const prefix = props.config.ssmPrefix;

      // Validate required API keys
      if (!props.config.anthropicApiKey) {
        console.warn('⚠️  ANTHROPIC_API_KEY not set - SSM parameter will be empty');
      }
      if (!props.config.openaiApiKey) {
        console.warn('⚠️  OPENAI_API_KEY not set - SSM parameter will be empty');
      }

      // Helper to create/update SSM parameter using SDK (bypasses CloudFormation early validation)
      const putSsmParameter = (id: string, parameterName: string, value: string, description: string) => {
        return new cr.AwsCustomResource(this, id, {
          onCreate: {
            service: 'SSM',
            action: 'putParameter',
            parameters: {
              Name: parameterName,
              Value: value,
              Type: 'String',
              Overwrite: true,
              Description: description,
            },
            physicalResourceId: cr.PhysicalResourceId.of(parameterName),
          },
          onUpdate: {
            service: 'SSM',
            action: 'putParameter',
            parameters: {
              Name: parameterName,
              Value: value,
              Type: 'String',
              Overwrite: true,
              Description: description,
            },
            physicalResourceId: cr.PhysicalResourceId.of(parameterName),
          },
          policy: cr.AwsCustomResourcePolicy.fromStatements([
            new iam.PolicyStatement({
              actions: ['ssm:PutParameter', 'ssm:GetParameter', 'ssm:DeleteParameter'],
              resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${prefix}/*`],
            }),
          ]),
        });
      };

      // ---- SSM Parameters (for config values - API keys, usernames) ----

      // PostgreSQL username (not a secret)
      putSsmParameter('PostgresUsername', `${prefix}/postgres/username`, 'remuser', 'PostgreSQL username for REM database');

      // LLM API Keys (from environment variables)
      putSsmParameter('AnthropicApiKey', `${prefix}/llm/anthropic-api-key`, props.config.anthropicApiKey || 'placeholder', 'Anthropic API key for Claude');
      putSsmParameter('OpenAIApiKey', `${prefix}/llm/openai-api-key`, props.config.openaiApiKey || 'placeholder', 'OpenAI API key');

      // Google OAuth (from environment variables)
      putSsmParameter('GoogleClientId', `${prefix}/auth/google-client-id`, props.config.googleClientId, 'Google OAuth Client ID');
      putSsmParameter('GoogleClientSecret', `${prefix}/auth/google-client-secret`, props.config.googleClientSecret, 'Google OAuth Client Secret');

      // ---- Secrets Manager (for random secrets - External Secrets reads from here) ----

      // PostgreSQL password
      new secretsmanager.Secret(this, 'PostgresPasswordSecret', {
        secretName: `${prefix}/postgres/password`,
        generateSecretString: {
          excludeCharacters: '"@/\\\'',
          passwordLength: 32,
        },
        description: 'PostgreSQL password for REM database',
      });

      // Phoenix secrets
      new secretsmanager.Secret(this, 'PhoenixApiKeySecret', {
        secretName: `${prefix}/phoenix/api-key`,
        generateSecretString: { passwordLength: 32 },
        description: 'Phoenix API key',
      });

      new secretsmanager.Secret(this, 'PhoenixSecretSecret', {
        secretName: `${prefix}/phoenix/secret`,
        generateSecretString: { passwordLength: 32 },
        description: 'Phoenix secret',
      });

      new secretsmanager.Secret(this, 'PhoenixAdminSecret', {
        secretName: `${prefix}/phoenix/admin-secret`,
        generateSecretString: { passwordLength: 32 },
        description: 'Phoenix admin secret',
      });

      // Session secret
      new secretsmanager.Secret(this, 'SessionSecret', {
        secretName: `${prefix}/auth/session-secret`,
        generateSecretString: { passwordLength: 32 },
        description: 'Session secret for authentication',
      });
    }

    // ============================================================
    // ARGOCD (Optional - deploy to app cluster or management cluster)
    // ============================================================

    if (props.config.enableArgoCD) {
      // ArgoCD namespace created in EksClusterStack

      // Deploy ArgoCD via Helm
      const argocd = new eks.HelmChart(this, 'ArgoCD', {
        cluster,
        chart: 'argo-cd',
        repository: 'https://argoproj.github.io/argo-helm',
        namespace: 'argocd',
        version: props.config.argoCDVersion,
        values: {
          // Minimal config for application cluster
          // Full config should be in values file for production
          server: {
            service: {
              type: 'LoadBalancer',
            },
            extraArgs: ['--insecure'], // Disable TLS (ALB handles it)
          },
          configs: {
            params: {
              'server.insecure': true,
            },
          },
          // Disable HA for non-production
          controller: {
            replicas: props.environment === 'production' ? 2 : 1,
          },
          repoServer: {
            replicas: props.environment === 'production' ? 2 : 1,
          },
          applicationSet: {
            replicas: props.environment === 'production' ? 2 : 1,
          },
        },
      });
      // ArgoCD must wait for ALB Controller pods to be ready (webhook must be available)
      argocd.node.addDependency(albController);
    }

    // ============================================================
    // OUTPUTS
    // ============================================================

    new cdk.CfnOutput(this, 'AddonsDeployed', {
      value: 'true',
      description: 'Indicates all K8s addons were deployed successfully',
    });

    if (props.config.enableSsmParameters) {
      new cdk.CfnOutput(this, 'SSMPrefix', {
        value: props.config.ssmPrefix,
        description: 'SSM Parameter Store prefix for secrets',
      });
    }

    if (props.config.enableArgoCD) {
      new cdk.CfnOutput(this, 'ArgoCDInstalled', {
        value: 'true',
        description: 'ArgoCD installed via Helm',
      });
    }
  }
}
