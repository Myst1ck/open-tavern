"""Immutable game state models.

:class:`GameState` is a frozen snapshot of a single moment in play. All
transitions are produced by pure reducers in
:mod:`open_tavern.state.reducers`, which return new instances and never mutate
the original.
"""

from __future__ import annotations

from dataclasses import dataclass

from open_tavern.character.models import CharacterSheet


@dataclass(frozen=True)
class GameState:
    """Frozen snapshot of game state at one point in play.

    Uses only hashable, immutable containers (``tuple``, ``frozenset``) so the
    whole state is hashable and safe to compare or key by.
    """

    current_hp: int
    max_hp: int
    inventory: tuple[str, ...]
    conditions: frozenset[str]
    scene: str
    character: CharacterSheet


def new_state(character: CharacterSheet) -> GameState:
    """Build a fresh :class:`GameState` for ``character``.

    Starts at full health, with empty inventory and conditions and no active
    scene.
    """
    return GameState(
        current_hp=character.max_hp,
        max_hp=character.max_hp,
        inventory=(),
        conditions=frozenset(),
        scene="",
        character=character,
    )


def state_to_persistable(state: GameState) -> dict:
    """Serialize ``state`` to a plain, JSON-friendly ``dict``.

    The character is excluded — it is persisted separately via
    ``save_character``. Inventory is converted to a list (from tuple) and
    conditions to a sorted list (from frozenset) so the result is
    deterministic and JSON-serializable.
    """
    return {
        "current_hp": state.current_hp,
        "max_hp": state.max_hp,
        "inventory": list(state.inventory),
        "conditions": sorted(state.conditions),
        "scene": state.scene,
    }


def state_from_persistable(character: CharacterSheet, data: dict) -> GameState:
    """Rebuild a :class:`GameState` from ``character`` and persisted ``data``.

    ``character`` is the single source of truth for derived values (``max_hp``)
    — it is expected to already be normalized upstream (mirroring how
    ``db.load_character`` normalizes from JSON). Stored numbers are never
    trusted: ``current_hp`` is coerced to an int and clamped into
    ``[0, max_hp]``, inventory/conditions are coerced to collections of
    strings, and ``scene`` to a string. Missing or malformed fields fall back
    to :func:`new_state` defaults. This helper is pure: no I/O, no storage.
    """
    if not isinstance(data, dict):
        return new_state(character)

    default = new_state(character)
    max_hp = default.max_hp

    current_hp = default.current_hp
    raw_hp = data.get("current_hp")
    if isinstance(raw_hp, int) and not isinstance(raw_hp, bool):
        current_hp = min(max(raw_hp, 0), max_hp)

    inventory = _coerce_str_tuple(data.get("inventory"))
    conditions = frozenset(_coerce_str_tuple(data.get("conditions")))

    scene = data.get("scene")
    if not isinstance(scene, str):
        scene = default.scene

    return GameState(
        current_hp=current_hp,
        max_hp=max_hp,
        inventory=inventory,
        conditions=conditions,
        scene=scene,
        character=character,
    )


def _coerce_str_tuple(value: object) -> tuple[str, ...]:
    """Return the string items of ``value`` if it is a list/tuple, else ``()``.

    Non-string items are dropped rather than stringified, so malformed or
    hostile payloads cannot inject junk entries into inventory or conditions.
    """
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))
