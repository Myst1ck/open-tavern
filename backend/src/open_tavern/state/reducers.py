"""Pure reducers for :class:`GameState`.

Every reducer returns a NEW :class:`GameState`; the input state is never
mutated. Reducers are pure functions: same input produces the same output and
no observable side effects occur.
"""

from __future__ import annotations

from dataclasses import replace

from open_tavern.character.items import Item
from open_tavern.state.models import GameState


def apply_hp(state: GameState, delta: int) -> GameState:
    """Shift ``current_hp`` by ``delta``, clamped to ``[0, max_hp]``."""
    new_hp = min(max(state.current_hp + delta, 0), state.max_hp)
    return replace(state, current_hp=new_hp)


def add_item(state: GameState, item: Item) -> GameState:
    """Add ``item`` to ``CharacterSheet.inventory`` (no duplicate ids)."""
    if any(existing.id == item.id for existing in state.character.inventory):
        return state
    new_inv = state.character.inventory + (item,)
    return replace(state, character=replace(state.character, inventory=new_inv))


def remove_item(state: GameState, item_id: str) -> GameState:
    """Remove item by ``item_id`` from ``CharacterSheet.inventory`` (no-op if absent)."""
    new_inv = tuple(i for i in state.character.inventory if i.id != item_id)
    if len(new_inv) == len(state.character.inventory):
        return state
    return replace(state, character=replace(state.character, inventory=new_inv))


def equip_item(state: GameState, item_id: str) -> GameState:
    """Set ``equipped=True`` on item identified by ``item_id``."""
    return _set_equipped(state, item_id, True)


def unequip_item(state: GameState, item_id: str) -> GameState:
    """Set ``equipped=False`` on item identified by ``item_id``."""
    return _set_equipped(state, item_id, False)


def _set_equipped(state: GameState, item_id: str, equipped: bool) -> GameState:
    """Replace item matching ``item_id`` with updated ``equipped`` flag."""
    new_inv = tuple(
        replace(item, equipped=equipped) if item.id == item_id else item
        for item in state.character.inventory
    )
    if new_inv == state.character.inventory:
        return state
    return replace(state, character=replace(state.character, inventory=new_inv))


def add_condition(state: GameState, name: str) -> GameState:
    """Add ``name`` to conditions (idempotent)."""
    return replace(state, conditions=state.conditions | {name})


def remove_condition(state: GameState, name: str) -> GameState:
    """Remove ``name`` from conditions (idempotent)."""
    return replace(state, conditions=state.conditions - {name})


def set_scene(state: GameState, scene: str) -> GameState:
    """Set the active ``scene``."""
    return replace(state, scene=scene)
