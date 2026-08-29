"""Tests for the GM tag protocol parser."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from open_tavern.protocol import (
    CheckAction,
    ConditionAction,
    DamageAction,
    HpAction,
    ItemAction,
    ParsedTurn,
    parse,
)


# --- single-tag parsing -------------------------------------------------


def test_check_ability_tag():
    turn = parse("[CHECK:strength DC15]")
    assert turn.narration == ""
    assert turn.actions == (CheckAction(kind="check", name="strength", ability="STR", skill=None, dc=15),)


def test_check_skill_tag():
    turn = parse("[CHECK:athletics DC12]")
    assert turn.actions == (CheckAction(kind="check", name="athletics", ability=None, skill="Athletics", dc=12),)


def test_check_ability_is_case_insensitive():
    turn = parse("[CHECK:STRENGTH DC15]")
    action = turn.actions[0]
    assert isinstance(action, CheckAction)
    assert action.ability == "STR"
    assert action.skill is None
    assert action.dc == 15
    assert action.name == "STRENGTH"


def test_check_skill_is_case_insensitive():
    turn = parse("[CHECK:ATHLETICS DC12]")
    action = turn.actions[0]
    assert isinstance(action, CheckAction)
    assert action.skill == "Athletics"
    assert action.ability is None


def test_check_multiword_skill():
    turn = parse("[CHECK:sleight of hand DC15]")
    action = turn.actions[0]
    assert isinstance(action, CheckAction)
    assert action.skill == "Sleight of Hand"
    assert action.dc == 15


def test_check_unknown_name_is_flagged_not_dropped():
    turn = parse("[CHECK:bluff DC10]")
    action = turn.actions[0]
    assert isinstance(action, CheckAction)
    assert action.name == "bluff"
    assert action.ability is None
    assert action.skill is None
    assert action.dc == 10


def test_damage_tag():
    turn = parse("[DAMAGE:2d6+3]")
    assert turn.actions == (DamageAction(kind="damage", dice="2d6+3"),)


def test_damage_tag_normalizes_case_and_whitespace():
    turn = parse("[DAMAGE: 2D6 + 3 ]")
    action = turn.actions[0]
    assert isinstance(action, DamageAction)
    assert action.dice == "2d6+3"


def test_damage_bare_number():
    turn = parse("[DAMAGE:5]")
    action = turn.actions[0]
    assert isinstance(action, DamageAction)
    assert action.dice == "5"


def test_item_add_tag():
    turn = parse("[ITEM:+sword]")
    assert turn.actions == (ItemAction(kind="item", sign="+", name="sword"),)


def test_item_remove_tag():
    turn = parse("[ITEM:-sword]")
    assert turn.actions == (ItemAction(kind="item", sign="-", name="sword"),)


def test_item_name_strips_whitespace():
    turn = parse("[ITEM:+  sword ]")
    action = turn.actions[0]
    assert isinstance(action, ItemAction)
    assert action.sign == "+"
    assert action.name == "sword"


def test_hp_positive_tag():
    turn = parse("[HP:+5]")
    assert turn.actions == (HpAction(kind="hp", delta=5),)


def test_hp_negative_tag():
    turn = parse("[HP:-3]")
    assert turn.actions == (HpAction(kind="hp", delta=-3),)


def test_condition_add_tag():
    turn = parse("[CONDITION:+poisoned]")
    assert turn.actions == (ConditionAction(kind="condition", sign="+", name="poisoned"),)


def test_condition_remove_tag():
    turn = parse("[CONDITION:-poisoned]")
    assert turn.actions == (ConditionAction(kind="condition", sign="-", name="poisoned"),)


# --- narration stripping ------------------------------------------------


def test_plain_text_yields_empty_actions():
    turn = parse("You enter a dimly lit tavern.")
    assert turn.narration == "You enter a dimly lit tavern."
    assert turn.actions == ()


def test_tag_stripped_from_narration():
    turn = parse("You take a swing. [DAMAGE:2d6+3] The goblin reels.")
    assert turn.narration == "You take a swing. The goblin reels."
    assert turn.actions == (DamageAction(kind="damage", dice="2d6+3"),)


def test_whitespace_is_normalized():
    turn = parse("  The   door\nopens.  ")
    assert turn.narration == "The door opens."


def test_mixed_narration_and_tags_preserve_order():
    text = (
        "The orc charges. [CHECK:strength DC15] "
        "You dodge [HP:-3] and grab [ITEM:+shield]."
    )
    turn = parse(text)
    assert turn.narration == "The orc charges. You dodge and grab ."
    kinds = [action.kind for action in turn.actions]
    assert kinds == ["check", "hp", "item"]


def test_multiple_tags_no_text_between():
    turn = parse("[HP:+5][HP:-3]")
    assert turn.narration == ""
    assert turn.actions == (HpAction(kind="hp", delta=5), HpAction(kind="hp", delta=-3))


# --- malformed / unrecognized tags --------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "[HP:abc]",
        "[HP:5]",
        "[HP:]",
        "[HP:+]",
        "[CHECK:strength]",
        "[CHECK:strength DC]",
        "[CHECK:strength DCxyz]",
        "[CHECK: DC15]",
        "[CHECK:strength DC-15]",
        "[DAMAGE:2z6]",
        "[DAMAGE:]",
        "[ITEM:sword]",
        "[ITEM:+]",
        "[CONDITION:poisoned]",
        "[CONDITION:-]",
    ],
)
def test_malformed_tags_are_ignored_without_raising(text):
    turn = parse(text)
    assert turn.actions == ()
    assert turn.narration == ""


def test_unrecognized_tag_stays_in_narration():
    turn = parse("You see [SECRET:xyz] and [HP:+5].")
    assert turn.narration == "You see [SECRET:xyz] and ."
    assert turn.actions == (HpAction(kind="hp", delta=5),)


def test_unmatched_brackets_stay_in_narration():
    turn = parse("A [check] and [] and [CHECK] remain prose.")
    assert turn.actions == ()
    assert "check" in turn.narration


def test_parsing_never_raises_on_garbage():
    turn = parse("[][][HP:+1][ITEM:+][[CHECK: DC]][DAMAGE:\\\\]")
    assert turn.actions == (HpAction(kind="hp", delta=1),)


# --- dataclass properties -----------------------------------------------


def test_actions_are_frozen():
    action = parse("[HP:+5]").actions[0]
    assert isinstance(action, HpAction)
    with pytest.raises(FrozenInstanceError):
        action.delta = 99  # type: ignore[misc]


def test_parsed_turn_is_frozen():
    turn = parse("hi")
    assert isinstance(turn, ParsedTurn)
    with pytest.raises(FrozenInstanceError):
        turn.narration = "nope"  # type: ignore[misc]


def test_actions_is_a_tuple():
    turn = parse("[HP:+1]")
    assert isinstance(turn.actions, tuple)


def test_parse_accepts_empty_string():
    turn = parse("")
    assert turn == ParsedTurn(narration="", actions=())
