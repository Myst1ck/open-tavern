"""Two-phase GM turn loop.

Phase 1: the player's action is sent to the LLM, whose narration may embed
instruction tags (including ``[CHECK:...]``). The engine parses those tags and
applies state changes, rolling dice itself.

Phase 2: if the LLM requested any check, the engine resolves the roll and feeds
the outcome back for a second narration call. The engine — never the LLM — owns
all dice math.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

from open_tavern.character.items import BaseType, Item
from open_tavern.character.models import CharacterSheet
from open_tavern.dice import check as dice_check
from open_tavern.dice import roll_expression
from open_tavern.protocol import (
    CheckAction,
    ConditionAction,
    DamageAction,
    HpAction,
    ItemAction,
    parse,
)
from open_tavern.state import (
    GameState,
    add_condition,
    add_item,
    apply_hp,
    remove_condition,
    remove_item,
)
from open_tavern.story.prompts import (
    gm_system_prompt,
    roll_result_prompt,
    user_action_prompt,
)

DEFAULT_WORLD_THEME: str = "a classic D&D fantasy world"

#: Cap on how many prior transcript messages are resent to the LLM each turn.
#: Bounds per-turn token cost as sessions grow long.
_MAX_HISTORY_MESSAGES: int = 20


def _recent_history(history: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    """Return at most the last ``limit`` messages, preserving order."""
    if len(history) <= limit:
        return history
    return history[-limit:]


@dataclass(frozen=True)
class RollOutcome:
    """Result of a single ability/skill check resolved by the dice engine."""

    name: str
    dc: int
    modifier: int
    d20: int
    total: int
    success: bool
    crit_success: bool
    crit_fail: bool


@dataclass(frozen=True)
class TurnResult:
    """Outcome of one processed player turn."""

    narration: str
    state: GameState
    rolls: tuple[RollOutcome, ...]
    llm_calls: int


def turn(
    action: str,
    state: GameState,
    history: list[dict[str, str]],
    client,
    rng: random.Random | None = None,
    premise: str | None = None,
) -> TurnResult:
    """Process one player ``action`` against ``state`` and return a result.

    ``history`` is a read-only list of ``{"role", "content"}`` messages. The
    caller appends the player action and final narration after this returns.
    """
    system = _build_system_prompt(state, premise=premise)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        *_recent_history(history, _MAX_HISTORY_MESSAGES),
        {"role": "user", "content": user_action_prompt(action)},
    ]

    first = client.chat(messages)
    first_parsed = parse(first)
    state, rolls, had_check = _apply_actions(
        state, first_parsed.actions, state.character, rng, allow_checks=True
    )

    if not had_check:
        return TurnResult(
            narration=first_parsed.narration,
            state=state,
            rolls=tuple(rolls),
            llm_calls=1,
        )

    follow_up: list[dict[str, str]] = [
        *messages,
        {"role": "assistant", "content": first},
        {"role": "user", "content": _roll_feedback(rolls)},
    ]
    second = client.chat(follow_up)
    second_parsed = parse(second)
    state, _, _ = _apply_actions(
        state, second_parsed.actions, state.character, rng, allow_checks=False
    )
    narration = second_parsed.narration or first_parsed.narration
    return TurnResult(
        narration=narration,
        state=state,
        rolls=tuple(rolls),
        llm_calls=2,
    )


def _build_system_prompt(state: GameState, premise: str | None = None) -> str:
    """Build the GM system prompt, reflecting the live hit-point total."""
    live_character = replace(state.character, hp=state.current_hp)
    return gm_system_prompt(live_character, DEFAULT_WORLD_THEME, premise=premise)


def _apply_actions(
    state: GameState,
    actions: tuple,
    character: CharacterSheet,
    rng: random.Random | None,
    allow_checks: bool,
) -> tuple[GameState, list[RollOutcome], bool]:
    """Apply each parsed action in order, collecting check outcomes."""
    rolls: list[RollOutcome] = []
    had_check = False
    for action in actions:
        if isinstance(action, CheckAction):
            had_check = True
            if allow_checks:
                outcome = _resolve_check(action, character, rng)
                if outcome is not None:
                    rolls.append(outcome)
        elif isinstance(action, DamageAction):
            damage = roll_expression(action.dice, rng=rng)
            state = apply_hp(state, -damage)
        elif isinstance(action, HpAction):
            state = apply_hp(state, action.delta)
        elif isinstance(action, ItemAction):
            state = _apply_item(state, action)
        elif isinstance(action, ConditionAction):
            state = _apply_condition(state, action)
    return state, rolls, had_check


def _resolve_check(
    action: CheckAction, character: CharacterSheet, rng: random.Random | None
) -> RollOutcome | None:
    """Resolve a check via the dice engine, or ``None`` if the name is unknown."""
    if action.skill is not None:
        modifier = character.skill_modifier(action.skill)
    elif action.ability is not None:
        modifier = character.ability_modifier(action.ability)
    else:
        return None

    result = dice_check(modifier, action.dc, rng=rng)
    return RollOutcome(
        name=action.name,
        dc=action.dc,
        modifier=modifier,
        d20=result.d20_value,
        total=result.total,
        success=result.success,
        crit_success=result.crit_success,
        crit_fail=result.crit_fail,
    )


def _apply_item(state: GameState, action: ItemAction) -> GameState:
    if action.sign == "+":
        item = Item(name=action.name, type=BaseType.loot)
        return add_item(state, item)
    for existing in state.character.inventory:
        if existing.name == action.name:
            return remove_item(state, existing.id)
    return state


def _apply_condition(state: GameState, action: ConditionAction) -> GameState:
    if action.sign == "+":
        return add_condition(state, action.name)
    return remove_condition(state, action.name)


def _roll_feedback(rolls: list[RollOutcome]) -> str:
    """Build the second-phase prompt describing resolved check outcomes."""
    if not rolls:
        return roll_result_prompt("", "no check was resolved")
    check_desc = ", ".join(f"{roll.name} DC {roll.dc}" for roll in rolls)
    summary = "; ".join(_format_roll(roll) for roll in rolls)
    return roll_result_prompt(check_desc, summary)


def _format_roll(outcome: RollOutcome) -> str:
    if outcome.crit_success:
        verdict = "critical success"
    elif outcome.crit_fail:
        verdict = "critical failure"
    elif outcome.success:
        verdict = "success"
    else:
        verdict = "failure"
    return (
        f"{outcome.name} DC {outcome.dc}: "
        f"d20 {outcome.d20} + {outcome.modifier} = {outcome.total} ({verdict})"
    )
