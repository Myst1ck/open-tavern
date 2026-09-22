"""API behavior tests that previously lived alongside the bearer-token suite.

``OPENAI_API_KEY`` is optional: the app starts without it and only
OpenAI-dependent requests fail (HTTP 503) until a key is supplied.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from open_tavern.api.main import create_app
from open_tavern.api.routes import get_client, get_storage
from open_tavern.storage import Storage


@pytest.fixture
def storage() -> Storage:
    store = Storage(":memory:")
    store.init()
    yield store
    store.close()


def _app(storage: Storage | None = None) -> TestClient:
    app = create_app()
    if storage is not None:
        app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


def test_cors_preflight_allows_origin(monkeypatch):
    monkeypatch.setenv("OPEN_TAVERN_ALLOWED_ORIGINS", "http://localhost:5173")
    client = _app()

    resp = client.options(
        "/sessions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_openai_request_503_without_key(monkeypatch, storage):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_client.cache_clear()
    client = _app(storage)

    resp = client.post("/sessions/any/character", json={"description": "elf"})

    assert resp.status_code == 503
    assert "OPENAI_API_KEY" in resp.json()["detail"]