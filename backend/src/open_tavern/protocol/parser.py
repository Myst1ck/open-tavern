"""GM tag protocol parser.

Parses untrusted GM narration into a :class:`ParsedTurn`: the prose with every
recognized instruction tag stripped, plus an ordered tuple of typed actions.

Tags are embedded in narration as ``[TAG:payload]``:

* ``[CHECK:strength DC15]``  -> :class:`CheckAction` (ability check)
* ``[CHECK:athletics DC12]`` -> :class:`CheckAction` (skill check)
* ``[DAMAGE:2d6+3]``         -> :class:`DamageAction`
* ``[ITEM:+sword]``          -> :class:`ItemAction`
* ``[HP:+5]``                -> :class:`HpAction`
* ``[CONDITION:+poisoned]``  -> :class:`ConditionAction`

GM output is untrusted: parsing is defensive, every recognized-but-malformed
tag is ignored silently, and unrecognized ``[x:y]`` brackets are left in the
narration untouched. Nothing here ever raises.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from open_tavern.character.models import resolve_ability, resolve_skill
from open_tavern.dice.dice import MAX_DICE_COUNT

#: Tag type names the parser recognizes (matched case-insensitively).
_KNOWN_TAGS: frozenset[str] = frozenset({"CHECK", "DAMAGE", "ITEM", "HP", "CONDITION"})

#: Matches any ``[TAG:body]`` bracket. ``body`` cannot contain a closing ``]``.
_TAG_RE: re.Pattern[str] = re.compile(r"\[(?P<tag>[A-Za-z]+):(?P<body>[^\]]*)\]")

#: Matches a CHECK payload: a name followed by ``DC`` and an integer.
_CHECK_RE: re.Pattern[str] = re.compile(
    r"^(?P<name>.+?)\s+DC\s*(?P<dc>\d+)\s*$", re.IGNORECASE
)

#: Matches a signed integer delta (``+5`` / ``-3``).
_SIGNED_INT_RE: re.Pattern[str] = re.compile(r"^[+-]\d+$")

#: Matches a bare integer, optionally signed.
_BARE_INT_RE: re.Pattern[str] = re.compile(r"^[+-]?\d+$")

#: Matches a dice expression (``2d6+3``, ``d20``, ``2d6``) — case-insensitive.
_DICE_RE: re.Pattern[str] = re.compile(r"^\d*d\d+(?:[+-]\d+)?$", re.IGNORECASE)

#: Matches the leading dice count of an ``XdY`` expression (empty => 1 die).
_DICE_COUNT_RE: re.Pattern[str] = re.compile(r"^(\d*)d", re.IGNORECASE)


@dataclass(frozen=True)
class CheckAction:
    """A CHECK tag: an ability or skill roll against a difficulty class.

    ``name`` holds the raw name exactly as the GM wrote it. ``ability`` is the
    canonical ability abbreviation (``"STR"``) when ``name`` resolves to an
    ability, else ``None``. ``skill`` is the canonical skill name
    (``"Athletics"``) when ``name`` resolves to a skill, else ``None``. An
    unknown name leaves both ``None`` and is carried only by ``name``.
    """

    kind: Literal["check"]
    name: str
    ability: str | None
    skill: str | None
    dc: int


@dataclass(frozen=True)
class DamageAction:
    """A DAMAGE tag: a dice expression to roll for damage."""

    kind: Literal["damage"]
    dice: str


@dataclass(frozen=True)
class ItemAction:
    """An ITEM tag: add (``+``) or remove (``-``) an item from inventory."""

    kind: Literal["item"]
    sign: Literal["+", "-"]
    name: str


@dataclass(frozen=True)
class HpAction:
    """An HP tag: a signed change to hit points."""

    kind: Literal["hp"]
    delta: int


@dataclass(frozen=True)
class ConditionAction:
    """A CONDITION tag: apply (``+``) or clear (``-``) a condition."""

    kind: Literal["condition"]
    sign: Literal["+", "-"]
    name: str


#: Discriminated union of every action type. Consumers match on ``kind``.
Action = CheckAction | DamageAction | ItemAction | HpAction | ConditionAction


@dataclass(frozen=True)
class ParsedTurn:
    """A parsed GM turn: clean narration plus the ordered actions embedded in it."""

    narration: str
    actions: tuple[Action, ...]


def parse(text: str) -> ParsedTurn:
    """Parse GM narration into a :class:`ParsedTurn`.

    Recognized tags are removed from the narration and turned into actions in
    source order. Recognized-but-malformed tags are removed but yield no
    action. Unrecognized ``[x:y]`` brackets are left as narration text.
    """
    actions: list[Action] = []
    chunks: list[str] = []
    cursor = 0

    for match in _TAG_RE.finditer(text):
        if match.group("tag").upper() not in _KNOWN_TAGS:
            continue
        chunks.append(text[cursor : match.start()])
        cursor = match.end()
        action = _parse_tag(match.group("tag"), match.group("body"))
        if action is not None:
            actions.append(action)

    chunks.append(text[cursor:])
    narration = _normalize_whitespace("".join(chunks))
    return ParsedTurn(narration=narration, actions=tuple(actions))


def _parse_tag(tag: str, body: str) -> Action | None:
    """Parse a single recognized tag into an action, or ``None`` if malformed."""
    key = tag.upper()
    if key == "CHECK":
        return _parse_check(body)
    if key == "DAMAGE":
        return _parse_damage(body)
    if key == "HP":
        return _parse_hp(body)
    if key == "ITEM":
        return _parse_item(body)
    if key == "CONDITION":
        return _parse_condition(body)
    return None


def _parse_check(body: str) -> CheckAction | None:
    """Parse ``name DC<int>`` into a :class:`CheckAction`."""
    match = _CHECK_RE.fullmatch(body.strip())
    if match is None:
        return None
    name = match.group("name").strip()
    ability = resolve_ability(name)
    skill = None if ability is not None else resolve_skill(name)
    return CheckAction(
        kind="check",
        name=name,
        ability=ability,
        skill=skill,
        dc=int(match.group("dc")),
    )


def _parse_damage(body: str) -> DamageAction | None:
    """Parse a dice expression, normalizing whitespace and case."""
    dice = "".join(body.split()).lower()
    if not _is_dice_expression(dice):
        return None
    count_match = _DICE_COUNT_RE.match(dice)
    if count_match is not None and count_match.group(1) != "":
        if int(count_match.group(1)) > MAX_DICE_COUNT:
            return None
    return DamageAction(kind="damage", dice=dice)


def _parse_hp(body: str) -> HpAction | None:
    """Parse a signed integer hit-point delta."""
    value = body.strip()
    if _SIGNED_INT_RE.fullmatch(value) is None:
        return None
    return HpAction(kind="hp", delta=int(value))


def _parse_item(body: str) -> ItemAction | None:
    """Parse a signed item name."""
    parsed = _split_sign_name(body)
    if parsed is None:
        return None
    sign, name = parsed
    return ItemAction(kind="item", sign=sign, name=name)


def _parse_condition(body: str) -> ConditionAction | None:
    """Parse a signed condition name."""
    parsed = _split_sign_name(body)
    if parsed is None:
        return None
    sign, name = parsed
    return ConditionAction(kind="condition", sign=sign, name=name)


def _split_sign_name(body: str) -> tuple[Literal["+", "-"], str] | None:
    """Split a payload into a ``+``/``-`` sign and a non-empty name."""
    text = body.strip()
    if not text or text[0] not in ("+", "-"):
        return None
    name = text[1:].strip()
    if not name:
        return None
    sign = cast(Literal["+", "-"], text[0])
    return sign, name


def _is_dice_expression(expr: str) -> bool:
    """Return whether ``expr`` is a bare integer or a dice expression."""
    if not expr:
        return False
    if _BARE_INT_RE.fullmatch(expr):
        return True
    return _DICE_RE.fullmatch(expr) is not None


def _normalize_whitespace(text: str) -> str:
    """Collapse all runs of whitespace to single spaces and strip the ends."""
    return " ".join(text.split())
