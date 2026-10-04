# syntax=docker/dockerfile:1.7
#
# arch-guardian CLI image.
#   docker run --rm -v "$PWD:/workspace" ghcr.io/rsaglobaltech/arch-guardian analyze . --base origin/main

# ---------- Builder stage ----------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/guardian

COPY --from=ghcr.io/astral-sh/uv:0.7.19 /uv /usr/local/bin/uv

WORKDIR /src

COPY pyproject.toml uv.lock README.md ./
COPY packages/engine/pyproject.toml packages/engine/README.md packages/engine/
COPY packages/engine/src packages/engine/src

# --frozen: the lockfile is the contract; a mismatch must fail the build.
# --no-editable: the venv is self-contained, sources are not needed at runtime.
RUN uv sync --frozen --no-dev --no-editable --package arch-guardian-engine

# ---------- Runtime stage ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/guardian/bin:$PATH"

# git is required for --base (merge-base + temporary worktrees).
# safe.directory: mounted repositories are owned by another UID; without this
# git refuses to operate on them ("detected dubious ownership").
# pip is removed: the tool never installs anything at runtime, and an unused
# package manager is just attack surface.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip \
    && git config --system --add safe.directory '*' \
    && groupadd --system guardian \
    && useradd --system --gid guardian --create-home --home-dir /home/guardian guardian

COPY --from=builder /opt/guardian /opt/guardian

USER guardian
WORKDIR /workspace

ENTRYPOINT ["guardian"]
CMD ["--help"]
