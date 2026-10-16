"""SSE framing contract tests for the actions endpoint.

``POST /sessions/{id}/actions`` streams ``event: roll`` frames (one per turn,
only when a check actually resolved) followed by exactly one terminal
``event: message`` or ``event: error`` frame. ``TestClient`` materializes the
whole body, so these tests parse the frames and assert their order and payloads.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from open_tavern.api import routes, turn_stream
from open_tavern.api.main import create_app
from open_tavern.api.ratelimit import RateLimiter
from open_tavern.api.routes import get_client, get_storage
from open_tavern.character.models import AbilityScores, CharacterSheet
from open_tavern.storage import Storage
from open_tavern.story.client import LLMClientError


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Split a materialized SSE body into ``(event, data)`` frames."""
    frames: list[tuple[str, dict]] = []
    event: str | None = None
    for line in body.splitlines():
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            frames.append((event, json.loads(line[len("data:") :].strip())))
            event = None
    return frames


class _ScriptedClient:
    """Fake chat client returning scripted narrations in order.

    ``follow_up_delay`` sleeps during the roll-result follow-up so tests can
    model a slow phase 2; ``fail_follow_up`` makes that follow-up raise
    ``LLMClientError`` instead of returning narration.
    """

    def __init__(
        self,
        responses: list[str],
        *,
        follow_up_delay: float = 0.0,
        fail_follow_up: bool = False,
    ) -> None:
        self._responses = list(responses)
        self._follow_up_delay = follow_up_delay
        self._fail_follow_up = fail_follow_up

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        if "The dice have been rolled" in messages[-1]["content"]:
            if self._follow_up_delay:
                time.sleep(self._follow_up_delay)
            if self._fail_follow_up:
                raise LLMClientError("upstream narration failed")
        return self._responses.pop(0)


@pytest.fixture
def storage() -> Storage:
    store = Storage(":memory:")
    store.init()
    yield store
    store.close()


def _client(storage: Storage, fake: _ScriptedClient) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_client] = lambda: fake
    return TestClient(app)


def _seed_character(storage: Storage) -> str:
    """Persist a session with a STR/DEX character so named checks resolve."""
    session_id = storage.create_session("gothic")
    storage.save_character(
        session_id,
        CharacterSheet(
            race="human",
            character_class="fighter",
            level=1,
            abilities=AbilityScores(16, 16, 12, 12, 12, 10),
            skills={},
            hp=12,
            max_hp=12,
            proficiency_bonus=2,
        ),
    )
    return session_id


def _post_action(
    client: TestClient, session_id: str, action: str
) -> list[tuple[str, dict]]:
    """POST an action and return its parsed SSE frames."""
    resp = client.post(f"/sessions/{session_id}/actions", json={"action": action})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return _parse_sse(resp.text)


def test_slow_phase_two_still_streams_roll_before_message(storage):
    """A slow phase 2 must not reorder the frames: ``roll`` precedes ``message``."""
    fake = _ScriptedClient(
        ["You swing at the goblin. [CHECK:strength DC12]", "You strike true."],
        follow_up_delay=0.2,
    )
    client = _client(storage, fake)
    session_id = _seed_character(storage)

    frames = _post_action(client, session_id, "attack the goblin")

    # TestClient materializes the body, so assert the frame order and payloads.
    assert [name for name, _ in frames] == ["roll", "message"]
    assert [roll["name"] for roll in frames[0][1]["rolls"]] == ["strength"]
    assert frames[1][1]["narration"] == "You strike true."


def test_two_roll_turn_streams_one_roll_frame_with_both_outcomes(storage):
    """Two resolved checks ride in a single ``roll`` frame, in resolution order."""
    fake = _ScriptedClient(
        [
            "You feint. [CHECK:strength DC12] [CHECK:dexterity DC15]",
            "Both blows land.",
        ]
    )
    client = _client(storage, fake)
    session_id = _seed_character(storage)

    frames = _post_action(client, session_id, "feint then strike")

    assert [name for name, _ in frames] == ["roll", "message"]
    rolls = frames[0][1]["rolls"]
    assert [roll["name"] for roll in rolls] == ["strength", "dexterity"]
    assert [roll["dc"] for roll in rolls] == [12, 15]


def test_llm_client_error_streams_terminal_error_frame(storage):
    """A failed follow-up ends the stream with exactly one ``error`` frame."""
    fake = _ScriptedClient(["You swing. [CHECK:strength DC12]"], fail_follow_up=True)
    client = _client(storage, fake)
    session_id = _seed_character(storage)

    frames = _post_action(client, session_id, "attack")

    # The roll frame was already emitted; the error frame terminates the stream.
    assert [name for name, _ in frames] == ["roll", "error"]
    _, payload = frames[-1]
    assert payload["detail"] == "upstream narration failed"
    assert payload["status"] == 502


def test_unexpected_exception_still_yields_terminal_error_frame(storage, monkeypatch):
    """A non-LLM failure in the turn task still terminates the stream cleanly."""
    fake = _ScriptedClient(["You swing. [CHECK:strength DC12]", "You strike true."])
    client = _client(storage, fake)
    session_id = _seed_character(storage)

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated storage failure")

    # A storage stub whose turn commit blows up: the terminal-frame guarantee
    # must still hold, so the client never hangs on an unterminated stream.
    monkeypatch.setattr(storage, "save_turn", _boom)

    frames = _post_action(client, session_id, "attack")

    assert [name for name, _ in frames] == ["roll", "error"]
    _, payload = frames[-1]
    assert payload["detail"] == "internal server error"
    assert payload["status"] == 500


def test_idle_stream_emits_keepalive_comment_frames(storage, monkeypatch):
    """A silent phase 2 keeps the wire alive with ``: keepalive`` comments."""
    monkeypatch.setattr(turn_stream, "_KEEPALIVE_S", 0.05)
    fake = _ScriptedClient(
        ["You swing at the goblin. [CHECK:strength DC12]", "You strike true."],
        follow_up_delay=0.3,
    )
    client = _client(storage, fake)
    session_id = _seed_character(storage)

    resp = client.post(f"/sessions/{session_id}/actions", json={"action": "attack"})
    assert resp.status_code == 200
    assert ": keepalive" in resp.text
    # Comments must not displace or corrupt the real frames.
    assert [name for name, _ in _parse_sse(resp.text)] == ["roll", "message"]


def test_executor_slot_released_when_stream_is_never_read(storage, monkeypatch):
    """A stream the client never reads must still release its executor slot."""
    single = threading.BoundedSemaphore(1)
    monkeypatch.setattr(routes, "_LLM_EXECUTOR_SLOTS", single)
    fake = _ScriptedClient(["You swing. [CHECK:strength DC12]", "You strike true."])
    session_id = _seed_character(storage)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "client": ("127.0.0.1", 1),
        }
    )
    limiter = RateLimiter(max_requests=10, window_seconds=60.0)

    async def _scenario() -> bool:
        prepared = await turn_stream.prepare_action(
            session_id=session_id,
            action="attack",
            storage=storage,
            client=fake,
            request=request,
            limiter=limiter,
        )
        # Start the turn but never read a single frame: the task must still
        # run to completion and hand the slot back, or the pool leaks one slot
        # per abandoned request until every action returns 503.
        turn_stream.stream_action(prepared)
        for _ in range(200):
            if single.acquire(blocking=False):
                single.release()
                return True
            await asyncio.sleep(0.01)
        return False

    assert asyncio.run(_scenario())
