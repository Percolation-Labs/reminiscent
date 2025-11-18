# ==============================================================================
# REM Unified Dockerfile
# Supports multiple entry points: API, Worker, CLI
# Built with uv for fast, deterministic builds
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies with uv
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock README.md ./

# Install dependencies into .venv
# Use --frozen to ensure lock file is up to date
# Use --no-dev to exclude development dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Copy source code
COPY src/ ./src/

# ------------------------------------------------------------------------------
# Stage 2: Runtime - Minimal production image
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Install minimal runtime dependencies
# curl: health checks
# procps: process monitoring (for worker health checks)
# ca-certificates: SSL/TLS connections
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    procps \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash rem && \
    chown -R rem:rem /app

# Copy virtual environment from builder
COPY --from=builder --chown=rem:rem /app/.venv /app/.venv

# Copy source code from builder
COPY --from=builder --chown=rem:rem /app/src /app/src

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random

# Switch to non-root user
USER rem

# Expose API port (ignored by worker)
EXPOSE 8000

# ------------------------------------------------------------------------------
# Entry Points - Override with docker-compose or kubernetes
# ------------------------------------------------------------------------------

# Default: API server
# Override with:
#   - Worker: ["python", "-m", "rem.workers.sqs_file_processor"]
#   - CLI: ["rem", "db", "migrate"]
CMD ["uvicorn", "rem.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Health check (works for API, override for worker)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
