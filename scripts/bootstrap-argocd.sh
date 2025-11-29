#!/bin/bash
# =============================================================================
# ArgoCD Bootstrap Script
# =============================================================================
#
# This script sets up all prerequisites for ArgoCD deployment:
#   1. Creates SSM parameters for secrets
#   2. Creates ArgoCD repository secret for private repo access
#   3. Applies platform-apps (app-of-apps)
#   4. Applies rem-stack application
#
# PREREQUISITES:
#   - AWS CLI configured with correct profile
#   - kubectl configured with cluster access
#   - ArgoCD installed in cluster
#
# USAGE:
#   # Set required environment variables
#   export AWS_PROFILE=rem
#   export ANTHROPIC_API_KEY=sk-ant-...
#   export OPENAI_API_KEY=sk-proj-...
#   export GITHUB_PAT=ghp_...
#   export GITHUB_USERNAME=your-username
#
#   # Optional: Google OAuth (leave empty to use placeholders)
#   export GOOGLE_CLIENT_ID=...
#   export GOOGLE_CLIENT_SECRET=...
#
#   # Run bootstrap
#   ./scripts/bootstrap-argocd.sh
#
# =============================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# Configuration
# =============================================================================

# Repository URL - REQUIRED (no default - user must specify their repo)
REPO_URL="${GITHUB_REPO_URL:-}"

# Namespace for rem-stack
REM_NAMESPACE="${REM_NAMESPACE:-rem}"

# SSM parameter prefix
SSM_PREFIX="${SSM_PREFIX:-/rem}"

# =============================================================================
# Validate Required Environment Variables
# =============================================================================

validate_env() {
    local missing=()

    # Required for LLM functionality
    [[ -z "${ANTHROPIC_API_KEY:-}" ]] && missing+=("ANTHROPIC_API_KEY")
    [[ -z "${OPENAI_API_KEY:-}" ]] && missing+=("OPENAI_API_KEY")

    # Required for repo access
    [[ -z "${GITHUB_REPO_URL:-}" ]] && missing+=("GITHUB_REPO_URL")
    [[ -z "${GITHUB_PAT:-}" ]] && missing+=("GITHUB_PAT")
    [[ -z "${GITHUB_USERNAME:-}" ]] && missing+=("GITHUB_USERNAME")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required environment variables:"
        for var in "${missing[@]}"; do
            echo "  - $var"
        done
        echo ""
        echo "Example:"
        echo "  export GITHUB_REPO_URL=https://github.com/YOUR_ORG/YOUR_REPO.git"
        echo "  export ANTHROPIC_API_KEY=sk-ant-..."
        echo "  export OPENAI_API_KEY=sk-proj-..."
        echo "  export GITHUB_PAT=ghp_..."
        echo "  export GITHUB_USERNAME=your-username"
        exit 1
    fi

    log_info "Repository URL: ${REPO_URL}"
    log_info "All required environment variables set"
}

# =============================================================================
# Generate Secure Random Strings
# =============================================================================

generate_secret() {
    openssl rand -base64 32 | tr -d '\n'
}

# =============================================================================
# Create SSM Parameters
# =============================================================================

create_ssm_param() {
    local name="$1"
    local value="$2"
    local type="${3:-SecureString}"

    # Check if parameter exists
    if aws ssm get-parameter --name "$name" &>/dev/null; then
        log_info "SSM parameter exists: $name (skipping)"
        return 0
    fi

    log_info "Creating SSM parameter: $name"
    aws ssm put-parameter \
        --name "$name" \
        --value "$value" \
        --type "$type" \
        --no-overwrite \
        > /dev/null
}

create_ssm_params() {
    log_info "Creating SSM parameters..."

    # PostgreSQL credentials
    # IMPORTANT: Username MUST be 'remuser' to match CNPG cluster spec
    create_ssm_param "${SSM_PREFIX}/postgres/username" "remuser" "String"
    create_ssm_param "${SSM_PREFIX}/postgres/password" "$(generate_secret)"

    # LLM API Keys (user-provided)
    create_ssm_param "${SSM_PREFIX}/llm/anthropic-api-key" "${ANTHROPIC_API_KEY}"
    create_ssm_param "${SSM_PREFIX}/llm/openai-api-key" "${OPENAI_API_KEY}"

    # Auth secrets
    create_ssm_param "${SSM_PREFIX}/auth/session-secret" "$(generate_secret)"
    create_ssm_param "${SSM_PREFIX}/auth/google-client-id" "${GOOGLE_CLIENT_ID:-placeholder}" "String"
    create_ssm_param "${SSM_PREFIX}/auth/google-client-secret" "${GOOGLE_CLIENT_SECRET:-placeholder}"

    # Phoenix secrets (auto-generated)
    create_ssm_param "${SSM_PREFIX}/phoenix/api-key" "$(generate_secret)"
    create_ssm_param "${SSM_PREFIX}/phoenix/secret" "$(generate_secret)"
    create_ssm_param "${SSM_PREFIX}/phoenix/admin-secret" "$(generate_secret)"

    log_info "SSM parameters created successfully"
}

# =============================================================================
# Create ArgoCD Repository Secret
# =============================================================================

create_argocd_repo_secret() {
    log_info "Creating ArgoCD repository secret..."

    # Check if secret exists
    if kubectl get secret repo-reminiscent -n argocd &>/dev/null; then
        log_info "ArgoCD repo secret exists (skipping)"
        return 0
    fi

    # Create the secret
    kubectl create secret generic repo-reminiscent \
        --namespace argocd \
        --from-literal=url="${REPO_URL}" \
        --from-literal=username="${GITHUB_USERNAME}" \
        --from-literal=password="${GITHUB_PAT}" \
        --from-literal=type=git \
        --dry-run=client -o yaml | kubectl apply -f -

    # Label it as an ArgoCD repository secret
    kubectl label secret repo-reminiscent -n argocd \
        argocd.argoproj.io/secret-type=repository \
        --overwrite

    log_info "ArgoCD repo secret created"
}

# =============================================================================
# Verify ArgoCD is Ready
# =============================================================================

verify_argocd() {
    log_info "Verifying ArgoCD is ready..."

    if ! kubectl get namespace argocd &>/dev/null; then
        log_error "ArgoCD namespace not found. Please install ArgoCD first:"
        echo "  kubectl create namespace argocd"
        echo "  kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml"
        exit 1
    fi

    # Wait for ArgoCD server to be ready
    kubectl wait --for=condition=available --timeout=120s \
        deployment/argocd-server -n argocd || {
        log_error "ArgoCD server not ready"
        exit 1
    }

    log_info "ArgoCD is ready"
}

# =============================================================================
# Check rem CLI is installed
# =============================================================================

check_rem_cli() {
    log_info "Checking rem CLI..."

    if ! command -v rem &>/dev/null; then
        log_error "rem CLI not installed. Install with:"
        echo "  pip install remdb"
        exit 1
    fi

    log_info "rem CLI found: $(rem --version 2>/dev/null || echo 'version unknown')"
}

# =============================================================================
# Create Namespace and Pre-requisite ConfigMaps (using rem CLI)
# =============================================================================

create_namespace_and_configmaps() {
    log_info "Creating namespace and pre-requisite resources using rem CLI..."

    # Create namespace if it doesn't exist
    if ! kubectl get namespace "${REM_NAMESPACE}" &>/dev/null; then
        log_info "Creating namespace: ${REM_NAMESPACE}"
        kubectl create namespace "${REM_NAMESPACE}"
    else
        log_info "Namespace ${REM_NAMESPACE} exists"
    fi

    # Use rem CLI to generate and apply SQL ConfigMap
    # This creates rem-postgres-init-sql ConfigMap needed by CNPG
    if kubectl get configmap rem-postgres-init-sql -n "${REM_NAMESPACE}" &>/dev/null; then
        log_info "ConfigMap rem-postgres-init-sql exists (skipping)"
    else
        log_info "Generating PostgreSQL init ConfigMap using rem CLI..."
        rem cluster generate-sql-configmap --namespace "${REM_NAMESPACE}" --apply
        log_info "ConfigMap rem-postgres-init-sql created"
    fi
}

# =============================================================================
# Apply ArgoCD Applications
# =============================================================================

apply_platform_apps() {
    log_info "Applying platform-apps (app-of-apps)..."

    kubectl apply -f manifests/platform/argocd/app-of-apps.yaml

    log_info "Waiting for cert-manager to be healthy..."
    sleep 10

    # Wait for critical platform apps
    for app in cert-manager external-secrets-operator; do
        log_info "Waiting for $app..."
        timeout 300 bash -c "
            while true; do
                status=\$(kubectl get application $app -n argocd -o jsonpath='{.status.health.status}' 2>/dev/null || echo 'Unknown')
                if [[ \"\$status\" == \"Healthy\" ]]; then
                    break
                fi
                echo \"  $app status: \$status\"
                sleep 10
            done
        " || log_warn "$app not healthy yet, continuing..."
    done

    log_info "Platform apps applied"
}

apply_rem_stack() {
    log_info "Applying rem-stack-staging..."

    kubectl apply -f manifests/application/rem-stack/argocd-staging.yaml

    log_info "rem-stack-staging applied"
}

# =============================================================================
# Print Status
# =============================================================================

print_status() {
    echo ""
    log_info "Bootstrap complete! Current ArgoCD application status:"
    echo ""
    kubectl get applications -n argocd
    echo ""
    log_info "To monitor deployment:"
    echo "  watch kubectl get applications -n argocd"
    echo ""
    log_info "To check rem namespace pods:"
    echo "  kubectl get pods -n ${REM_NAMESPACE}"
    echo ""
    log_info "To access ArgoCD UI:"
    echo "  kubectl port-forward svc/argocd-server -n argocd 8080:443"
    echo "  # Get admin password:"
    echo "  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo "=============================================="
    echo "ArgoCD Bootstrap for REM Stack"
    echo "=============================================="
    echo ""

    # Change to repo root
    cd "$(dirname "$0")/.."

    # Pre-flight checks
    validate_env
    check_rem_cli
    verify_argocd

    # Create secrets in SSM
    create_ssm_params

    # Create ArgoCD repo secret for private repo access
    create_argocd_repo_secret

    # Create namespace and ConfigMaps (needed before ArgoCD deploys apps)
    create_namespace_and_configmaps

    # Deploy via ArgoCD
    apply_platform_apps
    apply_rem_stack

    print_status
}

main "$@"
