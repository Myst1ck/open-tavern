FROM python:3.13-slim-bookworm

WORKDIR /app

# Install build deps for hatchling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy everything first (source + config)
COPY . .

# Install package + deps (hatchling needs src/ present)
RUN pip install --no-cache-dir .

# Non-root runtime user; /data is the mounted volume for the SQLite DB
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sessions', timeout=3)"

# Bind defaults to loopback; docker-compose overrides to 0.0.0.0 so the
# frontend container can reach the API over the docker network. The bind host
# must match OPEN_TAVERN_BIND_HOST for the startup auth policy to be accurate.
CMD ["sh", "-c", "uvicorn open_tavern.api.main:app --host ${OPEN_TAVERN_BIND_HOST:-127.0.0.1} --port 8000"]