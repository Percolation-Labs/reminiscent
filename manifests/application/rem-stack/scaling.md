# REM Stack Scaling Guide

This document describes the autoscaling behavior of the REM stack components.

## Overview

The REM stack uses multiple autoscaling mechanisms:

1. **HPA (Horizontal Pod Autoscaler)** - Scales the API based on CPU/memory
2. **KEDA** - Scales the file-processor worker based on SQS queue depth
3. **Karpenter** - Provisions nodes based on pod requirements

## API Autoscaling (HPA)

**Component**: `rem-api`  
**Manifest**: `components/api/hpa.yaml`

### Configuration

```yaml
minReplicas: 2
maxReplicas: 10
targetCPUUtilizationPercentage: 70
targetMemoryUtilizationPercentage: 80
```

### Behavior

- **Scale Up**: When CPU > 70% OR memory > 80%
  - Adds pods gradually to handle increased load
  - Max 4 pods can be added per 15-second window
  
- **Scale Down**: When CPU < 70% AND memory < 80%
  - Removes pods cautiously to avoid flapping
  - Max 1 pod removed per 5-minute window
  - 5-minute stabilization window before scaling down

### Monitoring

```bash
# Check current scaling status
kubectl get hpa rem-api -n rem-api

# View scaling events
kubectl describe hpa rem-api -n rem-api

# Watch replica count
kubectl get deployment rem-api -n rem-api -w
```

## Worker Autoscaling (KEDA)

**Component**: `file-processor`  
**Manifest**: `components/worker/keda-scaledobject.yaml`

### Configuration

```yaml
minReplicaCount: 0      # Scale to zero when idle
maxReplicaCount: 20     # Max 20 worker pods
pollingInterval: 10     # Check queue every 10 seconds
cooldownPeriod: 60      # Wait 60s before scaling down
queueLength: "10"       # Target: 1 pod per 10 messages
```

### Behavior

- **Scale Up**: When SQS messages accumulate
  - Target ratio: 1 pod per 10 messages
  - Example: 100 messages → 10 pods, 200 messages → 20 pods (capped)
  - Aggressive scaling: doubles pods every 15 seconds OR adds 4 pods (whichever is more)
  - No stabilization window (scales immediately)

- **Scale Down**: When SQS queue drains
  - Scales down to 0 when queue is empty (cost optimization)
  - Conservative scaling: max 50% reduction per minute
  - 5-minute stabilization window to avoid flapping

- **Scale to Zero**: When queue empty for 60+ seconds
  - Workers shut down gracefully (45s termination grace period)
  - No compute costs when idle
  - Scales back up automatically when messages arrive

### SQS Queue Configuration

**Queue Name**: `rem-file-processing`  
**Region**: `us-east-1`  
**URL**: `https://sqs.us-east-1.amazonaws.com/852140462228/rem-file-processing`

**Settings**:
- Message retention: 14 days (1209600 seconds)
- Visibility timeout: 5 minutes (300 seconds)
- Long polling: 20 seconds (reduces empty receives)

### Authentication

KEDA uses **Pod Identity (IRSA)** to access SQS:

1. KEDA operator service account (`keda/keda-operator`) is annotated with IAM role ARN
2. IAM role (`rem-api-role`) has trust policy allowing OIDC web identity
3. IAM role has inline policy granting SQS permissions:
   - `sqs:GetQueueAttributes` - Check queue depth
   - `sqs:ReceiveMessage` - Workers read messages
   - `sqs:DeleteMessage` - Workers delete after processing
   - `sqs:GetQueueUrl` - Resolve queue URL

### Monitoring

```bash
# Check KEDA scaler status
kubectl get scaledobject file-processor-scaler -n rem-api

# View scaling events
kubectl describe scaledobject file-processor-scaler -n rem-api

# Check current replica count
kubectl get deployment file-processor -n rem-api

# Watch pods scale up/down
kubectl get pods -n rem-api -l app=file-processor -w

# Check SQS queue depth
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-1.amazonaws.com/852140462228/rem-file-processing \
  --attribute-names ApproximateNumberOfMessages

# View KEDA operator logs
kubectl logs -n keda -l app.kubernetes.io/name=keda-operator --tail=50
```

## Node Autoscaling (Karpenter)

**Component**: Karpenter NodePools  
**Manifests**: `manifests/infra/eks-yaml/karpenter-nodepools.yaml`

### NodePools

#### 1. Stateless Pool (API + Workers)

**Name**: `stateless`  
**Capacity Type**: Spot (cost-optimized)  
**Instance Categories**: c, m, r (compute/general/memory optimized)  
**Sizes**: large, xlarge, 2xlarge

**Scaling Behavior**:
- Provisions nodes when pods are pending
- Consolidates underutilized nodes (WhenEmptyOrUnderutilized)
- Prefers Spot instances (up to 100% savings)
- Tolerates spot interruptions (15-120 second warnings)

**Use Cases**:
- rem-api pods (prefer via node affinity)
- file-processor pods (prefer via node affinity)

#### 2. Stateful Pool (Database)

**Name**: `stateful`  
**Capacity Type**: On-Demand (stability)  
**Instance Categories**: r, m (memory/general optimized)  
**Sizes**: large, xlarge, 2xlarge

**Scaling Behavior**:
- Provisions nodes for CloudNativePG pods
- Never uses Spot (data durability)
- Conservative consolidation (only when empty)

**Use Cases**:
- PostgreSQL primary and replicas
- Persistent data workloads

### Monitoring

```bash
# Check node capacity
kubectl get nodes -o wide

# View Karpenter provisioner logs
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=50

# Check node allocatable resources
kubectl describe nodes | grep -A 5 "Allocatable"

# View pending pods (trigger for scaling)
kubectl get pods -A --field-selector=status.phase=Pending
```

## Testing Autoscaling

### Test API Scaling (HPA)

Generate load to trigger CPU-based scaling:

```bash
# Run load test (requires hey or similar tool)
hey -z 60s -c 50 https://your-api-domain.com/health

# Watch scaling
kubectl get hpa rem-api -n rem-api -w
```

### Test Worker Scaling (KEDA)

Send messages to SQS to trigger worker scaling:

```bash
# Send 100 test messages
for i in {1..100}; do
  aws sqs send-message \
    --queue-url https://sqs.us-east-1.amazonaws.com/852140462228/rem-file-processing \
    --message-body '{"file_key": "test-file-'$i'.pdf", "bucket": "rem-api-bucket"}' \
    --region us-east-1
done

# Watch workers scale up
kubectl get deployment file-processor -n rem-api -w

# Expected: 100 messages / 10 messages per pod = 10 pods
kubectl get pods -n rem-api -l app=file-processor
```

Wait for workers to process messages (they'll fail since the S3 files don't exist, but will scale down after visibility timeout):

```bash
# Watch scale down to zero after queue empties
kubectl get scaledobject file-processor-scaler -n rem-api -w
```

### Test Node Scaling (Karpenter)

Scale workers beyond node capacity to trigger node provisioning:

```bash
# Send many messages to force worker scaling
for i in {1..500}; do
  aws sqs send-message \
    --queue-url https://sqs.us-east-1.amazonaws.com/852140462228/rem-file-processing \
    --message-body '{"file_key": "test-file-'$i'.pdf"}' \
    --region us-east-1 &
done
wait

# Expected: 500 messages / 10 = 50 pods (but capped at maxReplicas: 20)
# Watch Karpenter provision new nodes
kubectl get nodes -w

# Check pending pods
kubectl get pods -n rem-api -l app=file-processor --field-selector=status.phase=Pending
```

## Scaling Metrics

### Key Metrics to Monitor

1. **API Response Time** (p50, p95, p99)
   - Target: p95 < 500ms
   - Scale up if consistently > 500ms

2. **SQS Queue Depth** (ApproximateNumberOfMessages)
   - Target: < 100 messages (< 10 pods)
   - Alert if > 200 messages (indicates backlog)

3. **Worker Processing Rate** (messages/second per pod)
   - Monitor via CloudWatch or OTEL traces
   - Adjust `queueLength` target if needed

4. **Node Utilization** (CPU/Memory)
   - Target: 60-80% utilization
   - Karpenter consolidates below 60%

5. **Pod Churn Rate** (restarts, evictions)
   - Target: < 1 restart per hour
   - High churn indicates instability

## Cost Optimization

### Estimated Costs (us-east-1)

**API (On-Demand)**:
- 2 replicas minimum × $0.0464/hour (m5.large) = $68/month base cost
- Auto-scales to 10 replicas during peak = $340/month peak cost

**Workers (Spot)**:
- 0 replicas when idle = $0/month base cost
- 20 replicas max × $0.0139/hour (c5.large Spot, 70% savings) = $205/month peak cost
- Typical usage: 2-3 replicas average = $20-30/month

**Database (On-Demand)**:
- 1 primary + 1 replica × $0.192/hour (r5.large) = $283/month fixed cost

**Total Monthly Cost**:
- Base (idle): ~$351/month (API + database)
- Average: ~$400/month (with moderate worker activity)
- Peak: ~$828/month (all components at max)

### Optimization Tips

1. **Scale to Zero**: Workers scale to 0 when idle (already configured)
2. **Spot Instances**: Workers use Spot (70%+ savings, already configured)
3. **Right-sizing**: Monitor actual usage and adjust resource requests
4. **Reserved Instances**: Consider RIs for database if usage is predictable
5. **Consolidation**: Karpenter automatically consolidates underutilized nodes

## Troubleshooting

### Workers Not Scaling Up

Check KEDA status:
```bash
kubectl describe scaledobject file-processor-scaler -n rem-api
```

Common issues:
- READY: False → Check KEDA operator logs for auth errors
- ACTIVE: False → Queue might be empty or unreachable
- TriggerAuthentication missing → Apply `triggerauthentication.yaml`

### API Not Scaling

Check HPA status:
```bash
kubectl describe hpa rem-api -n rem-api
```

Common issues:
- Metrics unavailable → Check metrics-server is running
- CPU/Memory unknown → Pods may not have resource requests defined
- Scale up/down disabled → Check HPA behavior configuration

### Nodes Not Scaling

Check Karpenter logs:
```bash
kubectl logs -n karpenter -l app.kubernetes.io/name=karpenter --tail=100
```

Common issues:
- Pod scheduling constraints too restrictive (node affinity, tolerations)
- No matching NodePool for pod requirements
- AWS service quotas reached (EC2 instance limits)

## Further Reading

- [KEDA SQS Scaler Documentation](https://keda.sh/docs/latest/scalers/aws-sqs/)
- [Kubernetes HPA Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Karpenter Best Practices](https://karpenter.sh/docs/concepts/)
