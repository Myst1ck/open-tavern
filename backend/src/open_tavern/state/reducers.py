"""Pure reducers for :class:`GameState`.

Every reducer returns a NEW :class:`GameState`; the input state is never
mutated. Reducers are pure functions: same input produces the same output and
no observable side effects occur.
"""

from __future__ import annotations

from dataclasses import replace

from open_tavern.state.models import GameState


def apply_hp(state: GameState, delta: int) -> GameState:
    """Shift ``current_hp`` by ``delta``, clamped to ``[0, max_hp]``."""
    new_hp = min(max(state.current_hp + delta, 0), state.max_hp)
    return replace(state, current_hp=new_hp)


def add_item(state: GameState, name: str) -> GameState:
    """Add ``name`` to inventory (no duplicates)."""
    if name in state.inventory:
        return state
    return replace(state, inventory=state.inventory + (name,))


def remove_item(state: GameState, name: str) -> GameState:
    """Remove ``name`` from inventory (no-op if absent)."""
    if name not in state.inventory:
        return state
    return replace(
        state,
        inventory=tuple(item for item in state.inventory if item != name),
    )


def add_condition(state: GameState, name: str) -> GameState:
    """Add ``name`` to conditions (idempotent)."""
    return replace(state, conditions=state.conditions | {name})


def remove_condition(state: GameState, name: str) -> GameState:
    """Remove ``name`` from conditions (idempotent)."""
    return replace(state, conditions=state.conditions - {name})


def set_scene(state: GameState, scene: str) -> GameState:
    """Set the active ``scene``."""
    return replace(state, scene=scene)
