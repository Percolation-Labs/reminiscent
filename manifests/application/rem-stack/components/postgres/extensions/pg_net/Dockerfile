# =============================================================================
# pg_net Extension OCI Image for CloudNativePG ImageVolume
# =============================================================================
#
# This Dockerfile builds the pg_net extension as a standalone OCI image
# that can be mounted into CloudNativePG clusters using ImageVolume.
#
# The resulting image contains only the extension files (no PostgreSQL server),
# following the CloudNativePG extension image layout:
#   /share/extension/  - .control files and SQL scripts
#   /lib/              - shared libraries (.so files)
#
# Requirements:
#   - CloudNativePG 1.27+
#   - Kubernetes 1.33+ with ImageVolume feature gate enabled
#   - PostgreSQL 18+ (for extension_control_path GUC)
#
# Build:
#   docker build --build-arg PG_MAJOR=18 -t ghcr.io/<org>/pg_net-18:latest .
#
# =============================================================================

ARG PG_MAJOR=18

# -----------------------------------------------------------------------------
# Stage 1: Build the extension
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim AS builder

ARG PG_MAJOR

# Add PostgreSQL APT repository (PGDG) for PG18
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && rm -rf /var/lib/apt/lists/*

# Install build dependencies from PGDG
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libcurl4-openssl-dev \
    postgresql-server-dev-${PG_MAJOR} \
    && rm -rf /var/lib/apt/lists/*

# Clone and build pg_net
WORKDIR /build
RUN git clone --depth 1 https://github.com/supabase/pg_net.git

WORKDIR /build/pg_net
RUN make PG_CONFIG=/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config \
    && make install DESTDIR=/output PG_CONFIG=/usr/lib/postgresql/${PG_MAJOR}/bin/pg_config

# -----------------------------------------------------------------------------
# Stage 2: Create minimal extension image
# -----------------------------------------------------------------------------
FROM scratch

ARG PG_MAJOR

# Copy extension files to CloudNativePG expected layout
# Control files and SQL scripts
COPY --from=builder /output/usr/share/postgresql/${PG_MAJOR}/extension/pg_net* /share/extension/

# Shared library
COPY --from=builder /output/usr/lib/postgresql/${PG_MAJOR}/lib/pg_net.so /lib/

# Labels for image metadata
LABEL org.opencontainers.image.title="pg_net PostgreSQL Extension" \
      org.opencontainers.image.description="Async HTTP/HTTPS networking extension for PostgreSQL" \
      org.opencontainers.image.source="https://github.com/supabase/pg_net" \
      org.opencontainers.image.vendor="Supabase" \
      io.cloudnative-pg.extension.name="pg_net" \
      io.cloudnative-pg.extension.postgresql.major="${PG_MAJOR}"
