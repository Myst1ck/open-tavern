"""Bearer-token auth middleware and startup-config guard tests.

Auth is opt-in: it only enforces when ``OPEN_TAVERN_TOKEN`` is set. Startup
validation (:func:`open_tavern.api.main.validate_startup_config`) refuses to
start without an OpenAI key, and refuses a tokenless non-localhost bind.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from open_tavern.api.main import create_app, validate_startup_config
from open_tavern.api.routes import get_storage
from open_tavern.storage import Storage


@pytest.fixture
def storage() -> Storage:
    store = Storage(":memory:")
    store.init()
    yield store
    store.close()


def _authed_app(storage: Storage | None = None) -> TestClient:
    app = create_app()
    if storage is not None:
        app.dependency_overrides[get_storage] = lambda: storage
    return TestClient(app)


# --- middleware ----------------------------------------------------------


def test_401_without_token(monkeypatch):
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")
    client = _authed_app()

    resp = client.get("/sessions/does-not-exist")

    assert resp.status_code == 401


def test_401_with_wrong_token(monkeypatch):
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")
    client = _authed_app()

    resp = client.get(
        "/sessions/does-not-exist", headers={"Authorization": "Bearer wrong"}
    )

    assert resp.status_code == 401


def test_401_without_bearer_scheme(monkeypatch):
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")
    client = _authed_app()

    resp = client.get(
        "/sessions/does-not-exist", headers={"Authorization": "sekrit"}
    )

    assert resp.status_code == 401


def test_valid_token_passes(monkeypatch, storage):
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")
    client = _authed_app(storage)

    resp = client.post(
        "/sessions",
        json={"world_theme": "gothic"},
        headers={"Authorization": "Bearer sekrit"},
    )

    assert resp.status_code == 201


def test_health_path_exempt(monkeypatch, storage):
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")
    client = _authed_app(storage)

    resp = client.get("/sessions")

    assert resp.status_code == 200


def test_no_token_configured_serves_open(monkeypatch, storage):
    monkeypatch.delenv("OPEN_TAVERN_TOKEN", raising=False)
    client = _authed_app(storage)

    # Route runs (404, not 401) — auth is disabled when no token is set.
    assert client.get("/sessions/does-not-exist").status_code == 404


# --- startup config guard ------------------------------------------------


def test_startup_refuses_without_openai_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        validate_startup_config()


def test_startup_refuses_tokenless_nonlocal_bind(monkeypatch):
    monkeypatch.delenv("OPEN_TAVERN_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPEN_TAVERN_BIND_HOST", "0.0.0.0")

    with pytest.raises(RuntimeError, match="OPEN_TAVERN_TOKEN"):
        validate_startup_config()


def test_startup_warns_tokenless_local_bind(monkeypatch, caplog):
    monkeypatch.delenv("OPEN_TAVERN_TOKEN", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPEN_TAVERN_BIND_HOST", "127.0.0.1")

    validate_startup_config()  # must not raise

    assert any("OPEN_TAVERN_TOKEN" in record.message for record in caplog.records)


def test_startup_passes_with_token(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPEN_TAVERN_TOKEN", "sekrit")
    monkeypatch.setenv("OPEN_TAVERN_BIND_HOST", "0.0.0.0")

    validate_startup_config()  # must not raise