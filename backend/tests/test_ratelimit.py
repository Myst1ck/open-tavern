"""Rate-limit behavior tests: 429 on exhaustion and proxy-header handling.

``X-Forwarded-For`` is only trusted for rate-limit keys when
``OPEN_TAVERN_TRUST_PROXY=1``. By default the header is ignored (it is
trivially spoofable) and the client host is used.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from open_tavern.api.main import create_app
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


def _exhaust_create_limit(client: TestClient) -> None:
    """Send 30 create requests (the limit) and expect 201 each."""
    for _ in range(30):
        resp = client.post("/sessions", json={"world_theme": "gothic"})
        assert resp.status_code == 201


def test_429_when_limit_exceeded(storage):
    client = _client(storage)
    _exhaust_create_limit(client)

    resp = client.post("/sessions", json={"world_theme": "gothic"})

    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"


def test_x_forwarded_for_ignored_when_flag_off(storage):
    client = _client(storage)
    _exhaust_create_limit(client)

    # A different spoofed header value must NOT open a fresh bucket.
    resp = client.post(
        "/sessions",
        json={"world_theme": "gothic"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert resp.status_code == 429


def test_x_forwarded_for_used_when_flag_on(storage, monkeypatch):
    monkeypatch.setenv("OPEN_TAVERN_TRUST_PROXY", "1")
    client = _client(storage)
    _exhaust_create_limit(client)

    # A fresh forwarded IP gets its own bucket when the flag is on.
    resp = client.post(
        "/sessions",
        json={"world_theme": "gothic"},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )

    assert resp.status_code == 201