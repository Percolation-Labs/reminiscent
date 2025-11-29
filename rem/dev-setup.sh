#!/bin/bash
# =============================================================================
# REM Development Setup
# =============================================================================
# One-time setup for local development.
#
# Usage:
#   ./dev-setup.sh
#
# After setup:
#   docker compose up -d postgres   # Start database
#   uv run rem db migrate           # Run migrations
#   uv run pytest tests/unit/       # Run unit tests
# =============================================================================

set -e

# This script runs from the rem/ directory
REM_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$REM_DIR/.." && pwd)"
cd "$REM_DIR"

echo "=== REM Development Setup ==="
echo ""

# 1. Git hooks (relative to repo root)
echo ">>> Setting up git hooks..."
git -C "$REPO_ROOT" config core.hooksPath rem/.githooks
chmod +x .githooks/* 2>/dev/null || true
echo "✓ Git hooks configured"

# 2. Python dependencies
echo ""
echo ">>> Installing Python dependencies..."
uv sync --frozen
echo "✓ Dependencies installed"

# 3. Environment file
if [ ! -f ".env" ]; then
    echo ""
    echo ">>> Creating .env from template..."
    cat > .env << 'EOF'
# REM Development Environment
# Copy this file and add your API keys

# LLM API Keys (at least one required for agent tests)
LLM__OPENAI_API_KEY=
LLM__ANTHROPIC_API_KEY=

# Database (docker-compose default)
POSTGRES__CONNECTION_STRING=postgresql://rem:rem@localhost:5050/rem

# Auth (disabled for local dev)
AUTH__ENABLED=false

# OTEL (disabled for local dev)
OTEL__ENABLED=false
EOF
    echo "✓ Created .env (add your API keys)"
else
    echo ""
    echo "✓ .env already exists"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Quick start:"
echo "  docker compose up -d postgres    # Start database"
echo "  uv run rem db migrate            # Apply migrations"
echo "  uv run pytest tests/unit/ -v     # Run unit tests"
echo ""
echo "Full test suite (requires Docker):"
echo "  docker compose up -d postgres"
echo "  uv run pytest tests/ -v -m 'not llm'"
echo ""
