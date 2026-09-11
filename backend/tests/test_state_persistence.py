"""Tests for state serialization helpers (persist/restore)."""

from __future__ import annotations

import pytest

from open_tavern.character import normalize
from open_tavern.character.items import BaseType, Item
from open_tavern.state import (
    add_condition,
    add_item,
    apply_hp,
    new_state,
    set_scene,
    state_from_persistable,
    state_to_persistable,
)


@pytest.fixture
def character():
    return normalize(
        {
            "race": "human",
            "character_class": "rogue",
            "level": 2,
            "abilities": {
                "STR": 10,
                "DEX": 16,
                "CON": 14,
                "INT": 12,
                "WIS": 8,
                "CHA": 18,
            },
        }
    )


@pytest.fixture
def state(character):
    state = new_state(character)
    state = apply_hp(state, -5)
    state = add_item(state, Item(name="torch", type=BaseType.loot))
    state = add_item(state, Item(name="sword", type=BaseType.loot))
    state = add_condition(state, "poisoned")
    state = add_condition(state, "invisible")
    state = set_scene(state, "tavern")
    return state


# --- state_to_persistable -------------------------------------------------


def test_persistable_has_exact_keys(state):
    result = state_to_persistable(state)
    assert set(result) == {
        "current_hp",
        "max_hp",
        "conditions",
        "scene",
    }


def test_persistable_excludes_character(state):
    result = state_to_persistable(state)
    assert "character" not in result


def test_persistable_excludes_inventory(state):
    # inventory lives on the character projection, persisted separately
    result = state_to_persistable(state)
    assert "inventory" not in result


def test_persistable_conditions_is_sorted_list(state):
    result = state_to_persistable(state)
    assert result["conditions"] == ["invisible", "poisoned"]
    assert isinstance(result["conditions"], list)


def test_persistable_hp_and_scene(state):
    result = state_to_persistable(state)
    assert result["current_hp"] == state.max_hp - 5
    assert result["max_hp"] == state.max_hp
    assert result["scene"] == "tavern"


# --- state_from_persistable -----------------------------------------------


def test_round_trip_equality(state):
    rebuilt = state_from_persistable(state.character, state_to_persistable(state))
    assert rebuilt == state


def test_round_trip_uses_passed_character(state):
    data = state_to_persistable(state)
    # inject a hostile/stale character identity into data — must be ignored
    data["character"] = {"race": "orc"}
    rebuilt = state_from_persistable(state.character, data)
    assert rebuilt.character is state.character
    assert rebuilt == state


def test_from_persistable_hp_clamped_floor(character):
    rebuilt = state_from_persistable(
        character,
        {"current_hp": -100, "max_hp": character.max_hp},
    )
    assert rebuilt.current_hp == 0


def test_from_persistable_hp_clamped_ceiling(character):
    rebuilt = state_from_persistable(
        character,
        {"current_hp": 999999, "max_hp": character.max_hp},
    )
    assert rebuilt.current_hp == character.max_hp


def test_from_persistable_hp_ignores_stored_max_hp(character):
    # max_hp is recomputed from character, never trusted from data
    rebuilt = state_from_persistable(
        character,
        {"current_hp": 1, "max_hp": 1},
    )
    assert rebuilt.max_hp == character.max_hp
    assert rebuilt.current_hp == 1


def test_from_persistable_inventory_ignored(character):
    # inventory lives on the character projection; persisted data is ignored
    rebuilt = state_from_persistable(
        character,
        {"inventory": ["torch", 42, None, "sword", ["nested"]]},
    )
    assert rebuilt.character.inventory == character.inventory
    assert rebuilt == new_state(character)


def test_from_persistable_conditions_coerced(character):
    rebuilt = state_from_persistable(
        character,
        {"conditions": ["poisoned", "poisoned", 7, "invisible"]},
    )
    assert rebuilt.conditions == frozenset({"poisoned", "invisible"})


def test_from_persistable_scene_coerced(character):
    assert state_from_persistable(character, {"scene": "forest"}).scene == "forest"
    assert state_from_persistable(character, {"scene": 123}).scene == ""
    assert state_from_persistable(character, {"scene": None}).scene == ""


# --- defensive handling of malformed data ---------------------------------


def test_from_persistable_non_dict_returns_new_state(character):
    rebuilt = state_from_persistable(character, None)  # type: ignore[arg-type]
    assert rebuilt == new_state(character)


def test_from_persistable_missing_keys_uses_defaults(character):
    rebuilt = state_from_persistable(character, {})
    assert rebuilt == new_state(character)


def test_from_persistable_wrong_types_fall_back(character):
    rebuilt = state_from_persistable(
        character,
        {
            "current_hp": "lots",
            "inventory": {"not": "a list"},
            "conditions": "poisoned",
            "scene": [],
        },
    )
    assert rebuilt == new_state(character)


def test_from_persistable_bool_hp_rejected(character):
    # bool is an int subclass but must not be accepted as HP
    rebuilt = state_from_persistable(character, {"current_hp": True})
    assert rebuilt.current_hp == character.max_hp
