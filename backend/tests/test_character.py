"""Tests for character sheet models and validation."""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError

import pytest

from open_tavern.character import (
    SKILLS,
    AbilityScores,
    Goal,
    Quest,
    ability_modifier,
    max_hp_for,
    normalize,
    proficiency_bonus,
    validate,
)


def _valid_raw() -> dict:
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
    }


# --- ability modifier ---------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (3, -4), (4, -3), (5, -3), (6, -2), (7, -2), (8, -1),
        (9, -1), (10, 0), (11, 0), (12, 1), (13, 1), (14, 2),
        (15, 2), (16, 3), (17, 3), (18, 4),
    ],
)
def test_ability_modifier_formula(score, expected):
    assert ability_modifier(score) == expected


def test_ability_modifier_for_all_six_abilities():
    sheet = normalize(
        {
            "race": "human",
            "character_class": "rogue",
            "abilities": {
                "STR": 15,
                "DEX": 16,
                "CON": 14,
                "INT": 12,
                "WIS": 8,
                "CHA": 10,
            },
        }
    )
    expected = {"STR": 2, "DEX": 3, "CON": 2, "INT": 1, "WIS": -1, "CHA": 0}
    for ability, mod in expected.items():
        assert sheet.ability_modifier(ability) == mod


# --- proficiency bonus --------------------------------------------------


@pytest.mark.parametrize(
    "level,expected",
    [
        (1, 2), (2, 2), (3, 2), (4, 2),
        (5, 3), (8, 3),
        (9, 4), (12, 4),
        (13, 5), (16, 5),
        (17, 6), (20, 6),
    ],
)
def test_proficiency_bonus(level, expected):
    assert proficiency_bonus(level) == expected


# --- hit points ---------------------------------------------------------


@pytest.mark.parametrize("hit_die", [6, 8, 10, 12])
def test_max_hp_level_one(hit_die):
    # CON 14 -> +2 modifier
    assert max_hp_for(hit_die, 1, 14) == hit_die + 2


def test_max_hp_accumulates_across_levels():
    # d10, CON 16 (+3): level 1 = 10 + 3 = 13; each later level adds 6 + 3 = 9
    assert max_hp_for(10, 1, 16) == 13
    assert max_hp_for(10, 2, 16) == 13 + 9
    assert max_hp_for(10, 5, 16) == 13 + 4 * 9


def test_max_hp_negative_con_modifier():
    # d6, CON 8 (-1): level 1 = 6 - 1 = 5
    assert max_hp_for(6, 1, 8) == 5


def test_normalize_sets_hp_equal_to_max_hp():
    sheet = normalize(
        {
            "race": "human",
            "character_class": "rogue",
            "level": 1,
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
    assert sheet.max_hp == 10  # d8 + 2
    assert sheet.hp == sheet.max_hp


def test_normalize_ignores_input_hp():
    raw = _valid_raw()
    raw["level"] = 1
    raw["hp"] = 9999
    sheet = normalize(raw)
    assert sheet.max_hp == 8 + 2  # rogue d8, CON 14
    assert sheet.hp == sheet.max_hp


# --- validate -----------------------------------------------------------


def test_validate_accepts_valid_sheet():
    result = validate(_valid_raw())
    assert result.is_valid
    assert result.errors == ()


def test_validate_rejects_non_mapping():
    result = validate("not a dict")
    assert not result.is_valid
    assert result.errors == ("character sheet must be a mapping",)


@pytest.mark.parametrize(
    "mutate,substring",
    [
        (lambda r: r.pop("abilities"), "missing 'abilities'"),
        (lambda r: r.update(abilities="nope"), "'abilities' must be a mapping"),
        (lambda r: r["abilities"].update(STR=25), "out of range"),
        (lambda r: r["abilities"].update(STR="high"), "must be an integer"),
        (lambda r: r["abilities"].update(STR=True), "must be an integer"),
        (lambda r: r["abilities"].update(LUK=10), "unknown ability key"),
        (lambda r: r["abilities"].pop("CON"), "missing ability score 'CON'"),
        (lambda r: r.update(level=-1), "'level' must be a positive integer"),
        (lambda r: r.update(character_class="   "), "'character_class' must be a non-empty string"),
        (lambda r: r.pop("character_class"), "missing 'character_class'"),
        (lambda r: r.update(race=123), "'race' must be a string"),
        (lambda r: r.update(skills="yes"), "'skills' must be a mapping"),
        (lambda r: r.update(skills={"Stealth": "yes"}), "must be a boolean"),
        (lambda r: r.update(skills={"Pickpocketing": True}), "unknown skill"),
        (lambda r: r.update(inventory="sword"), "'inventory' must be a list of strings"),
        (lambda r: r.update(name=42), "'name' must be a string"),
    ],
)
def test_validate_rejects_malformed(mutate, substring):
    raw = _valid_raw()
    mutate(raw)
    result = validate(raw)
    assert not result.is_valid
    assert substring in " ".join(result.errors)


# --- normalize ----------------------------------------------------------


def test_normalize_fills_defaults():
    sheet = normalize(
        {
            "race": "elf",
            "character_class": "wizard",
            "abilities": {
                "STR": 8,
                "DEX": 14,
                "CON": 12,
                "INT": 18,
                "WIS": 10,
                "CHA": 12,
            },
        }
    )
    assert sheet.name == ""
    assert sheet.level == 1
    assert sheet.inventory == ()
    assert sheet.conditions == ()
    assert sheet.backstory == ""
    assert sheet.skills == {skill: False for skill in SKILLS}


def test_normalize_recomputes_derived_values():
    sheet = normalize(
        {
            "race": "half-orc",
            "character_class": "barbarian",
            "level": 3,
            "hit_die": 12,
            "abilities": {
                "STR": 16,
                "DEX": 14,
                "CON": 16,
                "INT": 12,
                "WIS": 10,
                "CHA": 8,
            },
        }
    )
    assert sheet.proficiency_bonus == 2  # level 3
    assert sheet.ability_modifier("STR") == 3
    assert sheet.ability_modifier("CON") == 3
    # d12 + 3 at level 1, plus (7 + 3) for levels 2 and 3
    assert sheet.max_hp == 12 + 3 + 2 * 10  # 35
    assert sheet.hp == sheet.max_hp


def test_normalize_raises_on_invalid():
    with pytest.raises(ValueError):
        normalize({"race": "human"})


# --- skill modifier -----------------------------------------------------


def test_skill_modifier_proficient_and_not():
    sheet = normalize(
        {
            "race": "human",
            "character_class": "rogue",
            "level": 5,
            "abilities": {
                "STR": 10,
                "DEX": 18,
                "CON": 12,
                "INT": 12,
                "WIS": 10,
                "CHA": 14,
            },
            "skills": {"Stealth": True, "Perception": False},
        }
    )
    assert sheet.proficiency_bonus == 3  # level 5
    assert sheet.ability_modifier("DEX") == 4
    # Stealth -> DEX +4, proficient -> +3 = 7
    assert sheet.skill_modifier("Stealth") == 7
    # Perception -> WIS +0, not proficient -> 0
    assert sheet.skill_modifier("Perception") == 0


def test_skill_modifier_case_insensitive():
    sheet = normalize(
        {
            "race": "human",
            "character_class": "rogue",
            "level": 1,
            "abilities": {
                "STR": 10,
                "DEX": 16,
                "CON": 14,
                "INT": 12,
                "WIS": 8,
                "CHA": 18,
            },
            "skills": {"stealth": True},
        }
    )
    assert sheet.skill_modifier("stealth") == sheet.skill_modifier("Stealth")


# --- dice reuse ---------------------------------------------------------


def test_roll_check_uses_derived_modifier():
    sheet = normalize(
        {
            "race": "human",
            "character_class": "rogue",
            "level": 1,
            "abilities": {
                "STR": 10,
                "DEX": 16,
                "CON": 14,
                "INT": 12,
                "WIS": 8,
                "CHA": 18,
            },
            "skills": {"Stealth": True},
        }
    )
    rng = random.Random(0)
    d20 = rng.randint(1, 20)
    result = sheet.roll_check("Stealth", 15, rng=random.Random(0))
    # DEX +3, proficiency +2 = +5
    assert result.modifier == 5
    assert result.d20_value == d20
    assert result.total == d20 + 5


# --- immutability -------------------------------------------------------


def test_character_sheet_is_frozen():
    sheet = normalize(_valid_raw())
    with pytest.raises(FrozenInstanceError):
        sheet.hp = 0  # type: ignore[misc]


def test_ability_scores_is_frozen():
    scores = AbilityScores(
        strength=10, dexterity=10, constitution=10,
        intelligence=10, wisdom=10, charisma=10,
    )
    with pytest.raises(FrozenInstanceError):
        scores.strength = 12  # type: ignore[misc]


# --- persona fields (personality / appearance / motivation) -------------


def test_normalize_fills_persona_defaults():
    sheet = normalize(
        {
            "race": "elf",
            "character_class": "wizard",
            "abilities": {
                "STR": 8,
                "DEX": 14,
                "CON": 12,
                "INT": 18,
                "WIS": 10,
                "CHA": 12,
            },
        }
    )
    assert sheet.personality == ""
    assert sheet.appearance == ""
    assert sheet.motivation == ""


def test_normalize_preserves_persona_fields():
    raw = _valid_raw()
    raw["personality"] = "gritty and pragmatic"
    raw["appearance"] = "scarred left cheek"
    raw["motivation"] = "avenge her brother"
    sheet = normalize(raw)
    assert sheet.personality == "gritty and pragmatic"
    assert sheet.appearance == "scarred left cheek"
    assert sheet.motivation == "avenge her brother"


def test_validate_accepts_persona_fields():
    raw = _valid_raw()
    raw["personality"] = "cheerful"
    raw["appearance"] = "short red hair"
    raw["motivation"] = "find a lost artifact"
    result = validate(raw)
    assert result.is_valid
    assert result.errors == ()


@pytest.mark.parametrize(
    "field",
    ["personality", "appearance", "motivation"],
)
def test_validate_rejects_non_string_persona_field(field):
    raw = _valid_raw()
    raw[field] = 42
    result = validate(raw)
    assert not result.is_valid
    assert f"'{field}' must be a string" in " ".join(result.errors)


# --- ability score range edges ------------------------------------------


def test_validate_accepts_ability_boundaries():
    raw = _valid_raw()
    raw["abilities"]["STR"] = 3  # MIN_ABILITY_SCORE
    raw["abilities"]["CHA"] = 18  # MAX_ABILITY_SCORE
    result = validate(raw)
    assert result.is_valid


@pytest.mark.parametrize(
    "score",
    [2, 19],
)
def test_validate_rejects_ability_out_of_range_edges(score):
    raw = _valid_raw()
    raw["abilities"]["STR"] = score
    result = validate(raw)
    assert not result.is_valid
    assert "out of range" in " ".join(result.errors)


# --- free-form class (no whitelist) --------------------------------------


def test_validate_accepts_free_form_class():
    raw = _valid_raw()
    raw["character_class"] = "spellblade"
    result = validate(raw)
    assert result.is_valid
    assert result.errors == ()


def test_normalize_preserves_free_form_class():
    raw = _valid_raw()
    raw["character_class"] = "dragon rider"
    sheet = normalize(raw)
    assert sheet.character_class == "dragon rider"


# --- hit die -------------------------------------------------------------


@pytest.mark.parametrize("hit_die", [6, 8, 10, 12])
def test_validate_accepts_valid_hit_die(hit_die):
    raw = _valid_raw()
    raw["hit_die"] = hit_die
    result = validate(raw)
    assert result.is_valid


def test_validate_rejects_hit_die_not_in_sizes():
    raw = _valid_raw()
    raw["hit_die"] = 7
    result = validate(raw)
    assert not result.is_valid
    assert "'hit_die' must be one of (6, 8, 10, 12)" in " ".join(result.errors)


def test_validate_rejects_non_integer_hit_die():
    raw = _valid_raw()
    raw["hit_die"] = "10"
    result = validate(raw)
    assert not result.is_valid
    assert "'hit_die' must be an integer" in " ".join(result.errors)


# --- goals / quests ------------------------------------------------------


def test_validate_accepts_goals_and_quests():
    raw = _valid_raw()
    raw["goals"] = [{"title": "Find the relic", "description": "deep in the ruins"}]
    raw["quests"] = [
        {"title": "Save the village", "status": "complete"},
    ]
    result = validate(raw)
    assert result.is_valid
    assert result.errors == ()


def test_validate_rejects_goal_without_title():
    raw = _valid_raw()
    raw["goals"] = [{"description": "no title here"}]
    result = validate(raw)
    assert not result.is_valid
    assert "'goals' item 0 'title' must be a non-empty string" in " ".join(
        result.errors
    )


def test_validate_rejects_goal_with_blank_title():
    raw = _valid_raw()
    raw["goals"] = [{"title": "   "}]
    result = validate(raw)
    assert not result.is_valid
    assert "'goals' item 0 'title' must be a non-empty string" in " ".join(
        result.errors
    )


def test_validate_rejects_goal_with_bad_status():
    raw = _valid_raw()
    raw["goals"] = [{"title": "Quest", "status": "pending"}]
    result = validate(raw)
    assert not result.is_valid
    assert "'goals' item 0 'status' must be one of" in " ".join(result.errors)


def test_validate_rejects_goal_with_non_string_status():
    raw = _valid_raw()
    raw["goals"] = [{"title": "Quest", "status": 3}]
    result = validate(raw)
    assert not result.is_valid
    assert "'goals' item 0 'status' must be a string" in " ".join(result.errors)


def test_validate_rejects_goal_item_that_is_not_an_object():
    raw = _valid_raw()
    raw["goals"] = ["not a mapping"]
    result = validate(raw)
    assert not result.is_valid
    assert "'goals' item 0 must be an object" in " ".join(result.errors)


def test_validate_rejects_quest_with_bad_status():
    raw = _valid_raw()
    raw["quests"] = [{"title": "Task", "status": "pending"}]
    result = validate(raw)
    assert not result.is_valid
    assert "'quests' item 0 'status' must be one of" in " ".join(result.errors)


def test_normalize_reconstructs_goals_and_quests():
    raw = _valid_raw()
    raw["goals"] = [
        {
            "title": "Find the relic",
            "description": "deep in the ruins",
            "status": "failed",
        },
        {"title": "Only a title"},
    ]
    raw["quests"] = [
        {"title": "Save the village", "status": "complete"},
        {"title": "Empty quest", "description": ""},
    ]
    sheet = normalize(raw)
    assert sheet.goals == (
        Goal(
            title="Find the relic",
            description="deep in the ruins",
            status="failed",
        ),
        Goal(title="Only a title"),
    )
    assert sheet.quests == (
        Quest(title="Save the village", status="complete"),
        Quest(title="Empty quest", description=""),
    )


def test_normalize_recomputes_hp_from_hit_die():
    raw = _valid_raw()  # level 3, CON 14
    raw["hit_die"] = 10
    sheet = normalize(raw)
    assert sheet.hit_die == 10
    # d10: level 1 = 10 + 2, plus (6 + 2) for each of levels 2 and 3
    assert sheet.max_hp == max_hp_for(10, 3, 14)  # 28
    assert sheet.hp == sheet.max_hp
