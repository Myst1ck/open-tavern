"""CORS origin allowlist behavior tests.

Origins come from ``OPEN_TAVERN_ALLOWED_ORIGINS`` (comma-separated) with a
localhost-only default. Allowed origins receive CORS headers; disallowed
origins get none. ``GET /sessions`` is used as the probe route — it is
auth-exempt; the probe tests back the app with an isolated in-memory store.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from open_tavern.api.main import _allowed_origins, create_app
from open_tavern.api.routes import get_storage
from open_tavern.storage import Storage


@pytest.fixture
def storage() -> Storage:
    store = Storage(":memory:")
    store.init()
    yield store
    store.close()


def _client(storage: Storage) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


def _get_with_origin(client: TestClient, origin: str):
    return client.get("/sessions", headers={"Origin": origin})


# --- _allowed_origins parsing --------------------------------------------


def test_allowed_origins_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("OPEN_TAVERN_ALLOWED_ORIGINS", raising=False)

    assert _allowed_origins() == ["http://localhost:5173"]


def test_allowed_origins_parses_comma_separated_env(monkeypatch):
    monkeypatch.setenv(
        "OPEN_TAVERN_ALLOWED_ORIGINS", "http://a.example, http://b.example"
    )

    assert _allowed_origins() == ["http://a.example", "http://b.example"]


def test_allowed_origins_drops_whitespace_entries(monkeypatch):
    monkeypatch.setenv(
        "OPEN_TAVERN_ALLOWED_ORIGINS", "http://a.example, ,  ,http://b.example"
    )

    assert _allowed_origins() == ["http://a.example", "http://b.example"]


# --- middleware behavior --------------------------------------------------


def test_allowed_origin_gets_cors_headers(monkeypatch, storage):
    monkeypatch.delenv("OPEN_TAVERN_ALLOWED_ORIGINS", raising=False)
    client = _client(storage)

    resp = _get_with_origin(client, "http://localhost:5173")

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_disallowed_origin_gets_no_cors_headers(monkeypatch, storage):
    monkeypatch.delenv("OPEN_TAVERN_ALLOWED_ORIGINS", raising=False)
    client = _client(storage)

    resp = _get_with_origin(client, "http://evil.example")

    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


def test_env_override_allows_only_configured_origins(monkeypatch, storage):
    monkeypatch.setenv(
        "OPEN_TAVERN_ALLOWED_ORIGINS", "http://a.example,http://b.example"
    )
    client = _client(storage)

    allowed = _get_with_origin(client, "http://a.example")
    assert allowed.headers.get("access-control-allow-origin") == "http://a.example"

    allowed_b = _get_with_origin(client, "http://b.example")
    assert allowed_b.headers.get("access-control-allow-origin") == "http://b.example"

    denied = _get_with_origin(client, "http://localhost:5173")
    assert "access-control-allow-origin" not in denied.headers


def test_preflight_allowed_origin_ok(monkeypatch, storage):
    monkeypatch.delenv("OPEN_TAVERN_ALLOWED_ORIGINS", raising=False)
    client = _client(storage)

    resp = client.options(
        "/sessions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_preflight_enumerates_methods_and_headers(monkeypatch, storage):
    monkeypatch.delenv("OPEN_TAVERN_ALLOWED_ORIGINS", raising=False)
    client = _client(storage)

    resp = client.options(
        "/sessions",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "X-API-Key, X-Model, X-Base-Url",
        },
    )

    assert resp.status_code == 200
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "PATCH" in allow_methods
    assert "*" not in allow_methods
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "x-api-key" in allow_headers
    assert "x-model" in allow_headers
    assert "x-base-url" in allow_headers
    assert "*" not in allow_headers
