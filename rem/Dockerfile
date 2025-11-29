# ==============================================================================
# REM Unified Dockerfile
# Supports multiple entry points: API, Worker, CLI
# Built with uv for fast, deterministic builds
# ==============================================================================
#
# Build and Push (Multi-Platform with buildx):
#   # Push to registry (3 tags: latest, git SHA, semantic version):
#   VERSION=$(grep '^version' pyproject.toml | cut -d'"' -f2) && \
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -t percolationlabs/rem:latest \
#     -t percolationlabs/rem:$(git rev-parse --short HEAD) \
#     -t percolationlabs/rem:$VERSION \
#     --push \
#     -f Dockerfile .
#
#   # Load locally for testing (single platform):
#   docker buildx build --platform linux/arm64 \
#     -t percolationlabs/rem:latest \
#     --load \
#     -f Dockerfile .
#
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies with uv
# ------------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

# Install build dependencies for packages with native extensions (Rust, C)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Disable bytecode compilation to avoid timeout on large files (language_data/name_data.py)
ENV UV_COMPILE_BYTECODE=0

# Copy dependency files first for better layer caching
COPY pyproject.toml uv.lock README.md ./

# Copy source code (needed for package installation)
# Schemas are inside src/rem/schemas
COPY src/ ./src/

# Install dependencies and the rem package into .venv
# Use --frozen to ensure lock file is up to date
# Use --no-dev to exclude development dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ------------------------------------------------------------------------------
# Stage 2: Runtime - Minimal production image
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Install minimal runtime dependencies
# curl: health checks
# procps: process monitoring (for worker health checks)
# ca-certificates: SSL/TLS connections
# tesseract-ocr: OCR engine for PDF parsing (Kreuzberg)
# tesseract-ocr-eng: English language data for Tesseract
# ffmpeg: Audio/video processing (required by pydub for M4A, MP3, etc.)
# git: GitProvider for versioned schema/experiment syncing
# openssh-client: SSH authentication for private Git repositories
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    procps \
    ca-certificates \
    tesseract-ocr \
    tesseract-ocr-eng \
    ffmpeg \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash rem && \
    chown -R rem:rem /app

# Copy virtual environment from builder
COPY --from=builder --chown=rem:rem /app/.venv /app/.venv

# Copy source code from builder (includes schemas at src/rem/schemas)
COPY --from=builder --chown=rem:rem /app/src /app/src

# Create Kreuzberg cache directory with write permissions
# Kreuzberg uses Path.cwd() / ".kreuzberg", so we must create /app/.kreuzberg
# Make it writable by UID 1000 (runAsUser in K8s)
RUN mkdir -p /app/.kreuzberg && chown 1000:0 /app/.kreuzberg && chmod 775 /app/.kreuzberg

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1 \
    PYTHONHASHSEED=random \
    PYTHONWARNINGS="ignore::SyntaxWarning:pydub,ignore::DeprecationWarning:pydub,ignore::DeprecationWarning:audioop"

# Switch to non-root user
USER rem

# Expose API port (ignored by worker)
EXPOSE 8000

# ------------------------------------------------------------------------------
# Entry Points - Override with docker-compose or kubernetes
# ------------------------------------------------------------------------------

# Default: API server with hypercorn (HTTP/2 support)
# Override with:
#   - Worker: ["python", "-m", "rem.workers.sqs_file_processor"]
#   - CLI: ["rem", "db", "migrate"]
# Disable hypercorn access logging - RequestLoggingMiddleware handles this
# with health checks logged at DEBUG level to reduce noise
# Use python -W flags to suppress pydub SyntaxWarnings (emitted at parse time before PYTHONWARNINGS applies)
CMD ["python", "-W", "ignore::SyntaxWarning", "-W", "ignore::DeprecationWarning", "-m", "hypercorn", "rem.api.main:app", "--bind", "0.0.0.0:8000", "--access-logfile", "/dev/null"]

# Health check (works for API, override for worker)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
