# REM AWS Cost Analysis

AWS Account: `852140462228`
Cluster: `application-cluster-a` (EKS 1.34)
Region: `us-east-1`
Created: November 19, 2025

## Current Infrastructure (As of Nov 20, 2025)

### EKS Cluster
- **Cluster**: application-cluster-a (EKS 1.34)
- **Status**: ACTIVE (12 hours old)
- **Platform**: eks.9

### Compute Resources
**Running Nodes** (3 total):
- 2x t3.medium (on-demand) - control plane/system workloads
- 1x m6a.large (spot) - application workloads

**EBS Volumes**:
- 1x 100GB gp3 (CloudNativePG/stateful workloads)
- 1x 20GB gp2 (node storage)

### Storage
**S3 Buckets** (3 total):
- `rem-io-dev` - application uploads/parsed content (currently empty)
- `rem-io-pg-backups-dev` - PostgreSQL backups (currently empty)
- `cdk-hnb659fds-assets-*` - CDK deployment assets (minimal)

**Total S3 Storage**: ~0 GB (newly provisioned)

### Queues
**SQS Queues** (4 total):
- `application-cluster-a-file-processing-dev` - file processing queue
- `application-cluster-a-file-processing-dlq-dev` - dead letter queue
- `application-cluster-a-karpenter-interruption` - spot interruption handling
- `rem-file-processing` - legacy/test queue

### Platform Services
**Kubernetes Platform** (running in EKS):
- ArgoCD (7 pods) - GitOps continuous delivery
- Karpenter (1 pod) - dynamic node provisioning
- KEDA (3 pods) - event-driven autoscaling
- cert-manager (3 pods) - certificate management
- CloudNativePG operator (1 pod) - PostgreSQL management
- External Secrets (3 pods) - secret management

**No Application Workloads Deployed Yet**:
- rem-app namespace: empty
- postgres namespace: empty (no database cluster created)

## Current Costs (November 2025)

**Total Cost**: ~$0.00 USD (account just created)

The account is brand new (< 24 hours old) with minimal activity:
- Services are provisioned but not actively used
- No database instances running
- No S3 storage charges (empty buckets)
- SQS queues idle
- Minimal data transfer

**Expected First Month Costs** (with current setup, no workloads):
- EKS Control Plane: ~$73/month ($0.10/hour × 730 hours)
- EC2 Instances (3 nodes): ~$60/month
  - 2x t3.medium on-demand: ~$30/month ($0.0416/hour × 730 × 2)
  - 1x m6a.large spot (~70% discount): ~$30/month
- EBS Storage (120GB): ~$12/month ($0.10/GB-month)
- **Baseline Total**: ~$145/month

## Projected Costs: Development Workload

### Scenario 1: Light Development (Current + Application)

**Additional Resources**:
- CloudNativePG cluster (1 primary, 2 replicas on t3.medium)
- REM API (2-4 pods, HPA-scaled)
- File processor (0-2 pods, KEDA-scaled, spot instances)
- S3 storage: 10GB uploads, 10GB parsed
- Database: 5GB PostgreSQL

**Monthly Cost Estimate**:
```
EKS Control Plane                 $  73.00
Compute (5-7 nodes):
  - 3x t3.medium (stateful)       $  45.00
  - 2-4x m6a.large (spot)         $  40.00  (avg 3 nodes)
EBS Storage (200GB gp3)           $  20.00
S3 Storage (20GB Standard)        $   0.46
RDS/CloudNativePG (5GB)           $   0.50  (EBS-backed)
Data Transfer (minimal)           $   5.00
SQS Requests (1M/month)           $   0.40
NAT Gateway (minimal)             $  10.00
CloudWatch Logs                   $   5.00
Secrets Manager                   $   2.00
-----------------------------------------
TOTAL                             $ 201.36/month
```

### Scenario 2: Production Workload with Scale

**Assumptions**:
- CloudNativePG cluster: 1 primary + 2 replicas (100GB each)
- REM API: HPA 2-10 replicas (avg 4)
- File processor: KEDA 0-20 replicas (avg 5, spot instances)
- S3 storage: **1TB uploads, 500GB parsed** (1.5TB total)
- Database: **100GB PostgreSQL**
- Higher traffic, data transfer, API calls

**Monthly Cost Estimate**:
```
EKS Control Plane                 $   73.00
Compute (15-20 nodes):
  - 5x t3.medium (stateful/system) $   75.00
  - 10-15x m6a.large (spot apps)   $  150.00  (avg 12 nodes)
EBS Storage:
  - 300GB gp3 (CloudNativePG)      $   30.00
  - 500GB gp3 (nodes, logs)        $   50.00
S3 Storage:
  - 1TB Standard (uploads)         $   23.00  ($0.023/GB)
  - 500GB Intelligent-Tier         $   11.50  (parsed, auto-archived)
S3 Requests:
  - 10M PUT (uploads)              $   50.00
  - 100M GET (retrieval)           $   40.00
Database (CloudNativePG):
  - 300GB EBS (100GB × 3 replicas) $   30.00
Data Transfer:
  - 500GB outbound                 $   45.00
  - 200GB inter-AZ                 $   20.00
SQS Requests (100M/month)         $   40.00
NAT Gateway (production)          $   45.00
CloudWatch Logs (10GB/month)      $   15.00
Secrets Manager (10 secrets)      $    5.00
KMS (key operations)              $    3.00
ALB/NLB (if added)                $   20.00
-----------------------------------------
SUBTOTAL                          $  725.50/month
```

### Scenario 3: Optimized Production (Cost-Saving Measures)

**Optimizations Applied**:
- S3 Intelligent-Tiering for all storage (auto-archive to Glacier)
- Savings Plans for EC2 (1-year, no upfront): 20% discount
- Reserved capacity for stateful nodes
- gp3 with optimized IOPS/throughput settings
- CloudWatch log retention policies (7 days for debug, 30 days for audit)
- KEDA scale-to-zero for file processors during off-hours

**Monthly Cost Estimate**:
```
EKS Control Plane                 $   73.00
Compute (12-15 nodes, optimized):
  - 5x t3.medium (reserved)        $   60.00  (20% savings)
  - 10x m6a.large (spot + savings) $  120.00  (spot + 20% base savings)
EBS Storage (800GB gp3, optimized) $   80.00
S3 Storage (1.5TB Intelligent-Tier):
  - Frequent Access Tier           $   15.00  (first month, 60% infrequent)
  - Infrequent Access Tier         $    5.00
  - Archive Tier (auto)            $    2.00
S3 Requests (reduced via caching):
  - 5M PUT                         $   25.00
  - 50M GET                        $   20.00
Database (optimized):
  - 300GB gp3 (optimized IOPS)     $   25.00
Data Transfer (CDN offload):
  - 300GB outbound                 $   27.00
  - 100GB inter-AZ                 $   10.00
SQS Requests (100M/month)         $   40.00
NAT Gateway (single AZ)           $   32.00
CloudWatch (optimized retention)  $    8.00
Secrets Manager                   $    5.00
-----------------------------------------
SUBTOTAL                          $  547.00/month

Savings Plans (1-year discount)   -$  36.00
-----------------------------------------
TOTAL                             $  511.00/month
```

## Cost Breakdown by Service (Optimized Production)

| Service | Monthly Cost | % of Total | Notes |
|---------|-------------|-----------|-------|
| **Compute (EC2/EKS)** | $253 | 49% | Largest cost driver, optimized with spot + savings |
| **Storage (EBS + S3)** | $127 | 25% | Intelligent-Tiering saves ~40% on S3 |
| **Data Transfer** | $69 | 14% | Consider CloudFront CDN for static assets |
| **SQS + Queuing** | $40 | 8% | Scales with file processing volume |
| **Other Services** | $22 | 4% | CloudWatch, Secrets, NAT Gateway |

## Cost Comparison: Database Options

### CloudNativePG (Current Architecture)
**Pros**:
- ✅ Full control over PostgreSQL 18 + pgvector
- ✅ Immutable extension pattern
- ✅ Lower cost ($25-30/month for 100GB with replicas)
- ✅ Integrated with Kubernetes ecosystem
- ✅ High availability built-in

**Cons**:
- ❌ Requires EBS storage (but cheaper than RDS)
- ❌ Manual backup management (automated via WAL-G to S3)

**Monthly Cost** (100GB, 3 replicas):
```
EBS Storage: 300GB gp3 × $0.08/GB    $  24.00
Backup Storage: 100GB S3             $   2.30
Compute: Included in node costs      $   0.00
-----------------------------------------
TOTAL                                $  26.30/month
```

### RDS PostgreSQL (Alternative)
**Pros**:
- ✅ Fully managed (backups, updates, monitoring)
- ✅ Easy to scale storage
- ✅ Multi-AZ high availability

**Cons**:
- ❌ 3-4x more expensive than CloudNativePG
- ❌ Limited control over PostgreSQL config
- ❌ pgvector extension support depends on version

**Monthly Cost** (100GB, Multi-AZ):
```
db.t3.medium Multi-AZ                $  73.00
Storage: 100GB gp3                   $  12.00
Backup Storage: 100GB                $  10.00
-----------------------------------------
TOTAL                                $  95.00/month
```

**Recommendation**: CloudNativePG for REM. Saves ~$70/month with more flexibility.

## Cost Optimization Strategies

### Immediate Actions (0-30 days)
1. **Enable S3 Intelligent-Tiering**
   - Automatically moves infrequently accessed data to cheaper tiers
   - Savings: 40-60% on storage costs after 30 days
   ```bash
   aws s3api put-bucket-intelligent-tiering-configuration \
     --bucket rem-io-dev \
     --id AutoArchive \
     --intelligent-tiering-configuration '{...}'
   ```

2. **Configure S3 Lifecycle Policies**
   - Move parsed content to Glacier after 90 days
   - Delete temporary files after 7 days
   - Savings: $10-20/month on 1TB

3. **Enable gp3 for All EBS Volumes**
   - 20% cheaper than gp2
   - Baseline 3000 IOPS included (vs 300 IOPS on gp2)
   - Savings: $2-5/month per 100GB

4. **Implement KEDA Scale-to-Zero**
   - File processors scale to 0 when idle
   - Savings: 50% on spot instance costs during off-hours

### Medium-Term (30-90 days)
1. **Purchase EC2 Savings Plans**
   - 1-year, no upfront: 20% discount
   - 3-year, no upfront: 40% discount
   - Applies to stateful t3.medium nodes
   - Savings: $15-30/month (20% of $75-150)

2. **Implement CloudFront CDN**
   - Cache static assets and parsed content
   - Reduce S3 GET requests (90% reduction possible)
   - Reduce data transfer costs
   - Savings: $20-40/month on high-traffic workloads

3. **Optimize CloudWatch Logs**
   - 7-day retention for debug logs
   - 30-day retention for audit logs
   - Export to S3 for long-term storage
   - Savings: $5-10/month

### Long-Term (90+ days)
1. **Reserved Capacity for Stateful Nodes**
   - 1-year reserved instances for PostgreSQL nodes
   - Savings: 30-40% on stateful compute

2. **Multi-Region Replication (Future)**
   - S3 Cross-Region Replication only for critical data
   - Cost: +$50-100/month for disaster recovery

## Scaling Projections

### Users/Traffic to Cost Mapping

| Users | API Requests/Day | Files Processed/Day | S3 Storage | DB Size | Monthly Cost |
|-------|------------------|---------------------|------------|---------|--------------|
| 10 (dev) | 1K | 10 | 10GB | 5GB | ~$200 |
| 100 | 10K | 100 | 100GB | 20GB | ~$300 |
| 1,000 | 100K | 1,000 | 500GB | 50GB | ~$450 |
| 10,000 | 1M | 10,000 | 1TB | 100GB | ~$700 |
| 10,000 (optimized) | 1M | 10,000 | 1TB | 100GB | **~$511** |

### Compute Scaling
**Karpenter Autoscaling** (based on CPU/memory utilization):
- Min: 3 nodes (control plane)
- Max: 50 nodes (safety limit)
- Typical: 12-15 nodes at scale
- Spot instances for 80% of application workloads

**KEDA Autoscaling** (based on SQS queue depth):
- File processors: 0-20 replicas
- Scales to zero when queue empty
- Typical: 2-5 active during business hours

## Monitoring & Alerts

### Cost Anomaly Detection
```bash
# Set up AWS Cost Anomaly Detection
aws ce update-anomaly-subscription \
  --subscription-arn arn:aws:ce::852140462228:anomalysubscription/rem-cost-alerts \
  --threshold-expression '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Elastic Compute Cloud - Compute","Amazon Simple Storage Service"]}}' \
  --monitor-arn arn:aws:ce::852140462228:anomalymonitor/rem-monitor
```

### Budget Alerts
**Recommended Budgets**:
- Development: $300/month (current baseline + 50%)
- Production: $600/month (with room for spikes)
- Alert at 80%, 90%, 100% of budget

### Key Metrics to Track
1. **EC2 Spot Instance Interruptions** - target < 5% interruption rate
2. **S3 Storage Growth Rate** - monitor for data accumulation
3. **SQS Queue Depth** - detect processing bottlenecks
4. **Database Storage Growth** - plan for expansion
5. **Data Transfer Costs** - largest variable cost

## Summary

### Current State (Nov 20, 2025)
- Cluster operational with platform services only
- No application workloads deployed yet
- Current cost: ~$145/month (baseline infrastructure)
- All services provisioned and ready for deployment

### Projected Production Cost
- **Unoptimized**: ~$725/month
- **Optimized**: ~$511/month
- **Cost per user** (10K users): ~$0.05/user/month

### Key Cost Drivers
1. **Compute** (49%): EC2 instances for EKS
2. **Storage** (25%): S3 + EBS for database and files
3. **Data Transfer** (14%): Bandwidth costs
4. **Queue Processing** (8%): SQS message costs

### Optimization Impact
- S3 Intelligent-Tiering: **-$15-20/month** (-40% storage)
- Savings Plans: **-$36/month** (-20% compute)
- KEDA Scale-to-Zero: **-$30/month** (-50% off-hours compute)
- gp3 Migration: **-$10/month** (-20% EBS)
- **Total Savings**: **-$91-96/month** (-15% total cost)

### Next Steps
1. ✅ Infrastructure provisioned and validated
2. ⏭️ Deploy REM application to rem-app namespace
3. ⏭️ Create CloudNativePG cluster in postgres namespace
4. ⏭️ Enable S3 Intelligent-Tiering on rem-io-dev bucket
5. ⏭️ Set up cost alerts and budgets
6. ⏭️ Monitor actual vs projected costs over first 30 days

---

**Cost Analysis Date**: November 20, 2025
**Infrastructure Age**: 12 hours
**AWS Account**: 852140462228 (rem profile)
**Estimated Monthly Run Rate**: $511/month (optimized production)
