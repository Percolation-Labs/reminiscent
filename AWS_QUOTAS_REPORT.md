# AWS Quotas Report & Recommendations

**Account ID**: 852140462228
**Region**: us-east-1
**Date**: 2025-11-19

## Current Quota Status

### ⚠️ CRITICAL - Below Minimum Requirements

| Service | Quota | Current | Required | Status |
|---------|-------|---------|----------|--------|
| **EC2 On-Demand Standard vCPUs** | L-1216C47A | **5** | **64** | ✅ **REQUESTED** |

### ✅ Adequate for Small Cluster

| Service | Quota | Current | Notes |
|---------|-------|---------|-------|
| **EKS Clusters** | L-1194D53C | 100 | Sufficient |
| **EKS Managed Node Group Nodes** | L-BD136A63 | 450 | Sufficient |
| **VPCs per Region** | L-F678F1CE | 5 | Sufficient |
| **NAT Gateways per AZ** | L-FE5A380F | 5 | Sufficient (need 3) |

## Infrastructure Requirements

### Minimum for REM Cluster (Small)

**Karpenter Controller Nodes**:
- 2x t3.medium (on-demand) = 4 vCPUs

**Initial Workload Nodes** (via Karpenter):
- 2x t3.large (on-demand/spot) = 4 vCPUs
- Total: **8 vCPUs minimum**

**Network Infrastructure**:
- 1 VPC
- 3 NAT Gateways (one per AZ)
- 3 Elastic IPs

### Recommended for Testing Full Stack

**Karpenter Controller**:
- 2x t3.medium = 4 vCPUs

**Application Workloads**:
- 4x t3.large = 16 vCPUs (API, workers, databases)
- 2x t3.xlarge = 8 vCPUs (burst capacity)
- Total: **28 vCPUs minimum**

**Recommended quota**: **64 vCPUs** (requested)

## Quota Increase Request Status

### ✅ Submitted Requests

1. **EC2 On-Demand Standard vCPUs**
   - Request ID: `9191ecba0d364ec78388a4071c9fa804Ya0W7JBS`
   - Current: 5 vCPUs
   - Requested: 64 vCPUs
   - Status: **PENDING**
   - Typical approval time: **15 minutes - 2 hours** (automatic for standard quotas)

## Cost Estimates

### Minimum Cluster (8 vCPUs)

| Component | Configuration | Monthly Cost (USD) |
|-----------|--------------|-------------------|
| EKS Control Plane | 1 cluster | $73 |
| Karpenter Controller | 2x t3.medium on-demand | ~$60 |
| Workload Nodes | 2x t3.large (50% spot) | ~$30 |
| NAT Gateways | 3x NAT GW | ~$97 |
| Data Transfer | Estimated | ~$20 |
| **Total** | | **~$280/month** |

### Full Stack Testing (28 vCPUs)

| Component | Configuration | Monthly Cost (USD) |
|-----------|--------------|-------------------|
| EKS Control Plane | 1 cluster | $73 |
| Karpenter Controller | 2x t3.medium on-demand | ~$60 |
| Application Nodes | 4x t3.large (50% spot) | ~$60 |
| Database Nodes | 2x r6i.xlarge on-demand | ~$340 |
| NAT Gateways | 3x NAT GW | ~$97 |
| Data Transfer | Estimated | ~$50 |
| **Total** | | **~$680/month** |

### Cost Optimization Strategies

1. **Use Spot Instances** (Up to 90% savings)
   - General-purpose workloads: 80% spot, 20% on-demand
   - Saves ~$150-300/month

2. **Enable Karpenter Consolidation**
   - Automatically removes underutilized nodes
   - Saves ~10-20% on compute costs

3. **Development Schedule**
   - Shut down cluster outside working hours
   - Saves ~50% if running 8hrs/day, 5 days/week

4. **Single NAT Gateway** (dev/test only)
   - Use 1 NAT instead of 3
   - Saves ~$65/month
   - ⚠️ **NOT recommended for production**

## Next Steps

### Immediate Actions

1. **Wait for Quota Approval** (15 min - 2 hours)
   ```bash
   # Check request status
   aws service-quotas get-requested-service-quota-change \
     --request-id 9191ecba0d364ec78388a4071c9fa804Ya0W7JBS \
     --profile rem \
     --region us-east-1
   ```

2. **Deploy Minimal Cluster First**
   - Deploy just VPC + EKS + Karpenter controller (4 vCPUs)
   - Verify everything works
   - Then scale up workloads

3. **Set Up Billing Alerts**
   ```bash
   # Create CloudWatch alarm for $100/month threshold
   aws cloudwatch put-metric-alarm \
     --alarm-name rem-billing-alert-100 \
     --alarm-description "Alert when charges exceed $100" \
     --metric-name EstimatedCharges \
     --namespace AWS/Billing \
     --statistic Maximum \
     --period 21600 \
     --evaluation-periods 1 \
     --threshold 100 \
     --comparison-operator GreaterThanThreshold \
     --profile rem \
     --region us-east-1
   ```

### After Quota Approval

1. **Deploy Infrastructure**
   ```bash
   cd manifests/infra/eks
   source venv/bin/activate
   export AWS_PROFILE=rem
   export PULUMI_CONFIG_PASSPHRASE=""
   pulumi up
   ```

2. **Monitor Costs**
   - AWS Cost Explorer: Track daily spend
   - Set up budget alerts
   - Review costs weekly

3. **Scale Testing**
   - Start with 2 nodes (Karpenter controller only)
   - Deploy test workloads
   - Let Karpenter scale automatically
   - Monitor node utilization

## Recommended Configuration Changes

### For Cost-Conscious Testing

Update `__main__.py` to use smaller instances:

```python
# Karpenter controller (keep as-is)
instance_types=["t3.small"],  # Change from t3.medium
desired_size=1,  # Change from 2 (single node during testing)
min_size=1,
max_size=1,

# In karpenter_resources.py - General Purpose NodePool
"values": ["small", "medium", "large"],  # Remove xlarge/2xlarge
```

### Monthly Budget Recommendations

- **Development/Testing**: $300-500/month
- **Staging**: $500-1000/month
- **Production**: $1000-3000+/month

## Free Tier Notes

AWS Free Tier does NOT include:
- ❌ EKS Control Plane ($73/month - no free tier)
- ❌ NAT Gateways (~$32/month each - no free tier)
- ✅ EC2 t2.micro/t3.micro (750 hours/month for 12 months)
- ✅ Some data transfer (100GB/month)

**Bottom line**: Minimum cost is ~$200/month due to EKS + NAT gateways.

## Monitoring Quota Usage

```bash
# Check current vCPU usage
aws cloudwatch get-metric-statistics \
  --namespace AWS/Usage \
  --metric-name ResourceCount \
  --dimensions Name=Class,Value=Standard/OnDemand Name=Resource,Value=vCPU Name=Service,Value=EC2 Name=Type,Value=Resource \
  --statistics Maximum \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 \
  --profile rem \
  --region us-east-1
```

## Support & Escalation

If quota increase is denied or delayed:

1. **AWS Support** (if you have a support plan)
   - Create a support case requesting quota increase
   - Explain use case (development/testing EKS cluster)

2. **Alternative Regions**
   - Try us-west-2 or eu-west-1
   - Some regions have higher default quotas

3. **Instance Type Alternatives**
   - Use t2 instances instead of t3 (older generation, may have higher quotas)
   - Use t3a (AMD) instead of t3 (Intel)

## References

- [AWS Service Quotas Documentation](https://docs.aws.amazon.com/servicequotas/latest/userguide/intro.html)
- [EC2 Instance Types](https://aws.amazon.com/ec2/instance-types/)
- [EKS Pricing](https://aws.amazon.com/eks/pricing/)
- [AWS Cost Calculator](https://calculator.aws/)
