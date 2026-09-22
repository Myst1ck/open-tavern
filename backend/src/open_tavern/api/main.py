"""FastAPI application factory and the default app instance.

``create_app`` builds a fresh app for tests (which then override the client and
storage dependencies). The module-level ``app`` is the uvicorn entry point:
``uvicorn open_tavern.api.main:app``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from open_tavern.api.routes import router

#: CORS origins used when ``OPEN_TAVERN_ALLOWED_ORIGINS`` is unset. Local-only
#: default; the API is driven by the bundled frontend dev server (Vite, 5173).
_DEFAULT_ALLOWED_ORIGINS: list[str] = ["http://localhost:5173"]


def _allowed_origins() -> list[str]:
    """Return CORS origins from ``OPEN_TAVERN_ALLOWED_ORIGINS``.

    Comma-separated env override; empty/whitespace-only entries are dropped.
    Falls back to :data:`_DEFAULT_ALLOWED_ORIGINS` when unset — never ``"*"``,
    which would let any website drive the API.
    """
    raw = os.environ.get("OPEN_TAVERN_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in raw.split(",") if origin.strip()]
    return origins or list(_DEFAULT_ALLOWED_ORIGINS)


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Application lifespan hook (no startup checks; kept for future use)."""
    yield


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    application = FastAPI(title="Open Tavern", version="0.1.0", lifespan=_lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=False,
        # Enumerated rather than "*": PATCH is used by session rename, and the
        # frontend sends X-API-Key / X-Model / X-Base-Url alongside Content-Type.
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-API-Key",
            "X-Model",
            "X-Base-Url",
        ],
    )
    application.include_router(router)
    return application


app: FastAPI = create_app()