"""API endpoint tests using a fake LLM client and in-memory storage.

No network or disk access: the real ``get_client`` / ``get_storage``
dependencies are replaced via ``app.dependency_overrides``.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import open_tavern.api.routes as routes_module
from open_tavern.api.main import create_app
from open_tavern.api.ratelimit import RateLimiter
from open_tavern.api.routes import (
    _STATE_CACHE,
    build_client_from_headers,
    get_client,
    get_storage,
)
from open_tavern.state import GameState, new_state
from open_tavern.storage import Storage


class FakeClient:
    """Queue-backed fake chat client that never touches the network."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def chat(self, messages, temperature=0.7, json_mode=False):
        self.calls.append({"messages": messages, "json_mode": json_mode})
        return self.responses.pop(0)


def _valid_sheet_raw() -> dict:
    return {
        "name": "Thorn",
        "race": "elf",
        "character_class": "rogue",
        "level": 2,
        "abilities": {"STR": 8, "DEX": 17, "CON": 12, "INT": 14, "WIS": 13, "CHA": 10},
        "skills": {"Stealth": True},
        "inventory": ["dagger", "lockpicks"],
        "backstory": "An orphaned elf.",
    }


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


# --- sessions ------------------------------------------------------------


def test_create_session_creates_and_persists(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.post("/sessions", json={"world_theme": "gothic"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["world_theme"] == "gothic"
    assert data["session_id"]

    loaded = storage.load_session(data["session_id"])
    assert loaded is not None
    assert loaded["world_theme"] == "gothic"


def test_create_session_rejects_malformed_body(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.post("/sessions", json={"nope": 1})

    assert resp.status_code == 422


def test_create_session_accepts_optional_title(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.post("/sessions", json={"world_theme": "gothic", "title": "My Tale"})

    assert resp.status_code == 201
    data = resp.json()
    assert data["world_theme"] == "gothic"
    summaries = storage.list_sessions()
    assert any(
        s["id"] == data["session_id"] and s["title"] == "My Tale" for s in summaries
    )


# --- list / resume / rename / delete -------------------------------------


def test_list_sessions_empty(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.get("/sessions")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sessions_populated(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    s1 = storage.create_session("gothic", title="The Crypt")
    client.post(f"/sessions/{s1}/character", json={"description": "elf"})
    s2 = storage.create_session("western")

    resp = client.get("/sessions")

    assert resp.status_code == 200
    by_id = {s["id"]: s for s in resp.json()}
    assert by_id[s1]["title"] == "The Crypt"
    assert by_id[s1]["world_theme"] == "gothic"
    assert by_id[s1]["character_name"] == "Thorn"
    assert by_id[s2]["title"] == "western"
    assert by_id[s2]["character_name"] is None


def test_get_session_resume_bundle(storage):
    client = _make_client(
        storage,
        FakeClient([json.dumps(_valid_sheet_raw()), "You strike true."]),
    )
    session_id = storage.create_session("gothic", title="The Crypt")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})
    client.post(f"/sessions/{session_id}/actions", json={"action": "attack"})

    resp = client.get(f"/sessions/{session_id}")

    assert resp.status_code == 200
    data = resp.json()
    assert data["meta"]["id"] == session_id
    assert data["meta"]["title"] == "The Crypt"
    assert data["meta"]["world_theme"] == "gothic"
    assert data["meta"]["character_name"] == "Thorn"
    assert data["state"]["character"]["name"] == "Thorn"
    assert data["character"]["name"] == "Thorn"
    assert {"role": "user", "content": "attack"} in data["messages"]
    assert {"role": "assistant", "content": "You strike true."} in data["messages"]


def test_get_session_unknown_404(storage):
    client = _make_client(storage, FakeClient([]))

    assert client.get("/sessions/does-not-exist").status_code == 404


def test_get_session_messages(storage):
    client = _make_client(
        storage,
        FakeClient([json.dumps(_valid_sheet_raw()), "Boom."]),
    )
    session_id = storage.create_session("gothic")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})
    client.post(f"/sessions/{session_id}/actions", json={"action": "attack"})

    resp = client.get(f"/sessions/{session_id}/messages")

    assert resp.status_code == 200
    assert resp.json() == [
        {"role": "user", "content": "attack"},
        {"role": "assistant", "content": "Boom."},
    ]


def test_get_session_messages_unknown_404(storage):
    client = _make_client(storage, FakeClient([]))

    assert client.get("/sessions/does-not-exist/messages").status_code == 404


def test_rename_session(storage):
    client = _make_client(storage, FakeClient([]))
    session_id = storage.create_session("gothic")

    resp = client.patch(f"/sessions/{session_id}", json={"title": "New Title"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == session_id
    assert data["title"] == "New Title"


def test_rename_session_unknown_404(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.patch("/sessions/does-not-exist", json={"title": "X"})

    assert resp.status_code == 404


def test_delete_session(storage):
    client = _make_client(storage, FakeClient([]))
    session_id = storage.create_session("gothic")

    resp = client.delete(f"/sessions/{session_id}")

    assert resp.status_code == 204
    assert storage.load_session(session_id) is None


def test_delete_session_unknown_404(storage):
    client = _make_client(storage, FakeClient([]))

    assert client.delete("/sessions/does-not-exist").status_code == 404


def test_delete_session_removes_from_cache(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = storage.create_session("gothic")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})
    assert session_id in _STATE_CACHE

    client.delete(f"/sessions/{session_id}")

    assert session_id not in _STATE_CACHE


# --- state persistence ---------------------------------------------------


def test_send_action_persists_state(storage):
    client = _make_client(
        storage,
        FakeClient([json.dumps(_valid_sheet_raw()), "You strike true."]),
    )
    session_id = storage.create_session("gothic")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})
    client.post(f"/sessions/{session_id}/actions", json={"action": "attack"})

    character = storage.load_character(session_id)
    saved = storage.load_state(session_id, character)

    assert saved is not None
    assert saved.current_hp == character.max_hp


def test_get_state_loads_persisted_state_after_cache_cleared(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = storage.create_session("gothic")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})

    character = storage.load_character(session_id)
    persisted = GameState(
        current_hp=5,
        max_hp=new_state(character).max_hp,
        inventory=("potion",),
        conditions=frozenset({"poisoned"}),
        scene="a dark cave",
        character=character,
    )
    storage.save_state(session_id, persisted)
    _STATE_CACHE.pop(session_id, None)

    resp = client.get(f"/sessions/{session_id}/state")

    assert resp.status_code == 200
    state = resp.json()["state"]
    assert state["current_hp"] == 5
    assert state["scene"] == "a dark cave"
    assert state["conditions"] == ["poisoned"]
    assert state["inventory"] == ["potion"]


# --- character -----------------------------------------------------------


def test_create_character_returns_and_saves_sheet(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character",
        json={"description": "a sneaky elf"},
    )

    assert resp.status_code == 200
    sheet = resp.json()["character"]
    assert sheet["name"] == "Thorn"
    assert sheet["character_class"] == "rogue"
    assert sheet["level"] == 2

    saved = storage.load_character(session_id)
    assert saved is not None
    assert saved.name == "Thorn"


# --- actions -------------------------------------------------------------


def test_send_action_returns_narration_state_and_persists(storage):
    client = _make_client(
        storage,
        FakeClient([json.dumps(_valid_sheet_raw()), "You strike true."]),
    )
    session_id = storage.create_session("gothic")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})

    resp = client.post(
        f"/sessions/{session_id}/actions",
        json={"action": "attack the goblin"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["narration"] == "You strike true."
    assert data["rolls"] == []
    assert data["state"]["character"]["name"] == "Thorn"

    messages = storage.load_messages(session_id)
    assert {"role": "user", "content": "attack the goblin"} in messages
    assert {"role": "assistant", "content": "You strike true."} in messages


# --- state ---------------------------------------------------------------


def test_get_state_returns_current_state(storage):
    client = _make_client(
        storage,
        FakeClient([json.dumps(_valid_sheet_raw()), "You strike true."]),
    )
    session_id = storage.create_session("gothic")
    client.post(f"/sessions/{session_id}/character", json={"description": "elf"})
    client.post(f"/sessions/{session_id}/actions", json={"action": "attack"})

    resp = client.get(f"/sessions/{session_id}/state")

    assert resp.status_code == 200
    state = resp.json()["state"]
    assert state["character"]["name"] == "Thorn"
    assert state["current_hp"] == state["max_hp"]


# --- error handling ------------------------------------------------------


# --- per-request header client -------------------------------------------


def test_build_client_from_headers_routes_values(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    client = build_client_from_headers(
        api_key="sk-test",
        base_url="http://localhost:11434/v1",
        model="llama3",
    )

    assert client.api_key == "sk-test"
    assert client.base_url == "http://localhost:11434/v1"
    assert client.model == "llama3"


def test_build_client_from_headers_partial_falls_back_to_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    client = build_client_from_headers(
        api_key="sk-test",
        base_url=None,
        model="",
    )

    assert client.api_key == "sk-test"
    # No base URL / model supplied: fall back to OpenAIClient defaults.
    assert client.base_url == "https://api.openai.com/v1"
    assert client.model == "gpt-4o-mini"


def test_build_client_from_headers_empty_values_overridden_by_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    client = build_client_from_headers(api_key=None, base_url="", model=None)

    assert client.api_key == "env-key"
    assert client.base_url == "http://env:8000/v1"
    assert client.model == "env-model"


def test_unknown_session_returns_404(storage):
    client = _make_client(storage, FakeClient([]))

    assert client.get("/sessions/does-not-exist/state").status_code == 404
    assert (
        client.post(
            "/sessions/does-not-exist/actions", json={"action": "attack"}
        ).status_code
        == 404
    )


# --- structured character creation --------------------------------------


def _structured_sheet_raw() -> dict:
    raw = _valid_sheet_raw()
    raw["name"] = "Kael"
    raw["personality"] = "stoic and reliable"
    raw["appearance"] = "broad-shouldered, short beard"
    raw["motivation"] = "protect his village"
    return raw


def test_create_character_structured_request_returns_sheet(storage, monkeypatch):
    monkeypatch.setattr(routes_module, "_character_limiter", RateLimiter(5, 60.0))
    client = _make_client(storage, FakeClient([json.dumps(_structured_sheet_raw())]))
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character",
        json={
            "name": "Kael",
            "race": "elf",
            "class_concept": "swift archer",
            "backstory": "raised by rangers",
            "personality": "stoic and reliable",
            "appearance": "broad-shouldered, short beard",
            "motivation": "protect his village",
        },
    )

    assert resp.status_code == 200
    sheet = resp.json()["character"]
    assert sheet["name"] == "Kael"
    assert isinstance(sheet["character_class"], str) and sheet["character_class"]
    assert all(
        isinstance(sheet["abilities"][ability], int)
        and 3 <= sheet["abilities"][ability] <= 18
        for ability in sheet["abilities"]
    )
    assert sheet["personality"] == "stoic and reliable"
    assert sheet["appearance"] == "broad-shouldered, short beard"
    assert sheet["motivation"] == "protect his village"

    saved = storage.load_character(session_id)
    assert saved is not None
    assert saved.personality == "stoic and reliable"
    assert saved.appearance == "broad-shouldered, short beard"
    assert saved.motivation == "protect his village"


def test_create_character_legacy_description_only_keeps_persona_keys(
    storage, monkeypatch
):
    monkeypatch.setattr(routes_module, "_character_limiter", RateLimiter(5, 60.0))
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character",
        json={"description": "a sneaky elf"},
    )

    assert resp.status_code == 200
    sheet = resp.json()["character"]
    assert sheet["name"] == "Thorn"
    assert sheet["personality"] == ""
    assert sheet["appearance"] == ""
    assert sheet["motivation"] == ""


def test_create_character_structured_invalid_llm_returns_502(storage, monkeypatch):
    monkeypatch.setattr(routes_module, "_character_limiter", RateLimiter(5, 60.0))
    client = _make_client(storage, FakeClient(["not json at all"]))
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character",
        json={"name": "Kael", "race": "elf", "class_concept": "swift archer"},
    )

    assert resp.status_code == 502


def test_create_character_rate_limited_at_five_per_minute(storage, monkeypatch):
    monkeypatch.setattr(routes_module, "_character_limiter", RateLimiter(5, 60.0))
    responses = [json.dumps(_valid_sheet_raw()) for _ in range(5)]
    client = _make_client(storage, FakeClient(responses))
    session_id = storage.create_session("gothic")

    for _ in range(5):
        resp = client.post(
            f"/sessions/{session_id}/character", json={"description": "elf"}
        )
        assert resp.status_code == 200

    resp = client.post(f"/sessions/{session_id}/character", json={"description": "elf"})
    assert resp.status_code == 429


# --- class preview -------------------------------------------------------


def test_create_class_preview_returns_class_definition(storage):
    client = _make_client(
        storage,
        FakeClient(
            [
                json.dumps(
                    {"name": "spellblade", "description": "A duelist.", "hit_die": 10}
                )
            ]
        ),
    )
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character/class",
        json={"class_concept": "arcane duelist"},
    )

    assert resp.status_code == 200
    definition = resp.json()["class_definition"]
    assert definition["name"] == "spellblade"
    assert definition["description"] == "A duelist."
    assert definition["hit_die"] == 10


def test_create_class_preview_unknown_session_404(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.post(
        "/sessions/does-not-exist/character/class",
        json={"class_concept": "arcane duelist"},
    )

    assert resp.status_code == 404


# --- combined character: opening + goals/quests --------------------------


def _sheet_with_goals_raw() -> dict:
    raw = _valid_sheet_raw()
    raw["hit_die"] = 10
    raw["class_description"] = "A duelist who weaves cantrips into swordplay."
    raw["goals"] = [{"title": "Find the relic", "description": "deep in the ruins"}]
    raw["quests"] = [{"title": "Clear the crypt", "status": "complete"}]
    raw["opening"] = "  Mist clings to the cobblestones as you step into the square.  "
    raw["scene"] = "a foggy market square"
    return raw


def test_create_character_returns_opening_and_goals_quests(storage):
    client = _make_client(storage, FakeClient([json.dumps(_sheet_with_goals_raw())]))
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character",
        json={"description": "a sneaky elf"},
    )

    assert resp.status_code == 200
    data = resp.json()
    expected_opening = "Mist clings to the cobblestones as you step into the square."
    assert data["opening"] == expected_opening
    assert data["character"]["hit_die"] == 10
    assert (
        data["character"]["class_description"]
        == "A duelist who weaves cantrips into swordplay."
    )
    assert data["character"]["goals"][0]["title"] == "Find the relic"
    assert data["character"]["goals"][0]["status"] == "active"
    assert data["character"]["quests"][0]["status"] == "complete"

    # Opening seeded as first assistant message (non-empty only).
    assert storage.load_messages(session_id) == [
        {"role": "assistant", "content": expected_opening}
    ]

    # Goals/quests/hit_die/class_description persist on the reconstructed sheet.
    saved = storage.load_character(session_id)
    assert saved is not None
    assert saved.hit_die == 10
    assert saved.class_description == ("A duelist who weaves cantrips into swordplay.")
    assert saved.goals[0].title == "Find the relic"
    assert saved.quests[0].status == "complete"

    # Scene folded into game state.
    state = storage.load_state(session_id, saved)
    assert state is not None
    assert state.scene == "a foggy market square"


def test_create_character_without_opening_appends_no_message(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = storage.create_session("gothic")

    resp = client.post(
        f"/sessions/{session_id}/character",
        json={"description": "a sneaky elf"},
    )

    assert resp.status_code == 200
    assert resp.json()["opening"] == ""
    assert storage.load_messages(session_id) == []
