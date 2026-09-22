"""API endpoint tests using a fake LLM client and in-memory storage.

No network or disk access: the real ``get_client`` / ``get_storage``
dependencies are replaced via ``app.dependency_overrides``.
"""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import open_tavern.api.routes as routes_module
from open_tavern.api.main import create_app
from open_tavern.api.ratelimit import RateLimiter
from open_tavern.api.routes import (
    _STATE_CACHE,
    build_client_from_headers,
    get_client,
    get_per_request_client,
    get_storage,
)
from open_tavern.character.items import BaseType, Item
from open_tavern.state import GameState, new_state
from open_tavern.storage import Storage
from open_tavern.story import OpenAIClient


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
        "inventory": [
            {"name": "dagger", "type": "weapon"},
            {"name": "lockpicks", "type": "loot"},
        ],
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
    # Inventory lives on the character projection, not the state envelope.
    assert [item["name"] for item in state["character"]["inventory"]] == [
        "dagger",
        "lockpicks",
    ]


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


def test_build_client_from_headers_partial_falls_back_to_env(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    client = build_client_from_headers(api_key="sk-test", model="")

    assert client.api_key == "sk-test"
    # No model supplied: fall back to OpenAIClient defaults.
    assert client.model == "gpt-4o-mini"


def test_build_client_from_headers_empty_values_overridden_by_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    client = build_client_from_headers(api_key=None, model=None)

    assert client.api_key == "env-key"
    assert client.base_url == "http://env:8000/v1"
    assert client.model == "env-model"


def test_get_per_request_client_honors_base_url_header(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    client = get_per_request_client(
        x_api_key="sk-test",
        x_model="llama3",
        x_base_url="https://openrouter.ai/api/v1",
    )

    assert isinstance(client, OpenAIClient)
    assert client.api_key == "sk-test"
    assert client.model == "llama3"
    # X-Base-Url is a recognized header: it overrides the env base URL.
    assert client.base_url == "https://openrouter.ai/api/v1"


def test_get_per_request_client_empty_base_url_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env:8000/v1")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    client = get_per_request_client(
        x_api_key="sk-test",
        x_model="llama3",
        x_base_url="",
    )

    assert isinstance(client, OpenAIClient)
    # Empty X-Base-Url is dropped: env base URL applies.
    assert client.base_url == "http://env:8000/v1"


def test_build_client_from_headers_invalid_base_url_raises_400(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    with pytest.raises(HTTPException) as excinfo:
        build_client_from_headers(
            api_key="sk-test", model="", base_url="not-a-url"
        )

    assert excinfo.value.status_code == 400


def test_x_base_url_header_blocked_by_endpoint(storage):
    fake = FakeClient(['{"theme": "gothic", "premise": "a haunted tavern"}'])
    client = _make_client(storage, fake)

    resp = client.post(
        "/world/generate",
        json={"description": "hi"},
        headers={"X-Base-Url": "http://169.254.169.254/v1"},
    )

    assert resp.status_code == 400
    assert not fake.calls  # blocked base URL rejected before any LLM call


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


# --- items ---------------------------------------------------------------


def _session_with_character(client: TestClient, storage: Storage) -> str:
    session_id = storage.create_session("gothic")
    resp = client.post(
        f"/sessions/{session_id}/character", json={"description": "elf"}
    )
    assert resp.status_code == 200
    return session_id


def _item_url(session_id: str, item_id: str | None = None) -> str:
    base = f"/sessions/{session_id}/characters/{session_id}/items"
    return base if item_id is None else f"{base}/{item_id}"


def test_create_item_creates_and_persists(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.post(
        _item_url(session_id),
        json={"name": "Iron Sword", "type": "weapon", "stats": {"damage": 5}},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["success"] is True
    assert data["item"]["name"] == "Iron Sword"
    assert data["item"]["type"] == "weapon"
    assert data["item"]["stats"]["damage"] == 5
    assert data["message"] == "Item 'Iron Sword' created"

    items = storage.load_items(session_id, session_id)
    assert len(items) == 1
    assert items[0].name == "Iron Sword"


def test_create_item_defaults_type_to_loot(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.post(_item_url(session_id), json={"name": "Trinket"})

    assert resp.status_code == 201
    assert resp.json()["item"]["type"] == "loot"


def test_create_item_invalid_type_422(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.post(_item_url(session_id), json={"name": "X", "type": "artifact"})

    assert resp.status_code == 422
    assert "Invalid item type" in resp.json()["detail"]


def test_create_item_missing_name_422(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.post(_item_url(session_id), json={"type": "weapon"})

    assert resp.status_code == 422


def test_create_item_unknown_session_404(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.post(
        "/sessions/does-not-exist/characters/does-not-exist/items",
        json={"name": "X"},
    )

    assert resp.status_code == 404


def test_create_item_before_character_404(storage):
    client = _make_client(storage, FakeClient([]))
    session_id = storage.create_session("gothic")

    resp = client.post(_item_url(session_id), json={"name": "X"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "character not found"


def test_create_item_rate_limited(storage, monkeypatch):
    monkeypatch.setattr(routes_module, "_item_limiter", RateLimiter(3, 60.0))
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    for _ in range(3):
        resp = client.post(_item_url(session_id), json={"name": "X"})
        assert resp.status_code == 201

    resp = client.post(_item_url(session_id), json={"name": "X"})
    assert resp.status_code == 429


def test_list_items(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    client.post(_item_url(session_id), json={"name": "Sword", "type": "weapon"})
    client.post(_item_url(session_id), json={"name": "Potion", "type": "consumable"})

    resp = client.get(_item_url(session_id))

    assert resp.status_code == 200
    names = {item["name"] for item in resp.json()["items"]}
    assert names == {"Sword", "Potion"}


def test_get_item(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    created = client.post(_item_url(session_id), json={"name": "Sword"}).json()
    item_id = created["item"]["id"]

    resp = client.get(_item_url(session_id, item_id))

    assert resp.status_code == 200
    assert resp.json()["name"] == "Sword"


def test_get_item_unknown_404(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.get(_item_url(session_id, "nope"))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "item not found"


def test_delete_item(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    item_id = client.post(_item_url(session_id), json={"name": "Sword"}).json()[
        "item"
    ]["id"]

    resp = client.delete(_item_url(session_id, item_id))

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert storage.load_items(session_id, session_id) == []


def test_delete_item_missing_returns_success_false(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.delete(_item_url(session_id, "nope"))

    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["message"] == "item not found"


def test_equip_item(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    item_id = client.post(_item_url(session_id), json={"name": "Sword"}).json()[
        "item"
    ]["id"]

    resp = client.post(_item_url(session_id, f"{item_id}/equip"))

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["item"]["equipped"] is True


def test_unequip_item(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    item_id = client.post(_item_url(session_id), json={"name": "Sword"}).json()[
        "item"
    ]["id"]
    client.post(_item_url(session_id, f"{item_id}/equip"))

    resp = client.post(_item_url(session_id, f"{item_id}/unequip"))

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["item"]["equipped"] is False


def test_use_item_consumable_depletes(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    item_id = client.post(
        _item_url(session_id), json={"name": "Potion", "type": "consumable"}
    ).json()["item"]["id"]

    resp = client.post(_item_url(session_id, f"{item_id}/use"))

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["item"] is None
    assert data["message"] == "Item 'Potion' used and depleted"
    assert storage.load_items(session_id, session_id) == []


def test_use_item_consumable_decrements_quantity(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    potion = Item(name="Potion", type=BaseType.consumable, quantity=2)
    storage.save_item(session_id, session_id, potion)

    resp = client.post(_item_url(session_id, f"{potion.id}/use"))

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["item"]["quantity"] == 1
    assert data["message"] == "Item 'Potion' used"
    assert storage.load_items(session_id, session_id)[0].quantity == 1


def test_use_item_non_consumable_fails(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)
    item_id = client.post(
        _item_url(session_id), json={"name": "Sword", "type": "weapon"}
    ).json()["item"]["id"]

    resp = client.post(_item_url(session_id, f"{item_id}/use"))

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "is not consumable" in data["message"]


def test_use_item_unknown_returns_success_false(storage):
    client = _make_client(storage, FakeClient([json.dumps(_valid_sheet_raw())]))
    session_id = _session_with_character(client, storage)

    resp = client.post(_item_url(session_id, "nope/use"))

    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert resp.json()["message"] == "item not found"


# --- world generation ----------------------------------------------------


def test_world_generate_from_description(storage):
    fake = FakeClient(['{"theme": "gothic horror", "premise": "a haunted tavern"}'])
    client = _make_client(storage, fake)

    resp = client.post("/world/generate", json={"description": "spooky tavern"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["theme"] == "gothic horror"
    assert data["premise"] == "a haunted tavern"
    assert fake.calls[0]["json_mode"] is True


def test_world_generate_surprise(storage):
    fake = FakeClient(['{"theme": "space opera", "premise": "a dying star"}'])
    client = _make_client(storage, fake)

    resp = client.post("/world/generate", json={"surprise": True})

    assert resp.status_code == 200
    assert resp.json()["theme"] == "space opera"


def test_world_generate_empty_description_without_surprise_422(storage):
    client = _make_client(storage, FakeClient([]))

    resp = client.post("/world/generate", json={"description": ""})

    assert resp.status_code == 422


def test_world_generate_invalid_llm_json_502(storage):
    client = _make_client(storage, FakeClient(["not json"]))

    resp = client.post("/world/generate", json={"description": "spooky"})

    assert resp.status_code == 502


def test_world_generate_missing_fields_502(storage):
    client = _make_client(storage, FakeClient(['{"theme": "gothic horror"}']))

    resp = client.post("/world/generate", json={"description": "spooky"})

    assert resp.status_code == 502


def test_world_generate_rate_limited(storage, monkeypatch):
    monkeypatch.setattr(routes_module, "_world_limiter", RateLimiter(3, 60.0))
    responses = [
        '{"theme": "gothic horror", "premise": "a haunted tavern"}' for _ in range(3)
    ]
    client = _make_client(storage, FakeClient(responses))

    for _ in range(3):
        resp = client.post("/world/generate", json={"description": "spooky"})
        assert resp.status_code == 200

    resp = client.post("/world/generate", json={"description": "spooky"})
    assert resp.status_code == 429
