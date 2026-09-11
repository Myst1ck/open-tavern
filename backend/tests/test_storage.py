"""Tests for the SQLite storage layer."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

from open_tavern.character import CharacterSheet, Goal, Quest, normalize
from open_tavern.character.items import BaseType, Item
from open_tavern.state import new_state, set_scene
from open_tavern.storage import Storage
from open_tavern.storage.db import MESSAGE_LOAD_LIMIT, SchemaTooNewError


def _make_character(name: str = "Aria") -> CharacterSheet:
    return normalize(
        {
            "name": name,
            "race": "human",
            "character_class": "rogue",
            "level": 3,
            "abilities": {
                "STR": 10,
                "DEX": 16,
                "CON": 14,
                "INT": 12,
                "WIS": 8,
                "CHA": 18,
            },
            "skills": {"Stealth": True},
            "inventory": [
                {"name": "thieves' tools", "type": "loot", "quantity": 1},
                {"name": "dagger", "type": "weapon", "quantity": 1},
            ],
            "conditions": ["poisoned"],
            "backstory": "Grew up on the streets.",
        }
    )


@pytest.fixture
def storage(tmp_path):
    store = Storage(str(tmp_path / "test.db"))
    store.init()
    yield store
    store.close()


# --- init ----------------------------------------------------------------


def test_init_creates_tables(tmp_path):
    path = tmp_path / "db.sqlite"
    store = Storage(str(path))
    store.init()
    store.close()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()

    assert {"sessions", "characters", "messages", "items"} <= names


def test_init_works_with_memory_db():
    store = Storage(":memory:")
    store.init()
    session_id = store.create_session("gothic")
    loaded = store.load_session(session_id)
    assert loaded is not None
    assert loaded["world_theme"] == "gothic"
    store.close()


# --- migration ------------------------------------------------------------


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite"
    store = Storage(str(path))
    store.init()
    store.init()  # second init must not error
    store.close()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
    finally:
        conn.close()

    assert {"title", "updated_at", "state_json", "premise"} <= cols


def test_migration_preserves_legacy_unversioned_saves(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions ("
        "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, world_theme TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE characters ("
        "id INTEGER PRIMARY KEY, session_id TEXT NOT NULL UNIQUE, "
        "data_json TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE messages ("
        "id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL, "
        "content TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sessions (id, created_at, world_theme) VALUES ('abc', 't0', 'gothic')"
    )
    conn.commit()
    conn.close()

    store = Storage(str(path))
    store.init()
    store.close()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        rows = [tuple(r) for r in conn.execute("SELECT id, world_theme FROM sessions")]
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    # Legacy version-1 saves are MIGRATED forward, never dropped.
    assert {"title", "updated_at", "state_json", "premise"} <= cols
    assert rows == [("abc", "gothic")]
    assert version is not None and version["value"] == "4"


def test_migration_applies_steps_in_order(tmp_path):
    path = tmp_path / "v2.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '2')")
    conn.execute(
        "CREATE TABLE sessions ("
        "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, world_theme TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sessions (id, created_at, world_theme) VALUES ('abc', 't0', 'gothic')"
    )
    conn.commit()
    conn.close()

    store = Storage(str(path))
    store.init()
    store.close()

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        rows = [tuple(r) for r in conn.execute("SELECT id, world_theme FROM sessions")]
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        conn.close()

    # v2 -> v3 (items table) -> v4 (session columns), data preserved.
    assert "items" in tables
    assert {"title", "updated_at", "state_json", "premise"} <= cols
    assert rows == [("abc", "gothic")]
    assert version is not None and version["value"] == "4"


def test_migration_refuses_newer_database(tmp_path):
    path = tmp_path / "newer.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '99')")
    conn.execute(
        "CREATE TABLE sessions ("
        "id TEXT PRIMARY KEY, created_at TEXT NOT NULL, world_theme TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sessions (id, created_at, world_theme) VALUES ('abc', 't0', 'gothic')"
    )
    conn.commit()
    conn.close()

    store = Storage(str(path))
    with pytest.raises(SchemaTooNewError):
        store.init()
    store.close()

    # Refused, not dropped: version and data untouched.
    conn = sqlite3.connect(path)
    try:
        version = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        rows = [tuple(r) for r in conn.execute("SELECT id FROM sessions")]
    finally:
        conn.close()

    assert version is not None and version[0] == "99"
    assert rows == [("abc",)]


# --- premise ---------------------------------------------------------------


def test_create_session_with_premise(storage):
    session_id = storage.create_session(
        "gothic", premise="A vampire lord terrorizes the village."
    )
    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["premise"] == "A vampire lord terrorizes the village."


def test_create_session_premise_none_by_default(storage):
    session_id = storage.create_session("gothic")
    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["premise"] is None


def test_create_session_premise_empty_string(storage):
    session_id = storage.create_session("gothic", premise="")
    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["premise"] == ""


# --- sessions ------------------------------------------------------------


def test_create_session_returns_id_and_persists(storage):
    session_id = storage.create_session("high fantasy")
    assert session_id
    assert len(session_id) == 32  # uuid4().hex

    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["world_theme"] == "high fantasy"


def test_create_session_generates_unique_ids(storage):
    first = storage.create_session("gothic")
    second = storage.create_session("gothic")
    assert first != second


def test_create_session_defaults_title_to_world_theme(storage):
    storage.create_session("high fantasy")
    assert storage.list_sessions()[0]["title"] == "high fantasy"


def test_create_session_with_explicit_title(storage):
    session_id = storage.create_session("high fantasy", "My Tale")
    rows = storage.list_sessions()
    assert rows[0]["id"] == session_id
    assert rows[0]["title"] == "My Tale"


def test_create_session_empty_title_defaults_to_world_theme(storage):
    storage.create_session("gothic", "")
    assert storage.list_sessions()[0]["title"] == "gothic"


def test_create_session_sets_updated_at(storage):
    session_id = storage.create_session("gothic")
    rows = storage.list_sessions()
    assert rows[0]["id"] == session_id
    assert rows[0]["updated_at"] is not None


# --- character roundtrip -------------------------------------------------


def test_save_and_load_character_roundtrip(storage):
    session_id = storage.create_session("steampunk")
    sheet = _make_character()

    storage.save_character(session_id, sheet)
    loaded = storage.load_character(session_id)

    assert loaded is not None
    assert loaded == sheet


def test_load_character_missing_session_returns_none(storage):
    assert storage.load_character("does-not-exist") is None


def test_load_character_recomputes_derived_values(storage):
    session_id = storage.create_session("gothic")
    wounded = replace(_make_character(), hp=1)  # tamper with stored hp

    storage.save_character(session_id, wounded)
    loaded = storage.load_character(session_id)

    assert loaded is not None
    assert loaded.hp != 1
    assert loaded.hp == loaded.max_hp


def test_character_upsert_replaces_existing(storage):
    session_id = storage.create_session("gothic")
    storage.save_character(session_id, _make_character("Aria"))
    storage.save_character(session_id, _make_character("Bram"))

    loaded = storage.load_character(session_id)
    assert loaded is not None
    assert loaded.name == "Bram"


def test_save_and_load_character_with_inventory_roundtrip(storage):
    session_id = storage.create_session("gothic")
    sheet = normalize(
        {
            "name": "Aria",
            "race": "human",
            "character_class": "rogue",
            "level": 3,
            "abilities": {
                "STR": 10,
                "DEX": 16,
                "CON": 14,
                "INT": 12,
                "WIS": 8,
                "CHA": 18,
            },
            "inventory": [
                {"name": "Iron Dagger", "type": "weapon", "quantity": 1},
                {"name": "Health Potion", "type": "consumable", "quantity": 2},
            ],
        }
    )

    storage.save_character(session_id, sheet)
    loaded = storage.load_character(session_id)

    assert loaded is not None
    assert loaded == sheet
    assert loaded.inventory[0].type is BaseType.weapon
    assert loaded.inventory[1].type is BaseType.consumable


def test_item_with_enum_type_serializes_to_json():
    item = Item(name="Iron Dagger", type=BaseType.weapon)
    assert json.loads(json.dumps(item.to_dict()))["type"] == "weapon"


# --- messages ------------------------------------------------------------


def test_append_and_load_messages_ordered(storage):
    session_id = storage.create_session("gothic")
    storage.append_message(session_id, "user", "first")
    storage.append_message(session_id, "assistant", "second")
    storage.append_message(session_id, "user", "third")

    assert storage.load_messages(session_id) == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]


def test_save_and_load_state_roundtrip(storage):
    session_id = storage.create_session("gothic")
    sheet = _make_character()
    storage.save_character(session_id, sheet)

    state = new_state(sheet)
    state = set_scene(state, "the crypt")

    storage.save_state(session_id, state)
    loaded = storage.load_state(session_id, sheet)

    assert loaded == state


def test_load_state_returns_none_when_absent(storage):
    session_id = storage.create_session("gothic")
    assert storage.load_state(session_id, _make_character()) is None


def test_save_state_touches_updated_at(storage):
    first = storage.create_session("gothic")
    storage.create_session("western")
    sheet = _make_character()

    storage.save_state(first, new_state(sheet))

    # Saving state bumps ``first`` ahead of ``second`` in updated_at order.
    assert storage.list_sessions()[0]["id"] == first


# --- list_sessions --------------------------------------------------------


def test_list_sessions_orders_by_updated_at_desc(storage):
    first = storage.create_session("gothic")
    second = storage.create_session("western", "West")

    storage.touch_session(first)

    assert [r["id"] for r in storage.list_sessions()] == [first, second]


def test_list_sessions_includes_character_name(storage):
    session_id = storage.create_session("gothic")
    storage.save_character(session_id, _make_character("Aria"))

    assert storage.list_sessions()[0]["character_name"] == "Aria"


def test_list_sessions_character_name_none_when_absent(storage):
    storage.create_session("gothic")

    assert storage.list_sessions()[0]["character_name"] is None


# --- rename_session -------------------------------------------------------


def test_rename_session_updates_title(storage):
    session_id = storage.create_session("gothic")

    assert storage.rename_session(session_id, "New Title") is True
    assert storage.list_sessions()[0]["title"] == "New Title"


def test_rename_session_missing_returns_false(storage):
    assert storage.rename_session("does-not-exist", "x") is False


# --- delete_session -------------------------------------------------------


def test_delete_session_cascades(storage):
    session_id = storage.create_session("gothic")
    sheet = _make_character()
    storage.save_character(session_id, sheet)
    storage.append_message(session_id, "user", "hello")
    storage.save_state(session_id, new_state(sheet))

    assert storage.delete_session(session_id) is True

    assert storage.load_session(session_id) is None
    assert storage.load_character(session_id) is None
    assert storage.load_messages(session_id) == []
    assert storage.load_state(session_id, sheet) is None


def test_delete_session_missing_returns_false(storage):
    assert storage.delete_session("does-not-exist") is False


# --- touch_session --------------------------------------------------------


def test_touch_session_bumps_updated_at(storage):
    first = storage.create_session("gothic")
    storage.create_session("western")

    storage.touch_session(first)

    # first was created earlier; touching moves it to the front.
    assert storage.list_sessions()[0]["id"] == first


def test_messages_are_scoped_to_session(storage):
    first = storage.create_session("gothic")
    second = storage.create_session("western")
    storage.append_message(first, "user", "only here")

    assert storage.load_messages(second) == []


# --- load_session --------------------------------------------------------


def test_load_session_unknown_id_returns_none(storage):
    assert storage.load_session("does-not-exist") is None


def test_load_session_returns_full_state(storage):
    session_id = storage.create_session("space opera", premise="Deep space mystery")
    sheet = _make_character()
    storage.save_character(session_id, sheet)
    storage.append_message(session_id, "user", "hello")

    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["world_theme"] == "space opera"
    assert loaded["premise"] == "Deep space mystery"
    assert loaded["character"] == sheet
    assert loaded["messages"] == [{"role": "user", "content": "hello"}]


def test_load_session_character_none_when_not_saved(storage):
    session_id = storage.create_session("gothic")
    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["character"] is None
    assert loaded["messages"] == []


# --- SQL injection safety ------------------------------------------------


def test_special_characters_roundtrip_safely(storage):
    name = "O'Malley the 'Brave'"
    theme = "tavern of 'quotes' and \"ticks\""
    content = "don't -- drop tables; ' OR 1=1 --"

    session_id = storage.create_session(theme)
    storage.save_character(session_id, _make_character(name))
    storage.append_message(session_id, "user", content)

    loaded = storage.load_session(session_id)
    assert loaded is not None
    assert loaded["world_theme"] == theme
    assert loaded["character"] is not None
    assert loaded["character"].name == name
    assert loaded["messages"] == [{"role": "user", "content": content}]


def test_injection_does_not_create_extra_rows(storage):
    gothic_id = storage.create_session("gothic")
    malicious = "x'); DROP TABLE sessions; --"

    session_id = storage.create_session("western")
    storage.append_message(session_id, "user", malicious)

    assert storage.load_messages(session_id) == [{"role": "user", "content": malicious}]
    # Sessions table still intact.
    assert storage.load_session(gothic_id) is not None


def test_injection_safe_on_title_and_world_theme(storage):
    theme = "tavern'; DROP TABLE sessions; --"
    title = "x'); DELETE FROM sessions; --"

    session_id = storage.create_session(theme, title)
    storage.rename_session(session_id, "safe title")

    rows = storage.list_sessions()
    assert len(rows) == 1
    assert rows[0]["world_theme"] == theme
    assert rows[0]["title"] == "safe title"
    assert storage.load_session(session_id) is not None


# --- persona fields roundtrip -------------------------------------------


def test_save_and_load_character_roundtrips_persona_fields(storage):
    session_id = storage.create_session("gothic")
    sheet = normalize(
        {
            "name": "Kael",
            "race": "elf",
            "character_class": "ranger",
            "level": 2,
            "abilities": {
                "STR": 12,
                "DEX": 16,
                "CON": 13,
                "INT": 10,
                "WIS": 15,
                "CHA": 9,
            },
            "backstory": "Raised by forest rangers.",
            "personality": "stoic and reliable",
            "appearance": "broad-shouldered, short beard",
            "motivation": "protect his village",
        }
    )

    storage.save_character(session_id, sheet)
    loaded = storage.load_character(session_id)

    assert loaded is not None
    assert loaded == sheet
    assert loaded.personality == "stoic and reliable"
    assert loaded.appearance == "broad-shouldered, short beard"
    assert loaded.motivation == "protect his village"


def test_load_character_fills_empty_persona_defaults(storage):
    session_id = storage.create_session("gothic")
    storage.save_character(session_id, _make_character())

    loaded = storage.load_character(session_id)

    assert loaded is not None
    assert loaded.personality == ""
    assert loaded.appearance == ""
    assert loaded.motivation == ""


# --- schema v2: new character fields roundtrip ---------------------------


def _full_character() -> CharacterSheet:
    return normalize(
        {
            "name": "Vex",
            "race": "tiefling",
            "character_class": "spellblade",
            "level": 2,
            "hit_die": 10,
            "class_description": "A duelist who weaves cantrips into swordplay.",
            "abilities": {
                "STR": 14,
                "DEX": 16,
                "CON": 14,
                "INT": 14,
                "WIS": 10,
                "CHA": 12,
            },
            "goals": [
                {"title": "Find the relic", "description": "deep in the ruins"},
            ],
            "quests": [
                {"title": "Clear the crypt", "status": "complete"},
            ],
            "opening": "Mist clings to the cobblestones as you step into the square.",
        }
    )


def test_new_fields_roundtrip_persist_to_load(storage):
    session_id = storage.create_session("gothic")
    sheet = _full_character()

    storage.save_character(session_id, sheet)
    loaded = storage.load_character(session_id)

    assert loaded is not None
    assert loaded == sheet
    assert loaded.hit_die == 10
    assert loaded.class_description == ("A duelist who weaves cantrips into swordplay.")
    assert loaded.goals == (
        Goal(title="Find the relic", description="deep in the ruins", status="active"),
    )
    assert loaded.quests == (
        Quest(title="Clear the crypt", description="", status="complete"),
    )
    assert loaded.opening == (
        "Mist clings to the cobblestones as you step into the square."
    )


def test_reinit_same_version_preserves_data(storage):
    session_id = storage.create_session("gothic")
    storage.save_character(session_id, _make_character("Aria"))
    storage.append_message(session_id, "user", "hello")

    storage.init()  # idempotent no-op: version == SCHEMA_VERSION

    assert storage.load_session(session_id) is not None
    loaded = storage.load_character(session_id)
    assert loaded is not None
    assert loaded.name == "Aria"
    assert storage.load_messages(session_id) == [{"role": "user", "content": "hello"}]


def test_load_messages_returns_up_to_default_limit(storage):
    session_id = storage.create_session("gothic")
    for i in range(MESSAGE_LOAD_LIMIT + 100):
        storage.append_message(session_id, "user", f"msg-{i}")

    messages = storage.load_messages(session_id)

    assert len(messages) == MESSAGE_LOAD_LIMIT
    assert messages[0] == {"role": "user", "content": "msg-100"}
    assert messages[-1] == {"role": "user", "content": f"msg-{MESSAGE_LOAD_LIMIT + 99}"}


def test_load_messages_configurable_limit(storage, monkeypatch):
    monkeypatch.setattr("open_tavern.storage.db.MESSAGE_LOAD_LIMIT", 3)
    session_id = storage.create_session("gothic")
    for i in range(5):
        storage.append_message(session_id, "user", f"msg-{i}")

    assert storage.load_messages(session_id) == [
        {"role": "user", "content": "msg-2"},
        {"role": "user", "content": "msg-3"},
        {"role": "user", "content": "msg-4"},
    ]
