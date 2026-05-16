# syntax=docker/dockerfile:1.7

# ---------- Builder stage ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock* ./
COPY packages/engine/pyproject.toml packages/engine/pyproject.toml
COPY packages/engine/src packages/engine/src
COPY packages/engine/README.md packages/engine/README.md
COPY README.md ./

RUN uv sync --frozen --no-dev --package arch-guardian-engine || \
    uv sync --no-dev --package arch-guardian-engine

# ---------- Runtime stage ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system guardian \
    && useradd --system --gid guardian --create-home --home-dir /home/guardian guardian

WORKDIR /app

COPY --from=builder --chown=guardian:guardian /app /app

USER guardian

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import arch_guardian_engine; print(arch_guardian_engine.__version__)" || exit 1

ENTRYPOINT ["python", "-m", "arch_guardian_engine"]
