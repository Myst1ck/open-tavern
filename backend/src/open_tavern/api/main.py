"""FastAPI application factory and the default app instance.

``create_app`` builds a fresh app for tests (which then override the client and
storage dependencies). The module-level ``app`` is the uvicorn entry point:
``uvicorn open_tavern.api.main:app``.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from open_tavern.api.routes import router

_ALLOWED_ORIGINS = ["*"]


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    application = FastAPI(title="Open Tavern", version="0.1.0")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app: FastAPI = create_app()
