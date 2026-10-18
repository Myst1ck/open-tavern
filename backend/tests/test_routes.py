"""Tests for session lock refcount protocol and ActionRequest validation.

Covers the delete_session fix: the session lock must be acquired before
deleting, and the ``_SESSION_LOCKS`` entry must only be removed when the
refcount reaches zero (no unconditional pop). Also covers the ``kind``
field on :class:`ActionRequest`: the ``"act"`` default keeps legacy
action-only bodies valid, ``"say"``/``"continue"`` are accepted, and an
unknown kind is rejected with 422.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import open_tavern.api.runtime as runtime
from open_tavern.api.llm import get_client
from open_tavern.api.main import create_app
from open_tavern.api.runtime import get_storage
from open_tavern.character import normalize
from open_tavern.storage import Storage


class FakeClient:
    """Queue-backed fake chat client that never touches the network."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, temperature=0.7, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return self.responses.pop(0)


def _make_client(storage: Storage, fake: FakeClient) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_client] = lambda: fake
    return TestClient(app)


@pytest.fixture
def storage() -> Storage:
    store = Storage(":memory:")
    store.init()
    yield store
    store.close()


def _create_session(client: TestClient) -> str:
    resp = client.post("/sessions", json={"world_theme": "gothic"})
    assert resp.status_code == 201
    return resp.json()["session_id"]


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_delete_waits_for_inflight_action_and_cleans_lock(storage):
    """Delete blocks on the session lock and only pops the entry at refcount 0."""
    client = _make_client(storage, FakeClient([]))
    session_id = _create_session(client)

    with runtime.session_lock_ctx(session_id):
        # Simulate an inflight action holding the lock (refcount == 1).
        assert runtime.SESSION_LOCKS[session_id][1] == 1

        result: dict = {}
        deleter = threading.Thread(
            target=lambda: result.update(
                status=client.delete(f"/sessions/{session_id}").status_code
            )
        )
        deleter.start()

        # Delete thread must queue on the lock, not crash or pop the entry.
        assert _wait_until(
            lambda: runtime.SESSION_LOCKS.get(session_id, (None, 0))[1] == 2
        )
        assert deleter.is_alive()
        assert session_id in runtime.SESSION_LOCKS

    # Lock released: delete proceeds, refcount drops to zero, entry removed.
    deleter.join(timeout=5)
    assert not deleter.is_alive()
    assert result["status"] == 204
    assert session_id not in runtime.SESSION_LOCKS
    assert not storage.session_exists(session_id)


def test_concurrent_actions_and_delete_no_crash_no_deadlock(storage):
    """Hammer send_action against delete: no crash, no deadlock, clean lock map."""
    client = _make_client(storage, FakeClient([]))
    session_id = _create_session(client)

    errors: list[BaseException] = []
    barrier = threading.Barrier(5)

    def run_action() -> None:
        try:
            action_client = _make_client(storage, FakeClient(["You act."]))
            barrier.wait()
            resp = action_client.post(
                f"/sessions/{session_id}/actions", json={"action": "look around"}
            )
            # 200 (won the race), 404 (delete won), or 409 (no character
            # generated yet — session created without a character) are all
            # valid outcomes.
            assert resp.status_code in (200, 404, 409)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    def run_delete() -> None:
        try:
            delete_client = _make_client(storage, FakeClient([]))
            barrier.wait()
            resp = delete_client.delete(f"/sessions/{session_id}")
            assert resp.status_code in (204, 404)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=run_action) for _ in range(4)]
    threads.append(threading.Thread(target=run_delete))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"threads raised: {errors}"
    assert all(not t.is_alive() for t in threads), "deadlock: thread(s) hung"
    assert session_id not in runtime.SESSION_LOCKS
    assert not storage.session_exists(session_id)


# --- ActionRequest kind field --------------------------------------------


_MINIMAL_SHEET_RAW = {
    "name": "Thorn",
    "race": "elf",
    "character_class": "ranger",
    "level": 1,
    "abilities": {"STR": 12, "DEX": 16, "CON": 13, "INT": 10, "WIS": 14, "CHA": 9},
}


def _seed_character(storage: Storage, session_id: str) -> None:
    """Persist a normalized character sheet directly (no LLM involved)."""
    storage.save_character(session_id, normalize(_MINIMAL_SHEET_RAW))


@pytest.mark.parametrize(
    "body",
    [
        {"action": "look around"},
        {"action": "I greet the barkeep", "kind": "say"},
        {"action": "", "kind": "continue"},
    ],
)
def test_action_request_accepts_legacy_body_and_valid_kinds(storage, body):
    """Legacy action-only bodies default to "act"; say/continue are accepted."""
    client = _make_client(storage, FakeClient(["You act."]))
    session_id = storage.create_session("gothic")
    _seed_character(storage, session_id)

    resp = client.post(f"/sessions/{session_id}/actions", json=body)

    assert resp.status_code == 200


def test_action_request_rejects_unknown_kind(storage):
    """An unknown kind fails Literal validation with 422."""
    client = _make_client(storage, FakeClient([]))
    session_id = storage.create_session("gothic")

    resp = client.post(f"/sessions/{session_id}/actions", json={"kind": "bogus"})

    assert resp.status_code == 422
    assert any("kind" in err["loc"] for err in resp.json()["detail"])
