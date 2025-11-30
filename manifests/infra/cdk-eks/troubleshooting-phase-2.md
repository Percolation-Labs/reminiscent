# CDK EKS Deployment Troubleshooting - Phase 2

This document captures issues encountered during the CDK EKS deployment session and their resolutions.

## Issues Encountered

### 1. ALB Controller Webhook Timing Issue

**Error:**
```
failed calling webhook "mservice.elbv2.k8s.aws": no endpoints available for service "aws-load-balancer-webhook-service"
```

**Cause:** ArgoCD Helm chart tried to install before ALB Controller pods were ready. The webhook had no endpoints available.

**Solution:**
1. Add `wait: true` to ALB Controller HelmChart - makes Helm wait for pods to be ready
2. Add `argocd.node.addDependency(albController)` - ensures ArgoCD waits for ALB Controller

```typescript
const albController = new eks.HelmChart(this, 'ALBController', {
  // ...
  wait: true,  // Wait for pods to be ready before marking complete
});

// ArgoCD depends on ALB Controller
argocd.node.addDependency(albController);
```

**Best Practice:** Use `wait: true` for any Helm chart that installs webhooks or CRDs that other resources depend on.

### 2. SSM Parameter EarlyValidation Conflict

**Error:**
```
AWS::EarlyValidation::ResourceExistenceCheck - SSM parameter already exists
```

**Cause:** CloudFormation's new November 2025 EarlyValidation feature detects existing resources before deployment starts.

**Solution:** Use `AwsCustomResource` with `PutParameter` and `Overwrite: true` instead of native `ssm.StringParameter`:

```typescript
const putSsmParameter = (id: string, parameterName: string, value: string, description: string) => {
  return new cr.AwsCustomResource(this, id, {
    onCreate: {
      service: 'SSM',
      action: 'putParameter',
      parameters: {
        Name: parameterName,
        Value: value,
        Type: 'String',
        Overwrite: true,  // Key: allows updating existing params
        Description: description,
      },
      physicalResourceId: cr.PhysicalResourceId.of(parameterName),
    },
    // Similar for onUpdate...
  });
};
```

### 3. ServiceAccount Already Exists

**Error:**
```
ServiceAccount "aws-load-balancer-controller" in namespace "kube-system" exists and cannot be imported
```

**Cause:** ServiceAccounts were created in ClusterStack for Pod Identity associations, but Helm charts also tried to create them.

**Solution:** Set `serviceAccount.create: false` in Helm values:

```typescript
values: {
  serviceAccount: {
    create: false,  // SA already created in ClusterStack for Pod Identity
    name: 'aws-load-balancer-controller',
  },
}
```

### 4. SSM Parameter Nested Value Constraint

**Error:**
```
Parameter value can't nest another parameter. Do not use "{{}}" in the value.
```

**Cause:** Trying to use `secretValue.unsafeUnwrap()` which resolves to `{{resolve:secretsmanager:...}}` - SSM doesn't allow nested references.

**Solution:** Separate concerns:
- **SSM Parameters**: For config values (API keys from env vars, usernames)
- **Secrets Manager**: For generated random secrets (passwords, tokens)

Don't try to reference Secrets Manager values in SSM Parameters.

### 5. ArgoCD Repository Authentication

**Error:**
```
repository not found
```
or
```
authentication required
```

**Cause:**
- Wrong repo URL in Application manifests (old `Percolation-Labs/reminiscent` vs `mr-saoirse/remstack`)
- GitHub token from `gh auth` may not have access to the target repo

**Solution:**
1. Update all manifest files with correct repo URL:
   ```bash
   find manifests -name "*.yaml" -exec sed -i '' 's|old-org/old-repo|new-org/new-repo|g' {} \;
   ```

2. Create ArgoCD repo secret with correct credentials:
   ```bash
   kubectl create secret generic repo-remstack -n argocd \
     --from-literal=type=git \
     --from-literal=url=https://github.com/org/repo.git \
     --from-literal=username=$(gh api user --jq '.login') \
     --from-literal=password=$(gh auth token)
   kubectl label secret repo-remstack -n argocd argocd.argoproj.io/secret-type=repository
   ```

3. Patch existing Applications:
   ```bash
   kubectl patch application platform-apps -n argocd --type=json \
     -p='[{"op": "replace", "path": "/spec/source/repoURL", "value": "https://github.com/org/repo.git"}]'
   ```

**Important:**
- The `gh auth token` returns an OAuth token (`gho_`) which may not work for ArgoCD
- ArgoCD typically needs a Personal Access Token (`ghp_`) for private repos
- Create a PAT on GitHub with `repo` scope and use that instead:

```bash
# Use a PAT instead of gh auth token
export GITHUB_PAT=ghp_your_personal_access_token
```

## Tips for Future Deployments

### Use `gh` CLI for GitHub Credentials

Instead of manually managing PATs, use the `gh` CLI:

```bash
export GITHUB_USERNAME=$(gh api user --jq '.login')
export GITHUB_PAT=$(gh auth token)
export GITHUB_REPO_URL=https://github.com/<org>/<repo>.git
```

### Helm Chart Dependencies

When installing multiple Helm charts that depend on each other:
1. Use `wait: true` for charts that install webhooks/operators
2. Use explicit `addDependency()` to enforce ordering
3. Consider `atomic: true` for automatic rollback on failure

### Checking ArgoCD Application Status

```bash
# List all applications
kubectl get applications -A

# Check specific app status
kubectl get application <name> -n argocd -o jsonpath='{.status.conditions[*].message}'

# View full status
kubectl get application <name> -n argocd -o yaml | grep -A 30 "status:"
```

### Verify Repository Access

Before running `rem cluster apply`, verify repo access:
```bash
gh repo view <org>/<repo> --json owner,name,visibility
```

## Deployment Order Reference

Correct CDK HelmChart dependency order:
```
Storage Classes (gp3 → gp3-postgres → io2-postgres)
    ↓
Karpenter (first, to avoid webhook issues)
    ↓
ALB Controller (wait: true)
    ↓
NodePool + NodeClass (parallel, after Karpenter)
    ↓
ArgoCD (depends on ALB Controller for webhook)
```
