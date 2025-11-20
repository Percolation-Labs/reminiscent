#!/bin/bash
set -e

# Generate Kubernetes ConfigMaps from CDK stack outputs and REM application settings
#
# This script bridges infrastructure (CDK/CloudFormation) and application (REM settings.py)
# Only sets values that differ from application defaults
#
# Usage:
#   ./generate-configmap.sh [STACK_NAME] [NAMESPACE] [AWS_PROFILE]
#
# Examples:
#   ./generate-configmap.sh                                    # Use defaults
#   ./generate-configmap.sh REMApplicationClusterA rem rem     # Explicit values
#   ./generate-configmap.sh | kubectl apply -f -               # Apply directly
#

STACK_NAME="${1:-REMApplicationClusterA}"
NAMESPACE="${2:-rem}"
PROFILE="${3:-rem}"

echo "========================================" >&2
echo "REM ConfigMap Generator" >&2
echo "========================================" >&2
echo "Stack:     ${STACK_NAME}" >&2
echo "Namespace: ${NAMESPACE}" >&2
echo "Profile:   ${PROFILE}" >&2
echo "========================================" >&2
echo "" >&2

# Fetch stack outputs from CloudFormation
echo "Fetching stack outputs from CloudFormation..." >&2

APP_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --profile ${PROFILE} \
  --query 'Stacks[0].Outputs[?OutputKey==`AppBucketName`].OutputValue' \
  --output text 2>/dev/null || echo "")

QUEUE_URL=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --profile ${PROFILE} \
  --query 'Stacks[0].Outputs[?OutputKey==`FileProcessingQueueUrl`].OutputValue' \
  --output text 2>/dev/null || echo "")

PG_BACKUP_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --profile ${PROFILE} \
  --query 'Stacks[0].Outputs[?OutputKey==`PGBackupBucketName`].OutputValue' \
  --output text 2>/dev/null || echo "")

CLUSTER_NAME=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --profile ${PROFILE} \
  --query 'Stacks[0].Outputs[?OutputKey==`ClusterName`].OutputValue' \
  --output text 2>/dev/null || echo "")

VPC_ID=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --profile ${PROFILE} \
  --query 'Stacks[0].Outputs[?OutputKey==`VpcId`].OutputValue' \
  --output text 2>/dev/null || echo "")

# Determine environment from stack outputs or use default
ENVIRONMENT=$(aws cloudformation describe-stacks \
  --stack-name ${STACK_NAME} \
  --profile ${PROFILE} \
  --query 'Stacks[0].Tags[?Key==`Environment`].Value' \
  --output text 2>/dev/null || echo "dev")

# Validate required outputs
if [ -z "$APP_BUCKET" ] || [ -z "$CLUSTER_NAME" ]; then
  echo "ERROR: Failed to fetch required stack outputs" >&2
  echo "Ensure stack ${STACK_NAME} exists and is deployed" >&2
  exit 1
fi

echo "✅ Stack outputs retrieved successfully" >&2
echo "" >&2

# Generate ConfigMap YAML
# Note: Comments document REM settings.py defaults and why we override them
cat <<EOF
---
# ConfigMap: rem-config
# Generated from CDK stack: ${STACK_NAME}
# Overrides for REM application settings that differ from defaults
#
# REM settings.py reference:
# - S3Settings (lines 403-449): Default bucket="rem-storage", region="us-east-1"
# - OTELSettings (lines 159-207): Default enabled=false, endpoint="http://localhost:4318"
# - PhoenixSettings (lines 209-251): Default enabled=false, endpoint="http://localhost:6006/v1/traces"
# - PostgresSettings (lines 350-401): Default connection_string="postgresql://rem:rem@localhost:5050/rem"
#
apiVersion: v1
kind: ConfigMap
metadata:
  name: rem-config
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: rem
    app.kubernetes.io/component: config
    app.kubernetes.io/managed-by: generate-configmap
data:
  # ==========================================
  # S3 Settings
  # ==========================================
  # Default: rem-storage
  # Override: Infrastructure-created bucket with environment suffix
  S3__BUCKET_NAME: "${APP_BUCKET}"

  # S3__REGION defaults to "us-east-1" (no override needed)
  # S3__ACCESS_KEY_ID and S3__SECRET_ACCESS_KEY not needed (Pod Identity provides credentials)

  # ==========================================
  # OpenTelemetry Settings
  # ==========================================
  # Default: OTEL__ENABLED=false (disabled for local dev)
  # Override: Enable in cluster environment
  OTEL__ENABLED: "true"

  # Default: http://localhost:4318
  # Override: Point to OTEL collector service in observability namespace
  OTEL__COLLECTOR_ENDPOINT: "http://otel-collector.observability.svc.cluster.local:4318"

  # Default: rem-api
  # Keep default (can be overridden per deployment)
  OTEL__SERVICE_NAME: "rem-api"

  # Default: http
  # Keep default
  OTEL__PROTOCOL: "http"

  # ==========================================
  # Arize Phoenix Settings
  # ==========================================
  # Default: PHOENIX__ENABLED=false (disabled for local dev)
  # Override: Enable in cluster environment for LLM observability
  PHOENIX__ENABLED: "true"

  # Default: http://localhost:6006/v1/traces
  # Override: Point to Phoenix service in observability namespace
  PHOENIX__COLLECTOR_ENDPOINT: "http://phoenix.observability.svc.cluster.local:6006/v1/traces"

  # Default: rem
  # Keep default
  PHOENIX__PROJECT_NAME: "rem"

  # ==========================================
  # PostgreSQL Settings
  # ==========================================
  # Default: postgresql://rem:rem@localhost:5050/rem
  # Override: Point to CloudNativePG cluster service in postgres-cluster namespace
  # Note: Credentials (rem/rem) match CloudNativePG cluster bootstrap
  POSTGRES__CONNECTION_STRING: "postgresql://rem:rem@postgres-cluster-rw.postgres-cluster.svc.cluster.local:5432/rem"

  # ==========================================
  # Environment Metadata
  # ==========================================
  ENVIRONMENT: "${ENVIRONMENT}"
  CLUSTER_NAME: "${CLUSTER_NAME}"
  VPC_ID: "${VPC_ID}"

---
# ConfigMap: rem-queues
# Separate ConfigMap for queue URLs (may contain sensitive account IDs in URLs)
#
apiVersion: v1
kind: ConfigMap
metadata:
  name: rem-queues
  namespace: ${NAMESPACE}
  labels:
    app.kubernetes.io/name: rem
    app.kubernetes.io/component: queue-config
    app.kubernetes.io/managed-by: generate-configmap
data:
  FILE_PROCESSING_QUEUE_URL: "${QUEUE_URL}"

---
# ConfigMap: rem-postgres-backup
# PostgreSQL backup configuration for CloudNativePG operator
# Used by postgres-cluster namespace, not application pods
#
apiVersion: v1
kind: ConfigMap
metadata:
  name: rem-postgres-backup
  namespace: postgres-cluster
  labels:
    app.kubernetes.io/name: rem
    app.kubernetes.io/component: postgres-backup
    app.kubernetes.io/managed-by: generate-configmap
data:
  POSTGRES_BACKUP_BUCKET: "${PG_BACKUP_BUCKET}"
EOF

echo "" >&2
echo "✅ ConfigMaps generated successfully!" >&2
echo "" >&2
echo "Generated ConfigMaps:" >&2
echo "  1. rem-config (namespace: ${NAMESPACE})" >&2
echo "     - S3, OTEL, Phoenix, Postgres settings" >&2
echo "  2. rem-queues (namespace: ${NAMESPACE})" >&2
echo "     - File processing queue URLs" >&2
echo "  3. rem-postgres-backup (namespace: postgres-cluster)" >&2
echo "     - Backup bucket for CloudNativePG" >&2
echo "" >&2
echo "To apply to cluster:" >&2
echo "  ./generate-configmap.sh | kubectl apply -f -" >&2
echo "" >&2
echo "Or save to file:" >&2
echo "  ./generate-configmap.sh > application/rem-api/base/configmap.yaml" >&2
echo "" >&2
