"""Rate-limit behavior tests: 429 on exhaustion and proxy-header handling.

``X-Forwarded-For`` is only trusted for rate-limit keys when
``OPEN_TAVERN_TRUST_PROXY=1``. By default the header is ignored (it is
trivially spoofable) and the client host is used.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from open_tavern.api.main import create_app
from open_tavern.api.llm import get_client
from open_tavern.api.runtime import get_storage
from open_tavern.character.models import AbilityScores, CharacterSheet
from open_tavern.storage import Storage


@pytest.fixture
def storage() -> Storage:
    store = Storage(":memory:")
    store.init()
    yield store
    store.close()


class _NarratingClient:
    """Chat client stub that narrates without requesting any checks."""

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        return "The tavern falls quiet."


def _client(storage: Storage, fake: _NarratingClient | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    if fake is not None:
        app.dependency_overrides[get_client] = lambda: fake
    return TestClient(app)


def _seed_character(storage: Storage) -> str:
    """Persist a session + character so action requests clear validation."""
    session_id = storage.create_session("gothic")
    storage.save_character(
        session_id,
        CharacterSheet(
            race="human",
            character_class="fighter",
            level=1,
            abilities=AbilityScores(16, 12, 14, 10, 13, 8),
            skills={},
            hp=12,
            max_hp=12,
            proficiency_bonus=2,
        ),
    )
    return session_id


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


def test_action_rate_limit_is_plain_http_before_stream_opens(storage):
    """The actions limiter rejects with a plain 429 — no SSE stream opens."""
    client = _client(storage, _NarratingClient())
    session_id = _seed_character(storage)

    # The action limiter allows 10 requests; the 11th is rejected pre-stream.
    for _ in range(10):
        resp = client.post(
            f"/sessions/{session_id}/actions", json={"action": "look around"}
        )
        assert resp.status_code == 200

    resp = client.post(
        f"/sessions/{session_id}/actions", json={"action": "look around"}
    )

    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"
    # Rejected before the response exists: no SSE frames in the body.
    assert "event:" not in resp.text


def test_action_409_rejections_still_consume_the_rate_window(storage):
    """Requests rejected without a character are counted by the limiter."""
    client = _client(storage, _NarratingClient())
    session_id = storage.create_session("gothic")  # no character -> 409

    # Each 409 is a recorded hit: the limit of 10 fills up, and the 11th
    # request is throttled before validation instead of passing for free.
    for _ in range(10):
        resp = client.post(
            f"/sessions/{session_id}/actions", json={"action": "look around"}
        )
        assert resp.status_code == 409

    resp = client.post(
        f"/sessions/{session_id}/actions", json={"action": "look around"}
    )

    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"


def test_rate_limit_hits_before_session_existence_probe(storage):
    client = _client(storage)
    url = "/sessions/missing/characters/char-1/items"

    # The item limiter is consumed even for unknown sessions, and exhaustion
    # answers 429 instead of leaking a 404 existence oracle.
    for _ in range(30):
        resp = client.post(url, json={"name": "rock"})
        assert resp.status_code == 404

    resp = client.post(url, json={"name": "rock"})

    assert resp.status_code == 429
    assert resp.json()["detail"] == "rate limit exceeded"
