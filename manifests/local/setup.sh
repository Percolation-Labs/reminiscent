#!/bin/bash
# REM Stack Local Development Setup
# Checks prerequisites and provides setup instructions.
#
# Usage: ./setup.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

echo "=============================================="
echo "REM Stack Local Development Setup"
echo "=============================================="
echo ""

# Check Docker
echo "Checking prerequisites..."
echo ""

if command -v docker &> /dev/null && docker info &> /dev/null 2>&1; then
    VERSION=$(docker --version | cut -d' ' -f3 | tr -d ',')
    echo -e "${GREEN}[OK]${NC} Docker: $VERSION"
else
    if command -v docker &> /dev/null; then
        echo -e "${RED}[ERROR]${NC} Docker installed but daemon not running"
        echo "        Start Docker Desktop or run: sudo systemctl start docker"
    else
        echo -e "${RED}[MISSING]${NC} Docker - install from https://docs.docker.com/get-docker/"
    fi
    ERRORS=$((ERRORS + 1))
fi

# Check Docker Compose V2
if docker compose version &> /dev/null 2>&1; then
    VERSION=$(docker compose version --short)
    echo -e "${GREEN}[OK]${NC} Docker Compose: $VERSION"
else
    echo -e "${RED}[MISSING]${NC} Docker Compose V2 - included with Docker Desktop"
    ERRORS=$((ERRORS + 1))
fi

# Check Tilt
if command -v tilt &> /dev/null; then
    VERSION=$(tilt version 2>&1 | head -1)
    echo -e "${GREEN}[OK]${NC} Tilt: $VERSION"
else
    echo -e "${RED}[MISSING]${NC} Tilt - install: brew install tilt"
    ERRORS=$((ERRORS + 1))
fi

# Check uv (optional but recommended)
if command -v uv &> /dev/null; then
    VERSION=$(uv --version 2>&1)
    echo -e "${GREEN}[OK]${NC} uv: $VERSION"
else
    echo -e "${YELLOW}[OPTIONAL]${NC} uv - needed for CLI tasks (brew install uv)"
    WARNINGS=$((WARNINGS + 1))
fi

# Check kind (optional for K8s mode)
if command -v kind &> /dev/null; then
    VERSION=$(kind version 2>&1)
    echo -e "${GREEN}[OK]${NC} kind: $VERSION"
else
    echo -e "${YELLOW}[OPTIONAL]${NC} kind - needed for K8s mode (brew install kind)"
    WARNINGS=$((WARNINGS + 1))
fi

# Check kubectl (optional for K8s mode)
if command -v kubectl &> /dev/null; then
    VERSION=$(kubectl version --client -o yaml 2>/dev/null | grep gitVersion | head -1 | awk '{print $2}')
    echo -e "${GREEN}[OK]${NC} kubectl: $VERSION"
else
    echo -e "${YELLOW}[OPTIONAL]${NC} kubectl - needed for K8s mode (brew install kubectl)"
    WARNINGS=$((WARNINGS + 1))
fi

echo ""
echo "Checking configuration..."
echo ""

# Check .env
if [ -f "../../rem/.env" ]; then
    echo -e "${GREEN}[OK]${NC} .env file exists"

    # Check for API keys (without revealing them)
    if grep -q "LLM__ANTHROPIC_API_KEY=sk-" "../../rem/.env" 2>/dev/null || \
       grep -q "LLM__OPENAI_API_KEY=sk-" "../../rem/.env" 2>/dev/null; then
        echo -e "${GREEN}[OK]${NC} LLM API key configured"
    else
        echo -e "${YELLOW}[WARNING]${NC} No LLM API key found in .env"
        echo "          Add LLM__ANTHROPIC_API_KEY or LLM__OPENAI_API_KEY"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${YELLOW}[INFO]${NC} .env file not found"
    echo "        Create it: cp ../../rem/.env.example ../../rem/.env"
    echo "        Then add your LLM API key"
    WARNINGS=$((WARNINGS + 1))
fi

# Summary
echo ""
echo "=============================================="

if [ $ERRORS -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}All checks passed!${NC}"
    else
        echo -e "${GREEN}Ready to go!${NC} ($WARNINGS optional items)"
    fi
    echo ""
    echo "Quick Start:"
    echo "  1. cd manifests/local"
    echo "  2. tilt up"
    echo "  3. Open http://localhost:10350"
    echo ""
    echo "Tiers:"
    echo "  tilt up                        # Docker Compose (default)"
    echo "  tilt up -- --enable_minio      # + MinIO for S3 testing"
    echo "  tilt up -- --k8s_mode          # Local Kubernetes"
    echo ""
else
    echo -e "${RED}$ERRORS prerequisite(s) missing${NC}"
    echo ""
    echo "Please install missing prerequisites and run again."
    exit 1
fi
