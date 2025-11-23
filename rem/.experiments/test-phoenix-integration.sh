#!/usr/bin/env bash
#
# Phoenix Integration Test Script
#
# Quick test of experiments framework with Phoenix integration
#
# Usage:
#   ./test-phoenix-integration.sh [port-forward|cluster|local]
#
# Modes:
#   port-forward: Test with kubectl port-forward to cluster Phoenix (default)
#   cluster: Test execution from rem-api pod on cluster
#   local: Test with local Phoenix instance
#

set -euo pipefail

MODE="${1:-port-forward}"
EXPERIMENT_NAME="hello-world-phoenix-test"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}✓${NC} $1"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
}

step() {
    echo -e "\n${GREEN}==>${NC} $1"
}

check_prerequisites() {
    step "Checking prerequisites"

    # Check if in REM directory
    if [[ ! -f "pyproject.toml" ]] || ! grep -q "name = \"rem\"" pyproject.toml 2>/dev/null; then
        error "Must run from REM repository root"
        exit 1
    fi
    info "In REM repository"

    # Check uv
    if ! command -v uv &> /dev/null; then
        error "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    info "uv installed"

    # Check schemas exist
    if [[ ! -f "schemas/agents/examples/hello-world.yaml" ]]; then
        error "hello-world agent schema not found"
        exit 1
    fi
    info "Agent schemas exist"

    if [[ ! -f "schemas/evaluators/hello-world/default.yaml" ]]; then
        error "hello-world evaluator schema not found"
        exit 1
    fi
    info "Evaluator schemas exist"
}

check_api_keys() {
    step "Checking API keys"

    if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && [[ -z "${OPENAI_API_KEY:-}" ]]; then
        error "No LLM API keys set. Set ANTHROPIC_API_KEY or OPENAI_API_KEY"
        exit 1
    fi

    if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
        info "ANTHROPIC_API_KEY set"
    fi

    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        info "OPENAI_API_KEY set"
    fi
}

setup_port_forward() {
    step "Setting up port-forward to cluster Phoenix"

    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        error "kubectl not found"
        exit 1
    fi

    # Check Phoenix service exists
    if ! kubectl get svc -n observability phoenix-svc &> /dev/null; then
        error "Phoenix service not found in observability namespace"
        error "Run: kubectl get svc -n observability"
        exit 1
    fi
    info "Phoenix service exists"

    # Check if port-forward already running
    if lsof -Pi :6006 -sTCP:LISTEN -t &> /dev/null; then
        warn "Port 6006 already in use (Phoenix or other service)"
        warn "Assuming Phoenix is accessible at localhost:6006"
    else
        info "Starting port-forward (will run in background)"
        kubectl port-forward -n observability svc/phoenix-svc 6006:6006 &> /tmp/phoenix-port-forward.log &
        PORT_FORWARD_PID=$!

        # Wait for port-forward to be ready
        sleep 3

        if ! lsof -Pi :6006 -sTCP:LISTEN -t &> /dev/null; then
            error "Port-forward failed to start"
            cat /tmp/phoenix-port-forward.log
            exit 1
        fi

        info "Port-forward running (PID: $PORT_FORWARD_PID)"
        echo "$PORT_FORWARD_PID" > /tmp/phoenix-port-forward.pid
    fi

    export PHOENIX_BASE_URL="http://localhost:6006"
    info "Phoenix URL: $PHOENIX_BASE_URL"
}

setup_cluster() {
    step "Setting up cluster execution"

    if ! command -v kubectl &> /dev/null; then
        error "kubectl not found"
        exit 1
    fi

    # Check rem-api deployment exists
    if ! kubectl get deployment -n rem-app rem-api &> /dev/null; then
        error "rem-api deployment not found in rem-app namespace"
        exit 1
    fi
    info "rem-api deployment exists"

    export PHOENIX_BASE_URL="http://phoenix-svc.observability.svc.cluster.local:6006"
    info "Phoenix URL: $PHOENIX_BASE_URL (cluster DNS)"
}

setup_local() {
    step "Setting up local Phoenix"

    # Check if Phoenix is running locally
    if ! lsof -Pi :6006 -sTCP:LISTEN -t &> /dev/null; then
        warn "Phoenix not running on localhost:6006"
        warn "Start Phoenix: python -m phoenix.server.main serve"
        error "Phoenix must be running for local mode"
        exit 1
    fi
    info "Phoenix running on localhost:6006"

    export PHOENIX_BASE_URL="http://localhost:6006"
    info "Phoenix URL: $PHOENIX_BASE_URL"
}

create_experiment() {
    step "Creating experiment: $EXPERIMENT_NAME"

    # Remove existing experiment if present
    if [[ -d ".experiments/$EXPERIMENT_NAME" ]]; then
        warn "Experiment already exists, removing"
        rm -rf ".experiments/$EXPERIMENT_NAME"
    fi

    uv run rem experiments create "$EXPERIMENT_NAME" \
        --agent hello-world \
        --evaluator default \
        --description "Phoenix integration test with hello-world agent" \
        --dataset-location git \
        --results-location git \
        --tags "test,phoenix,hello-world"

    info "Experiment created"
}

create_dataset() {
    step "Creating test dataset"

    cat > ".experiments/$EXPERIMENT_NAME/datasets/ground_truth.csv" << 'EOF'
query,expected_greeting,difficulty
"Say hello","Hello!",easy
"Greet me","Hello!",easy
"Say hello to the world","Hello, World!",medium
"Hi there","Hello!",easy
"Good morning","Hello!",medium
EOF

    info "Dataset created (5 examples)"
}

verify_config() {
    step "Verifying experiment configuration"

    uv run rem experiments show "$EXPERIMENT_NAME"
}

run_dry_run() {
    step "Running dry-run test"

    uv run rem experiments run "$EXPERIMENT_NAME" --dry-run

    info "Dry-run completed"
}

run_experiment_local() {
    step "Running experiment locally (with Phoenix)"

    uv run rem experiments run "$EXPERIMENT_NAME"

    info "Experiment completed"
}

run_experiment_cluster() {
    step "Running experiment on cluster"

    # Copy experiment config to cluster
    kubectl create configmap "$EXPERIMENT_NAME" \
        --from-file=experiment.yaml=".experiments/$EXPERIMENT_NAME/experiment.yaml" \
        --from-file=dataset.csv=".experiments/$EXPERIMENT_NAME/datasets/ground_truth.csv" \
        -n rem-app \
        --dry-run=client -o yaml | kubectl apply -f -

    info "Experiment config copied to cluster"

    # Execute from rem-api pod
    kubectl exec -it deployment/rem-api -n rem-app -- bash -c "
        export PHOENIX_BASE_URL=http://phoenix-svc.observability.svc.cluster.local:6006
        export PHOENIX_API_KEY=\${PHOENIX_API_KEY}
        export ANTHROPIC_API_KEY=\${ANTHROPIC_API_KEY}
        export OPENAI_API_KEY=\${OPENAI_API_KEY}

        # Run experiment
        rem experiments run $EXPERIMENT_NAME
    "

    info "Cluster execution completed"
}

verify_results() {
    step "Verifying results"

    # Check metrics file
    if [[ -f ".experiments/$EXPERIMENT_NAME/results/metrics.json" ]]; then
        info "Metrics file created"
        echo ""
        cat ".experiments/$EXPERIMENT_NAME/results/metrics.json"
        echo ""
    else
        warn "Metrics file not found"
    fi

    # Check Phoenix UI
    info "Open Phoenix UI: $PHOENIX_BASE_URL"
}

cleanup() {
    step "Cleaning up"

    # Remove experiment
    if [[ -d ".experiments/$EXPERIMENT_NAME" ]]; then
        rm -rf ".experiments/$EXPERIMENT_NAME"
        info "Removed experiment directory"
    fi

    # Stop port-forward if we started it
    if [[ -f /tmp/phoenix-port-forward.pid ]]; then
        PORT_FORWARD_PID=$(cat /tmp/phoenix-port-forward.pid)
        if kill -0 "$PORT_FORWARD_PID" 2>/dev/null; then
            kill "$PORT_FORWARD_PID"
            info "Stopped port-forward (PID: $PORT_FORWARD_PID)"
        fi
        rm /tmp/phoenix-port-forward.pid
    fi

    # Remove configmap if in cluster mode
    if [[ "$MODE" == "cluster" ]]; then
        kubectl delete configmap "$EXPERIMENT_NAME" -n rem-app --ignore-not-found
        info "Removed cluster configmap"
    fi
}

main() {
    echo "================================================"
    echo "Phoenix Integration Test - Mode: $MODE"
    echo "================================================"

    # Setup cleanup trap
    trap cleanup EXIT

    check_prerequisites
    check_api_keys

    case "$MODE" in
        port-forward)
            setup_port_forward
            create_experiment
            create_dataset
            verify_config
            run_dry_run
            run_experiment_local
            verify_results
            ;;
        cluster)
            setup_cluster
            create_experiment
            create_dataset
            verify_config
            run_experiment_cluster
            verify_results
            ;;
        local)
            setup_local
            create_experiment
            create_dataset
            verify_config
            run_dry_run
            run_experiment_local
            verify_results
            ;;
        *)
            error "Unknown mode: $MODE"
            error "Usage: $0 [port-forward|cluster|local]"
            exit 1
            ;;
    esac

    echo ""
    echo "================================================"
    info "All tests completed successfully!"
    echo "================================================"
}

main
