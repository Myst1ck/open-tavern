"""FastAPI application factory and the default app instance.

``create_app`` builds a fresh app for tests (which then override the client and
storage dependencies). The module-level ``app`` is the uvicorn entry point:
``uvicorn open_tavern.api.main:app``.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from open_tavern.api.routes import router

#: CORS origins used when ``OPEN_TAVERN_ALLOWED_ORIGINS`` is unset. Local-only
#: default; the API is driven by the bundled frontend dev server.
_DEFAULT_ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]


def _allowed_origins() -> list[str]:
    """Return CORS origins from ``OPEN_TAVERN_ALLOWED_ORIGINS``.

    Comma-separated env override; empty/whitespace-only entries are dropped.
    Falls back to :data:`_DEFAULT_ALLOWED_ORIGINS` when unset — never ``"*"``,
    which would let any website drive the API.
    """
    raw = os.environ.get("OPEN_TAVERN_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or list(_DEFAULT_ALLOWED_ORIGINS)


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    application = FastAPI(title="Open Tavern", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app: FastAPI = create_app()
