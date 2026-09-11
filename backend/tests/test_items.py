"""Tests for item deserialization coercion and inventory validation."""

from __future__ import annotations

from open_tavern.character import validate
from open_tavern.character.items import BaseType, Item, ItemStats
from open_tavern.character.models import AbilityScores, CharacterSheet


def _raw(**overrides) -> dict:
    d = {
        "name": "Iron Sword",
        "type": "weapon",
        "quantity": 1,
        "stats": {"damage": 5, "armor": 0},
    }
    d.update(overrides)
    return d


# --- Item.from_dict coercion --------------------------------------------


def test_from_dict_unknown_type_coerces_to_loot() -> None:
    item = Item.from_dict(_raw(type="artifact"))
    assert item.type is BaseType.loot


def test_from_dict_missing_type_defaults_to_loot() -> None:
    item = Item.from_dict(_raw(type=None))
    assert item.type is BaseType.loot


def test_from_dict_accepts_base_type_instance() -> None:
    item = Item.from_dict(_raw(type=BaseType.armor))
    assert item.type is BaseType.armor


def test_from_dict_quantity_coerced_to_int() -> None:
    item = Item.from_dict(_raw(quantity="3"))
    assert item.quantity == 3
    assert isinstance(item.quantity, int)


def test_from_dict_quantity_garbage_falls_back_to_one() -> None:
    item = Item.from_dict(_raw(quantity="many"))
    assert item.quantity == 1


def test_from_dict_quantity_float_truncated() -> None:
    item = Item.from_dict(_raw(quantity=2.9))
    assert item.quantity == 2


def test_from_dict_armor_clamped_non_negative() -> None:
    item = Item.from_dict(_raw(stats={"armor": -5}))
    assert item.stats.armor == 0


def test_from_dict_valid_input_unchanged() -> None:
    item = Item.from_dict(_raw())
    assert item.name == "Iron Sword"
    assert item.type is BaseType.weapon
    assert item.quantity == 1
    assert item.stats.damage == 5


# --- ItemStats.from_dict armor clamp ------------------------------------


def test_stats_armor_clamped_non_negative() -> None:
    stats = ItemStats.from_dict({"armor": -3})
    assert stats.armor == 0


# --- inventory validation -----------------------------------------------


def _valid_raw_with_inventory() -> dict:
    return {
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
        "inventory": [{"name": "Iron Sword", "type": "weapon"}],
    }


def test_validate_accepts_known_type() -> None:
    result = validate(_valid_raw_with_inventory())
    assert result.errors == ()


def test_validate_rejects_unknown_type() -> None:
    raw = _valid_raw_with_inventory()
    raw["inventory"][0]["type"] = "artifact"
    result = validate(raw)
    assert "'inventory' item 0 'type' must be one of" in " ".join(result.errors)


def test_validate_rejects_non_string_type() -> None:
    raw = _valid_raw_with_inventory()
    raw["inventory"][0]["type"] = 42
    result = validate(raw)
    assert "'inventory' item 0 'type' must be a string" in " ".join(result.errors)


# --- immutability: input containers are deep-copied ---------------------


def test_from_dict_immutable_stats_extra_copied() -> None:
    extra = {"element": "fire", "nested": {"charges": 3}}
    item = Item.from_dict(_raw(stats={"damage": 5, "extra": extra}))
    extra["element"] = "ice"
    extra["nested"]["charges"] = 0
    assert item.stats.extra["element"] == "fire"
    assert item.stats.extra["nested"]["charges"] == 3


def test_from_dict_immutable_tags_copied() -> None:
    tags = ["sharp", "heavy"]
    item = Item.from_dict(_raw(tags=tags))
    tags.append("cursed")
    assert item.tags == ("sharp", "heavy")


def test_stats_immutable_extra_copied_on_direct_construction() -> None:
    extra = {"charges": 2}
    stats = ItemStats(damage=4, extra=extra)
    extra["charges"] = 99
    assert stats.extra == {"charges": 2}


def test_stats_immutable_extra_copied_from_dict() -> None:
    extra = {"nested": {"v": 1}}
    stats = ItemStats.from_dict({"extra": extra})
    extra["nested"]["v"] = 2
    assert stats.extra == {"nested": {"v": 1}}


def test_character_sheet_immutable_skills_copied() -> None:
    skills = {"Acrobatics": True}
    sheet = CharacterSheet(
        race="human",
        character_class="rogue",
        level=3,
        abilities=AbilityScores(10, 16, 14, 12, 8, 18),
        skills=skills,
        hp=10,
        max_hp=10,
        proficiency_bonus=2,
    )
    skills["Acrobatics"] = False
    assert sheet.skills == {"Acrobatics": True}