#!/bin/bash
# =============================================================================
# Pre-flight Validation Script
# =============================================================================
#
# Validates all prerequisites before running bootstrap-argocd.sh
#
# USAGE:
#   ./scripts/validate-prereqs.sh
#
# =============================================================================

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

check_pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
check_fail() { echo -e "${RED}[FAIL]${NC} $1"; ((ERRORS++)); }
check_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; ((WARNINGS++)); }

echo "=============================================="
echo "ArgoCD Bootstrap Pre-flight Validation"
echo "=============================================="
echo ""

# =============================================================================
# Check Required Tools
# =============================================================================

echo "Checking required tools..."

if command -v kubectl &>/dev/null; then
    check_pass "kubectl installed ($(kubectl version --client -o json 2>/dev/null | jq -r '.clientVersion.gitVersion' 2>/dev/null || echo 'unknown version'))"
else
    check_fail "kubectl not installed"
fi

if command -v aws &>/dev/null; then
    check_pass "aws CLI installed ($(aws --version 2>&1 | cut -d' ' -f1))"
else
    check_fail "aws CLI not installed"
fi

if command -v openssl &>/dev/null; then
    check_pass "openssl installed"
else
    check_fail "openssl not installed (needed to generate secrets)"
fi

if command -v rem &>/dev/null; then
    check_pass "rem CLI installed ($(rem --version 2>/dev/null || echo 'version unknown'))"
else
    check_fail "rem CLI not installed (install with: pip install remdb)"
fi

echo ""

# =============================================================================
# Check AWS Credentials
# =============================================================================

echo "Checking AWS credentials..."

if aws sts get-caller-identity &>/dev/null; then
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
    check_pass "AWS credentials valid (account: $ACCOUNT)"
else
    check_fail "AWS credentials not configured or invalid"
fi

echo ""

# =============================================================================
# Check Kubernetes Access
# =============================================================================

echo "Checking Kubernetes access..."

if kubectl cluster-info &>/dev/null; then
    CONTEXT=$(kubectl config current-context 2>/dev/null || echo "unknown")
    check_pass "Kubernetes cluster accessible (context: $CONTEXT)"
else
    check_fail "Cannot connect to Kubernetes cluster"
fi

echo ""

# =============================================================================
# Check ArgoCD Installation
# =============================================================================

echo "Checking ArgoCD installation..."

if kubectl get namespace argocd &>/dev/null; then
    check_pass "ArgoCD namespace exists"
else
    check_fail "ArgoCD namespace not found - install ArgoCD first"
fi

if kubectl get deployment argocd-server -n argocd &>/dev/null; then
    READY=$(kubectl get deployment argocd-server -n argocd -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "$READY" -gt 0 ]]; then
        check_pass "ArgoCD server is running ($READY replicas ready)"
    else
        check_warn "ArgoCD server deployed but not ready"
    fi
else
    check_fail "ArgoCD server deployment not found"
fi

echo ""

# =============================================================================
# Check Required Environment Variables
# =============================================================================

echo "Checking required environment variables..."

# Required
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    check_pass "ANTHROPIC_API_KEY is set"
else
    check_fail "ANTHROPIC_API_KEY not set"
fi

if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    check_pass "OPENAI_API_KEY is set"
else
    check_fail "OPENAI_API_KEY not set"
fi

if [[ -n "${GITHUB_PAT:-}" ]]; then
    check_pass "GITHUB_PAT is set"
else
    check_fail "GITHUB_PAT not set"
fi

if [[ -n "${GITHUB_USERNAME:-}" ]]; then
    check_pass "GITHUB_USERNAME is set"
else
    check_fail "GITHUB_USERNAME not set"
fi

if [[ -n "${GITHUB_REPO_URL:-}" ]]; then
    check_pass "GITHUB_REPO_URL is set (${GITHUB_REPO_URL})"
else
    check_fail "GITHUB_REPO_URL not set (e.g., https://github.com/YOUR_ORG/YOUR_REPO.git)"
fi

# Optional
if [[ -n "${GOOGLE_CLIENT_ID:-}" ]]; then
    check_pass "GOOGLE_CLIENT_ID is set"
else
    check_warn "GOOGLE_CLIENT_ID not set (will use placeholder)"
fi

if [[ -n "${GOOGLE_CLIENT_SECRET:-}" ]]; then
    check_pass "GOOGLE_CLIENT_SECRET is set"
else
    check_warn "GOOGLE_CLIENT_SECRET not set (will use placeholder)"
fi

echo ""

# =============================================================================
# Check Existing SSM Parameters (informational)
# =============================================================================

echo "Checking existing SSM parameters..."

SSM_PREFIX="${SSM_PREFIX:-/rem}"
PARAMS=(
    "${SSM_PREFIX}/postgres/username"
    "${SSM_PREFIX}/postgres/password"
    "${SSM_PREFIX}/llm/anthropic-api-key"
    "${SSM_PREFIX}/llm/openai-api-key"
)

for param in "${PARAMS[@]}"; do
    if aws ssm get-parameter --name "$param" &>/dev/null; then
        check_warn "SSM parameter exists: $param (will skip creation)"
    else
        echo -e "       SSM parameter not found: $param (will be created)"
    fi
done

echo ""

# =============================================================================
# Check ArgoCD Repo Secret
# =============================================================================

echo "Checking ArgoCD repository secret..."

if kubectl get secret repo-reminiscent -n argocd &>/dev/null; then
    check_warn "ArgoCD repo secret 'repo-reminiscent' exists (will skip creation)"
else
    echo "       ArgoCD repo secret not found (will be created)"
fi

echo ""

# =============================================================================
# Summary
# =============================================================================

echo "=============================================="
echo "Validation Summary"
echo "=============================================="

if [[ $ERRORS -gt 0 ]]; then
    echo -e "${RED}FAILED${NC}: $ERRORS errors, $WARNINGS warnings"
    echo ""
    echo "Please fix the errors above before running bootstrap-argocd.sh"
    exit 1
elif [[ $WARNINGS -gt 0 ]]; then
    echo -e "${YELLOW}PASSED WITH WARNINGS${NC}: $WARNINGS warnings"
    echo ""
    echo "You can proceed with bootstrap-argocd.sh"
    echo "Warnings indicate existing resources that will be skipped."
    exit 0
else
    echo -e "${GREEN}PASSED${NC}: All checks passed"
    echo ""
    echo "Ready to run: ./scripts/bootstrap-argocd.sh"
    exit 0
fi
