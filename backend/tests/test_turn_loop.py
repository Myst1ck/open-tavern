"""Tests for the two-phase GM turn loop."""

from __future__ import annotations

import random

from open_tavern.character import normalize
from open_tavern.dice import roll_expression
from open_tavern.state import new_state
from open_tavern.story import RollOutcome, TurnResult, turn


class FakeClient:
    """Queue-backed fake chat client — never touches the network."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, temperature=0.7, json_mode=False):
        self.calls.append({"messages": messages})
        return self.responses.pop(0)


def _character():
    return normalize(
        {
            "name": "Kael",
            "race": "human",
            "character_class": "fighter",
            "level": 1,
            "abilities": {
                "STR": 16,
                "DEX": 12,
                "CON": 14,
                "INT": 10,
                "WIS": 10,
                "CHA": 8,
            },
        }
    )


# --- no check: single call ----------------------------------------------


def test_turn_no_check_is_single_call_and_state_unchanged():
    state = new_state(_character())
    client = FakeClient(["You enter the tavern. The barkeep nods."])
    result = turn("I walk in", state, [], client, rng=random.Random(0))

    assert isinstance(result, TurnResult)
    assert result.llm_calls == 1
    assert len(client.calls) == 1
    assert result.narration == "You enter the tavern. The barkeep nods."
    assert result.rolls == ()
    assert result.state == state


def test_turn_no_check_applies_state_tags_without_second_call():
    state = new_state(_character())
    client = FakeClient(["A shard of ice pierces you. [HP:-3] [ITEM:+potion]"])
    result = turn("I step forward", state, [], client, rng=random.Random(0))

    assert result.llm_calls == 1
    assert result.state.current_hp == state.current_hp - 3
    assert any(item.name == "potion" for item in result.state.character.inventory)


# --- check: two calls, engine rolls -------------------------------------


def test_turn_check_two_calls_rolls_dice_and_updates_state():
    character = _character()
    state = new_state(character)
    first = "You swing your sword. [CHECK:strength DC15] [DAMAGE:2d6]"
    second = "Your blow lands true; the orc staggers back."
    client = FakeClient([first, second])
    seed = 42

    result = turn("I attack the orc", state, [], client, rng=random.Random(seed))

    assert result.llm_calls == 2
    assert len(client.calls) == 2
    assert result.narration == second

    # one check roll recorded, resolved deterministically
    assert len(result.rolls) == 1
    roll = result.rolls[0]
    assert isinstance(roll, RollOutcome)
    assert roll.name == "strength"
    assert roll.dc == 15
    assert roll.modifier == 3  # STR 16 -> +3

    # verify dice math comes from the dice engine, seeded and reproducible:
    # the check consumes one d20 first, then the damage rolls 2d6.
    replica = random.Random(seed)
    d20 = replica.randint(1, 20)
    damage = roll_expression("2d6", replica)
    assert roll.d20 == d20
    assert roll.total == d20 + 3
    assert result.state.current_hp == state.max_hp - damage


def test_turn_check_skill_uses_proficiency():
    character = normalize(
        {
            "race": "human",
            "character_class": "fighter",
            "level": 1,
            "abilities": {
                "STR": 16,
                "DEX": 12,
                "CON": 14,
                "INT": 10,
                "WIS": 10,
                "CHA": 8,
            },
            "skills": {"Athletics": True},
        }
    )
    state = new_state(character)
    client = FakeClient(
        ["You shove the door. [CHECK:athletics DC12]", "The door bursts open."]
    )
    result = turn("I shove the door", state, [], client, rng=random.Random(7))
    assert result.llm_calls == 2
    assert result.rolls[0].modifier == 5  # STR +3 + proficiency +2


def test_turn_check_falls_back_to_first_narration_when_second_empty():
    state = new_state(_character())
    client = FakeClient(
        ["You strain against the gate. [CHECK:strength DC15]", "[HP:-1]"]
    )
    result = turn("I push the gate", state, [], client, rng=random.Random(1))
    assert result.llm_calls == 2
    # second response narration is empty -> fall back to first narration
    assert result.narration == "You strain against the gate."
    # second response state tag still applied
    assert result.state.current_hp == state.max_hp - 1


def test_turn_second_response_does_not_retrigger_checks():
    state = new_state(_character())
    first = "You lunge at the beast. [CHECK:strength DC10]"
    second = "It dodges. [CHECK:dexterity DC10] [HP:-2]"
    client = FakeClient([first, second])
    result = turn("I lunge", state, [], client, rng=random.Random(3))

    assert result.llm_calls == 2
    # only the first check is rolled; the second is a state-only response
    assert len(result.rolls) == 1
    assert result.rolls[0].name == "strength"
    assert result.state.current_hp == state.max_hp - 2


def test_turn_appends_player_action_and_final_narration_to_messages():
    history = [{"role": "user", "content": "I open the door."}]
    state = new_state(_character())
    client = FakeClient(["The door creaks open."])
    turn("I look around", state, history, client, rng=random.Random(0))

    sent = client.calls[0]["messages"]
    roles = [message["role"] for message in sent]
    assert roles[0] == "system"
    assert history[0] in sent
    # player action is wrapped as untrusted data
    assert any("<player_action>" in message["content"] for message in sent)
