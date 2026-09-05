"""Item models for inventory system.

Frozen dataclasses for items, stats, and base types. JSON-serializable
via to_dict/from_dict round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class BaseType(Enum):
    """Canonical item categories."""

    weapon = "weapon"
    armor = "armor"
    consumable = "consumable"
    quest = "quest"
    loot = "loot"
    key = "key"


@dataclass(frozen=True)
class ItemStats:
    """Hybrid stats: fixed numeric fields + freeform extra dict."""

    damage: int = 0
    armor: int = 0
    value: int = 0
    weight: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "damage": self.damage,
            "armor": self.armor,
            "value": self.value,
            "weight": self.weight,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ItemStats:
        """Deserialize from dict (returns default if ``d`` is empty/None).

        Numeric fields are coerced with ``float()``; non-numeric values fall
        back to the field default. ``damage``/``value``/``weight`` are clamped
        with ``max(0, ...)`` so LLM/client garbage (e.g. string damage) cannot
        produce negative or non-numeric stats that crash the frontend.
        """
        if not d:
            return cls()

        def _coerce(key: str, default: float) -> float:
            try:
                return float(d.get(key, default))
            except (TypeError, ValueError):
                return default

        return cls(
            damage=int(max(0, _coerce("damage", 0))),
            armor=int(_coerce("armor", 0)),
            value=int(max(0, _coerce("value", 0))),
            weight=max(0.0, _coerce("weight", 0.0)),
            extra=d.get("extra", {}),
        )


@dataclass(frozen=True)
class Item:
    """An inventory item. Frozen/hashable. Auto-generates ID when omitted."""

    name: str
    type: BaseType
    id: str = field(default_factory=lambda: uuid4().hex[:8])
    tags: tuple[str, ...] = ()
    stats: ItemStats = field(default_factory=ItemStats)
    description: str = ""
    equipped: bool = False
    quantity: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "tags": list(self.tags),
            "stats": self.stats.to_dict(),
            "description": self.description,
            "equipped": self.equipped,
            "quantity": self.quantity,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Item:
        """Deserialize from dict.

        ``id`` is optional — auto-generated via ``uuid4().hex[:8]`` when missing.
        """
        raw_type = d.get("type", "loot")
        item_type = raw_type if isinstance(raw_type, BaseType) else BaseType(raw_type)

        return cls(
            id=d.get("id", uuid4().hex[:8]),
            name=d["name"],
            type=item_type,
            tags=tuple(d.get("tags", [])),
            stats=ItemStats.from_dict(d.get("stats", {})),
            description=d.get("description", ""),
            equipped=d.get("equipped", False),
            quantity=d.get("quantity", 1),
        )
