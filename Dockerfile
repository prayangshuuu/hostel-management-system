# ==============================================================================
# Multi-stage Dockerfile for Hostel Management System
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Builder
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

# Install uv binary directly from official Astral distribution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Configure uv behavior
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python3.12

WORKDIR /app

# Copy dependency definition and lockfile for caching layer
COPY pyproject.toml uv.lock ./

# Install locked production dependencies into /app/.venv without project code or dev dependencies
RUN uv sync --frozen --no-dev --no-install-project

# ------------------------------------------------------------------------------
# Stage 2: Final Runtime
# ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

LABEL maintainer="DevOps Team <devops@hostel.example.com>" \
      description="Production image for Hostel Management System API"

# Install runtime OS packages (curl for container healthcheck, libpq5 for PostgreSQL client libraries)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Create a dedicated non-root user and group with UID/GID 10001
RUN groupadd --gid 10001 appuser && \
    useradd --uid 10001 --gid 10001 --create-home --shell /bin/sh appuser

WORKDIR /app

# Configure execution environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    WEB_CONCURRENCY=1

# Copy compiled virtual environment from builder stage with proper ownership
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv

# Copy application source code
COPY --chown=appuser:appuser . /app

# Ensure scripts are executable
RUN chmod +x /app/scripts/*.sh

# Switch to non-root user
USER appuser

# Expose API port
EXPOSE 8000

# Container healthcheck querying the health API endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Launch container via database migration entrypoint
ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
