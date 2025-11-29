import * as cdk from 'aws-cdk-lib';
import * as eks from 'aws-cdk-lib/aws-eks';
import * as ssm from 'aws-cdk-lib/aws-ssm';
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
    // REM NAMESPACE + SERVICE ACCOUNT + POD IDENTITY
    // ============================================================

    const remNamespace = new eks.KubernetesManifest(this, 'REMNamespace', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Namespace',
        metadata: { name: props.config.appNamespace },
      }],
    });
    remNamespace.node.addDependency(io2PostgresStorageClass);

    const remAppServiceAccount = new eks.KubernetesManifest(this, 'REMAppServiceAccount', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'ServiceAccount',
        metadata: {
          name: 'rem-app',
          namespace: props.config.appNamespace,
        },
      }],
    });
    remAppServiceAccount.node.addDependency(remNamespace);

    const remAppPodIdentity = new eks.CfnPodIdentityAssociation(this, 'REMAppPodIdentity', {
      clusterName: cluster.clusterName,
      namespace: props.config.appNamespace,
      serviceAccount: 'rem-app',
      roleArn: props.clusterStack.appPodRole.roleArn,
    });
    remAppPodIdentity.node.addDependency(remAppServiceAccount);

    // ============================================================
    // OBSERVABILITY NAMESPACE + SERVICE ACCOUNT + POD IDENTITY
    // ============================================================

    const observabilityNamespace = new eks.KubernetesManifest(this, 'ObservabilityNamespace', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Namespace',
        metadata: { name: 'observability' },
      }],
    });
    observabilityNamespace.node.addDependency(remNamespace);

    const otelCollectorServiceAccount = new eks.KubernetesManifest(this, 'OTELCollectorServiceAccount', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'ServiceAccount',
        metadata: {
          name: 'otel-collector',
          namespace: 'observability',
        },
      }],
    });
    otelCollectorServiceAccount.node.addDependency(observabilityNamespace);

    const otelCollectorPodIdentity = new eks.CfnPodIdentityAssociation(this, 'OTELCollectorPodIdentity', {
      clusterName: cluster.clusterName,
      namespace: 'observability',
      serviceAccount: 'otel-collector',
      roleArn: props.clusterStack.otelCollectorRole.roleArn,
    });
    otelCollectorPodIdentity.node.addDependency(otelCollectorServiceAccount);

    // ============================================================
    // POSTGRES NAMESPACE + SERVICE ACCOUNT + POD IDENTITY
    // ============================================================

    const postgresNamespace = new eks.KubernetesManifest(this, 'PostgresClusterNamespace', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Namespace',
        metadata: { name: 'postgres-cluster' },
      }],
    });
    postgresNamespace.node.addDependency(observabilityNamespace);

    const postgresBackupServiceAccount = new eks.KubernetesManifest(this, 'PostgresBackupServiceAccount', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'ServiceAccount',
        metadata: {
          name: 'postgres-backup',
          namespace: 'postgres-cluster',
        },
      }],
    });
    postgresBackupServiceAccount.node.addDependency(postgresNamespace);

    const cnpgBackupPodIdentity = new eks.CfnPodIdentityAssociation(this, 'CNPGBackupPodIdentity', {
      clusterName: cluster.clusterName,
      namespace: 'postgres-cluster',
      serviceAccount: 'postgres-backup',
      roleArn: props.clusterStack.cnpgBackupRole.roleArn,
    });
    cnpgBackupPodIdentity.node.addDependency(postgresBackupServiceAccount);

    // ============================================================
    // EXTERNAL SECRETS POD IDENTITY
    // ============================================================

    const externalSecretsPodIdentity = new eks.CfnPodIdentityAssociation(this, 'ExternalSecretsPodIdentity', {
      clusterName: cluster.clusterName,
      namespace: 'external-secrets-system',
      serviceAccount: 'external-secrets',
      roleArn: props.clusterStack.externalSecretsRole.roleArn,
    });
    externalSecretsPodIdentity.node.addDependency(cnpgBackupPodIdentity);

    // ============================================================
    // ALB CONTROLLER POD IDENTITY + HELM
    // ============================================================

    const albControllerPodIdentity = new eks.CfnPodIdentityAssociation(this, 'ALBControllerPodIdentity', {
      clusterName: cluster.clusterName,
      namespace: 'kube-system',
      serviceAccount: 'aws-load-balancer-controller',
      roleArn: props.clusterStack.albControllerRole.roleArn,
    });
    albControllerPodIdentity.node.addDependency(externalSecretsPodIdentity);

    // Deploy AWS Load Balancer Controller via Helm
    // Required for Ingress resources and ALB/NLB provisioning
    const albController = new eks.HelmChart(this, 'ALBController', {
      cluster,
      chart: 'aws-load-balancer-controller',
      repository: 'https://aws.github.io/eks-charts',
      namespace: 'kube-system',
      version: '1.14.0',
      values: {
        clusterName: cluster.clusterName,
        region: this.region,
        vpcId: props.clusterStack.vpc.vpcId,
        serviceAccount: {
          create: true,
          name: 'aws-load-balancer-controller',
          annotations: {},  // Pod Identity - no IRSA annotation needed
        },
        enableShield: false,
        enableWaf: false,
        enableWafv2: false,
      },
    });
    albController.node.addDependency(albControllerPodIdentity);

    // ============================================================
    // KARPENTER NAMESPACE + HELM + NODEPOOL + NODECLASS
    // ============================================================

    const karpenterNamespace = new eks.KubernetesManifest(this, 'KarpenterNamespace', {
      cluster,
      manifest: [{
        apiVersion: 'v1',
        kind: 'Namespace',
        metadata: { name: 'karpenter' },
      }],
    });
    karpenterNamespace.node.addDependency(postgresNamespace);

    const karpenterPodIdentity = new eks.CfnPodIdentityAssociation(this, 'KarpenterPodIdentity', {
      clusterName: cluster.clusterName,
      namespace: 'karpenter',
      serviceAccount: 'karpenter',
      roleArn: props.clusterStack.karpenterRole.roleArn,
    });
    karpenterPodIdentity.node.addDependency(karpenterNamespace);

    // Use eks.HelmChart directly (not cluster.addHelmChart) to keep it in this stack
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
        serviceAccount: { name: 'karpenter', annotations: {} },
      },
    });

    karpenter.node.addDependency(karpenterNamespace);
    karpenter.node.addDependency(karpenterPodIdentity);

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
    // SSM PARAMETERS (Optional - for External Secrets Operator)
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

      // PostgreSQL credentials
      new ssm.StringParameter(this, 'PostgresUsername', {
        parameterName: `${prefix}/postgres/username`,
        stringValue: 'remuser',
        description: 'PostgreSQL username for REM database',
        tier: ssm.ParameterTier.STANDARD,
      });

      // Generate random password for PostgreSQL
      const postgresPassword = new secretsmanager.Secret(this, 'PostgresPasswordSecret', {
        secretName: `${prefix}/postgres/password-secret`,
        generateSecretString: {
          excludeCharacters: '"@/\\\'',
          passwordLength: 32,
        },
      });

      new ssm.StringParameter(this, 'PostgresPassword', {
        parameterName: `${prefix}/postgres/password`,
        stringValue: postgresPassword.secretValue.unsafeUnwrap(),
        description: 'PostgreSQL password for REM database',
        tier: ssm.ParameterTier.STANDARD,
      });

      // LLM API Keys
      new ssm.StringParameter(this, 'AnthropicApiKey', {
        parameterName: `${prefix}/llm/anthropic-api-key`,
        stringValue: props.config.anthropicApiKey || 'placeholder',
        description: 'Anthropic API key for Claude',
        tier: ssm.ParameterTier.STANDARD,
      });

      new ssm.StringParameter(this, 'OpenAIApiKey', {
        parameterName: `${prefix}/llm/openai-api-key`,
        stringValue: props.config.openaiApiKey || 'placeholder',
        description: 'OpenAI API key',
        tier: ssm.ParameterTier.STANDARD,
      });

      // Phoenix secrets (random)
      const phoenixApiKey = new secretsmanager.Secret(this, 'PhoenixApiKeySecret', {
        secretName: `${prefix}/phoenix/api-key-secret`,
        generateSecretString: { passwordLength: 32 },
      });
      new ssm.StringParameter(this, 'PhoenixApiKey', {
        parameterName: `${prefix}/phoenix/api-key`,
        stringValue: phoenixApiKey.secretValue.unsafeUnwrap(),
        tier: ssm.ParameterTier.STANDARD,
      });

      const phoenixSecret = new secretsmanager.Secret(this, 'PhoenixSecretSecret', {
        secretName: `${prefix}/phoenix/secret-secret`,
        generateSecretString: { passwordLength: 32 },
      });
      new ssm.StringParameter(this, 'PhoenixSecret', {
        parameterName: `${prefix}/phoenix/secret`,
        stringValue: phoenixSecret.secretValue.unsafeUnwrap(),
        tier: ssm.ParameterTier.STANDARD,
      });

      const phoenixAdminSecret = new secretsmanager.Secret(this, 'PhoenixAdminSecret', {
        secretName: `${prefix}/phoenix/admin-secret-secret`,
        generateSecretString: { passwordLength: 32 },
      });
      new ssm.StringParameter(this, 'PhoenixAdminSecretParam', {
        parameterName: `${prefix}/phoenix/admin-secret`,
        stringValue: phoenixAdminSecret.secretValue.unsafeUnwrap(),
        tier: ssm.ParameterTier.STANDARD,
      });

      // Auth secrets
      const sessionSecret = new secretsmanager.Secret(this, 'SessionSecret', {
        secretName: `${prefix}/auth/session-secret-secret`,
        generateSecretString: { passwordLength: 32 },
      });
      new ssm.StringParameter(this, 'SessionSecretParam', {
        parameterName: `${prefix}/auth/session-secret`,
        stringValue: sessionSecret.secretValue.unsafeUnwrap(),
        tier: ssm.ParameterTier.STANDARD,
      });

      // Google OAuth (optional)
      new ssm.StringParameter(this, 'GoogleClientId', {
        parameterName: `${prefix}/auth/google-client-id`,
        stringValue: props.config.googleClientId,
        tier: ssm.ParameterTier.STANDARD,
      });

      new ssm.StringParameter(this, 'GoogleClientSecret', {
        parameterName: `${prefix}/auth/google-client-secret`,
        stringValue: props.config.googleClientSecret,
        tier: ssm.ParameterTier.STANDARD,
      });
    }

    // ============================================================
    // ARGOCD (Optional - deploy to app cluster or management cluster)
    // ============================================================

    if (props.config.enableArgoCD) {
      // Create argocd namespace
      const argocdNamespace = new eks.KubernetesManifest(this, 'ArgoCDNamespace', {
        cluster,
        manifest: [{
          apiVersion: 'v1',
          kind: 'Namespace',
          metadata: { name: 'argocd' },
        }],
      });
      argocdNamespace.node.addDependency(karpenterNamespace);

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
      argocd.node.addDependency(argocdNamespace);
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
