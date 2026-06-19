# Multi-stage-ish build using the official uv image: fast, reproducible installs.
FROM python:3.12-slim

# uv is a single static binary — copy it in from its published image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only dependency manifests first so Docker can cache the install layer:
# code changes won't re-trigger a full dependency reinstall.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# Now copy the source and install the project itself.
COPY src ./src
RUN uv sync --no-dev

EXPOSE 8000

# `uv run` executes inside the project's managed venv.
# One worker here; scale with multiple workers behind a process manager in prod.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
