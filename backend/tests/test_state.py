"""Tests for immutable game state and pure reducers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from open_tavern.character import normalize
from open_tavern.character.items import BaseType, Item
from open_tavern.state import (
    add_condition,
    add_item,
    apply_hp,
    new_state,
    remove_condition,
    remove_item,
    set_scene,
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
    return new_state(character)


# --- new_state ----------------------------------------------------------


def test_new_state_initializes_hp_to_max_hp(character):
    state = new_state(character)
    assert state.current_hp == character.max_hp
    assert state.max_hp == character.max_hp
    assert state.character.inventory == ()
    assert state.conditions == frozenset()
    assert state.scene == ""


def test_state_embeds_character(character):
    state = new_state(character)
    assert state.character is character


def test_game_state_is_frozen(character):
    state = new_state(character)
    with pytest.raises(FrozenInstanceError):
        state.current_hp = 0  # type: ignore[misc]


# --- apply_hp -----------------------------------------------------------


def test_apply_hp_heals_below_max(state):
    damaged = apply_hp(state, -5)
    healed = apply_hp(damaged, 3)
    assert healed.current_hp == state.max_hp - 2


def test_apply_hp_negative_delta(state):
    result = apply_hp(state, -5)
    assert result.current_hp == state.max_hp - 5


def test_apply_hp_clamps_floor(state):
    result = apply_hp(state, -9999)
    assert result.current_hp == 0


def test_apply_hp_clamps_ceiling(state):
    result = apply_hp(state, 9999)
    assert result.current_hp == state.max_hp


# --- inventory ----------------------------------------------------------


def test_add_item_adds(state):
    result = add_item(state, Item(name="torch", type=BaseType.loot))
    assert result.character.inventory[0].name == "torch"
    assert state.character.inventory == ()


def test_add_item_no_duplicates(state):
    item = Item(name="torch", type=BaseType.loot)
    once = add_item(state, item)
    twice = add_item(once, item)
    assert len(twice.character.inventory) == 1
    assert twice.character.inventory == once.character.inventory


def test_remove_item_removes(state):
    with_item = add_item(state, Item(name="torch", type=BaseType.loot))
    item_id = with_item.character.inventory[0].id
    result = remove_item(with_item, item_id)
    assert result.character.inventory == ()


def test_remove_item_absent_noop(state):
    result = remove_item(state, "no-such-id")
    assert result.character.inventory == ()
    assert result == state


# --- conditions ---------------------------------------------------------


def test_add_condition_adds(state):
    result = add_condition(state, "poisoned")
    assert result.conditions == frozenset({"poisoned"})
    assert state.conditions == frozenset()


def test_add_condition_idempotent(state):
    once = add_condition(state, "poisoned")
    twice = add_condition(once, "poisoned")
    assert twice.conditions == frozenset({"poisoned"})
    assert twice == once


def test_remove_condition_removes(state):
    with_condition = add_condition(state, "poisoned")
    result = remove_condition(with_condition, "poisoned")
    assert result.conditions == frozenset()


def test_remove_condition_absent_noop(state):
    result = remove_condition(state, "poisoned")
    assert result.conditions == frozenset()
    assert result == state


# --- scene --------------------------------------------------------------


def test_set_scene(state):
    result = set_scene(state, "tavern")
    assert result.scene == "tavern"
    assert state.scene == ""


# --- immutability -------------------------------------------------------


def test_original_state_unchanged(character):
    original = new_state(character)
    apply_hp(original, -3)
    add_item(original, Item(name="sword", type=BaseType.loot))
    add_condition(original, "poisoned")
    set_scene(original, "forest")
    assert original.current_hp == character.max_hp
    assert original.character.inventory == ()
    assert original.conditions == frozenset()
    assert original.scene == ""
