# syntax=docker/dockerfile:1

# ── Builder: resolve deps from the lockfile into a venv ──────────────────────
FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

# uv installs wheels only; no compiler/build-essential needed.
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# Runtime deps only. The project itself is imported via PYTHONPATH, so it is
# not installed into the venv (keeps the runtime image free of build metadata).
RUN uv sync --frozen --no-dev --no-install-project

# ── Runtime: venv + source only ──────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

COPY --from=builder /app/.venv /app/.venv
COPY src ./src

# Non-root runtime user; /data is the mounted volume for the SQLite DB
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sessions', timeout=3)"

# Bind defaults to loopback; docker-compose overrides to 0.0.0.0 so the
# frontend container can reach the API over the docker network.
CMD ["sh", "-c", "uvicorn open_tavern.api.main:app --host ${OPEN_TAVERN_BIND_HOST:-127.0.0.1} --port 8000"]