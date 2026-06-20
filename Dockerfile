# Production image. uv for fast, reproducible installs from the lockfile.
FROM python:3.13-slim

# uv is a single static binary — copy it in from its published image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependency layer first so Docker caches it — code changes won't reinstall deps.
# Include the `redis` extra: the shared rate-limit/cache backend used when running
# multiple workers. (The rag/otel extras are heavier; add them here if you need them.)
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project --extra redis

# App code + migrations (alembic is needed to run `alembic upgrade head` in prod).
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --no-dev --extra redis

# Run as a non-root user (defence in depth).
RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Container-native liveness check hitting /health (stdlib only — no curl in slim).
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

# One worker by default. For multiple workers (or multiple containers), use the
# Redis-backed limit/cache (see docker-compose.yml) so state is shared.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
