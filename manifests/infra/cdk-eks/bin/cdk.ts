#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { SharedResourcesStack } from '../lib/shared-resources-stack';
import { ManagementClusterStack } from '../lib/management-cluster-stack';
import { WorkerClusterStack } from '../lib/worker-cluster-stack';
import { loadConfig, printConfig } from '../lib/config';

const app = new cdk.App();

// Load configuration from environment variables and .env file
const config = loadConfig();
printConfig(config);

// AWS Account and Region
// IMPORTANT: Set AWS_REGION environment variable to deploy to specific region
// Example: export AWS_REGION=eu-central-1
// Available EU regions with EIP quota: eu-central-1, eu-west-2, eu-north-1
// Default: eu-west-1 (has limited EIP quota - 4/5 used)
const env = {
  account: config.account,
  region: config.region,
};

// Shared resources (ECR, IAM roles, etc.)
const sharedStack = new SharedResourcesStack(app, 'REMSharedResources', {
  env,
  description: 'Shared resources for nShift EKS clusters (ECR, IAM)',
});

// Management cluster for ArgoCD and GitOps
// Note: Uses 1 NAT gateway by default for testing (saves $64/month + 2 EIPs)
// For production HA, pass natGateways: 3
const mgmtStack = new ManagementClusterStack(app, 'REMManagementCluster', {
  env,
  description: 'Management cluster with ArgoCD for GitOps',
  ecrRepository: sharedStack.apiRepository,
  config,
  // natGateways: 1, // Default, can set to 3 for production HA
});

// Application cluster A
const appClusterA = new WorkerClusterStack(app, 'REMApplicationClusterA', {
  env,
  description: `Application cluster for ${config.environment} workloads`,
  clusterName: 'application-cluster-a',
  environment: config.environment,
  ecrRepository: sharedStack.apiRepository,
  config,
});

// Uncomment to create production worker cluster
// const workerStackB = new WorkerClusterStack(app, 'REMWorkerClusterB', {
//   env,
//   description: 'Worker cluster for production workloads',
//   clusterName: 'worker-cluster-b',
//   environment: 'production',
//   ecrRepository: sharedStack.apiRepository,
//   config,
// });

// Tags for all resources
cdk.Tags.of(app).add('Project', 'REM');
cdk.Tags.of(app).add('ManagedBy', 'CDK');
cdk.Tags.of(app).add('Environment', 'Platform');

app.synth();
