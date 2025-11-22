# Postmortem: API Gateway Outage (Jan 12, 2025)

**Incident ID**: INC-2025-001
**Severity**: P1 (Customer-impacting)
**Duration**: 2 hours 15 minutes (10:30 AM - 12:45 PM PST)
**Author**: Sarah Chen
**Reviewers**: Mike Rodriguez, DevOps Team

## Summary
API Gateway experienced complete outage affecting all customer traffic. Root cause: Memory leak in authentication middleware introduced in v2.14.0 deployment.

## Impact
- **Customer Impact**: 100% of API requests failed (503 errors)
- **Revenue Impact**: Est. $45K in lost transactions
- **User Impact**: ~15,000 users unable to access service
- **Reputation**: 247 support tickets, negative social media mentions

## Timeline (All times PST)

**10:15 AM** - v2.14.0 deployed to production (gradual rollout)
**10:30 AM** - PagerDuty alert: API Gateway CPU at 95%
**10:32 AM** - Sarah joins incident channel, declares P1
**10:35 AM** - Traffic shifted to backup region (partial recovery)
**10:45 AM** - Memory leak identified in auth middleware
**11:00 AM** - Rollback initiated to v2.13.2
**11:20 AM** - Rollback complete, pods restarting
**11:45 AM** - Service recovery to 50% capacity
**12:45 PM** - Full recovery confirmed, incident resolved

## Root Cause

### Technical Details
```javascript
// Bug in authentication middleware (v2.14.0)
function authenticateRequest(req, res, next) {
  const cache = new Map(); // ❌ Created on every request!
  // ... authentication logic
  // cache never cleared - accumulated in memory
}
```

### How It Happened
1. New engineer (Alice) refactored auth middleware
2. Code review focused on logic, missed memory issue
3. Load testing performed but with unrealistic traffic pattern
4. Gradual rollout caught issue early, limited blast radius

## Resolution
1. Immediate rollback to v2.13.2 (known stable version)
2. Pod restarts to clear memory
3. Traffic gradually restored
4. Post-recovery monitoring (24 hours)

## Prevention Measures

### Immediate Actions (This Week)
- [ ] Add memory profiling to load testing suite
- [ ] Implement memory leak detection in CI pipeline
- [ ] Update code review checklist for resource management
- [ ] Add automated alerting for memory growth patterns

### Short-term (This Month)
- [ ] Improve load testing to match production traffic patterns
- [ ] Add chaos engineering tests (random pod kills)
- [ ] Circuit breaker for auth service
- [ ] Runbook for memory-related incidents

### Long-term (This Quarter)
- [ ] Horizontal pod autoscaling based on memory (not just CPU)
- [ ] Implement resource quotas per namespace
- [ ] Advanced observability with continuous profiling
- [ ] Engineering training on performance best practices

## Lessons Learned

### What Went Well
- Fast incident detection (2 minutes)
- Clear escalation process
- Backup region failover worked
- Team collaboration excellent

### What Needs Improvement
- Load testing didn't catch this
- Code review process missed resource leak
- Rollback took too long (20 minutes)
- Customer communication delayed

### Action Items
- **Sarah**: Update load testing requirements [Jan 15]
- **Mike**: Add memory leak checks to CI [Jan 18]
- **Alice**: Pair with senior eng on code review process [Jan 16]
- **DevOps**: Improve rollback automation [Jan 22]
- **PM (Jordan)**: Customer communication playbook [Jan 20]

## Related Incidents
- INC-2024-087: Similar memory issue in user service (Dec 2024)
- INC-2024-034: Database connection pool leak (Aug 2024)

Pattern emerging: Resource management needs org-wide focus.

## Appendix

### Monitoring Graphs
- CPU usage spike: 10:30-11:20 AM
- Memory growth: Linear from 10:15 AM
- Error rate: 0% → 100% in 15 minutes

### Customer Communication
- Status page updated: 10:40 AM
- Email to enterprise customers: 11:00 AM
- Postmortem published: Jan 13 (next day)
