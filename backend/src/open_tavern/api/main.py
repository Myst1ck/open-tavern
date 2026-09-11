"""FastAPI application factory and the default app instance.

``create_app`` builds a fresh app for tests (which then override the client and
storage dependencies). The module-level ``app`` is the uvicorn entry point:
``uvicorn open_tavern.api.main:app``.
"""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from open_tavern.api.routes import router

#: CORS origins used when ``OPEN_TAVERN_ALLOWED_ORIGINS`` is unset. Local-only
#: default; the API is driven by the bundled frontend dev server.
_DEFAULT_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

#: ``(method, path)`` pairs exempt from bearer-token auth.
#:
#: ``GET /sessions`` is the Docker HEALTHCHECK probe (see ``backend/Dockerfile``)
#: and must stay reachable without a token, so it is exempted here rather than
#: teaching the health check a token. Every other route requires a valid bearer
#: token when ``OPEN_TAVERN_TOKEN`` is set.
_AUTH_EXEMPT_PATHS: frozenset[tuple[str, str]] = frozenset({("GET", "/sessions")})

#: Hosts treated as localhost-only for the tokenless-startup policy.
_LOCALHOST_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

logger = logging.getLogger(__name__)


def _allowed_origins() -> list[str]:
    """Return CORS origins from ``OPEN_TAVERN_ALLOWED_ORIGINS``.

    Comma-separated env override; empty/whitespace-only entries are dropped.
    Falls back to :data:`_DEFAULT_ALLOWED_ORIGINS` when unset — never ``"*"``,
    which would let any website drive the API.
    """
    raw = os.environ.get("OPEN_TAVERN_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or list(_DEFAULT_ALLOWED_ORIGINS)


def _is_localhost_bind(host: str) -> bool:
    """Return ``True`` when ``host`` is a loopback-only bind address."""
    return host in _LOCALHOST_HOSTS


def validate_startup_config() -> None:
    """Refuse to start when the deployment would be unsafe.

    Raises ``RuntimeError`` when:

    * ``OPENAI_API_KEY`` is missing or empty — the API cannot function without
      an LLM credential.
    * ``OPEN_TAVERN_TOKEN`` is unset while the server binds a non-localhost
      interface — an unauthenticated, network-exposed API.

    Logs a warning (does not raise) when ``OPEN_TAVERN_TOKEN`` is unset but the
    bind is localhost-only, which is acceptable for local development.

    The bind address is read from ``OPEN_TAVERN_BIND_HOST`` (default
    ``127.0.0.1``); the uvicorn ``--host`` flag must match it. ``docker-compose``
    sets it to ``0.0.0.0`` so the policy reflects the container's real exposure.
    """
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError(
            "OPENAI_API_KEY is not set; refusing to start. "
            "Set OPENAI_API_KEY to your OpenAI-compatible API key."
        )
    token = os.environ.get("OPEN_TAVERN_TOKEN", "").strip()
    if token:
        return
    bind_host = os.environ.get("OPEN_TAVERN_BIND_HOST", "127.0.0.1")
    if _is_localhost_bind(bind_host):
        logger.warning(
            "OPEN_TAVERN_TOKEN is not set; serving unauthenticated on "
            "localhost only. Set OPEN_TAVERN_TOKEN to require bearer auth."
        )
        return
    raise RuntimeError(
        "OPEN_TAVERN_TOKEN is not set and the server binds a non-localhost "
        f"interface ({bind_host!r}); refusing to start. "
        "Set OPEN_TAVERN_TOKEN to require bearer auth."
    )


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Require a valid bearer token on every non-exempt request.

    The token comes from the ``OPEN_TAVERN_TOKEN`` environment variable. When
    the variable is unset the middleware is inert (auth disabled) — startup
    validation (:func:`validate_startup_config`) decides whether that is
    acceptable. Comparison uses :func:`hmac.compare_digest` to avoid timing
    side channels.
    """

    def __init__(self, app, token: str | None) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):
        if self._token is None:
            return await call_next(request)
        if (request.method, request.url.path) in _AUTH_EXEMPT_PATHS:
            return await call_next(request)
        expected = f"Bearer {self._token}".encode()
        provided = request.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(provided, expected):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Run startup safety checks before serving; refuse to start on failure."""
    validate_startup_config()
    yield


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    application = FastAPI(title="Open Tavern", version="0.1.0", lifespan=_lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    token = os.environ.get("OPEN_TAVERN_TOKEN", "").strip() or None
    application.add_middleware(BearerTokenMiddleware, token=token)
    application.include_router(router)
    return application


app: FastAPI = create_app()
