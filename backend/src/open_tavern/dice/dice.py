"""Pure dice engine.

All dice math lives here. Functions are pure: they take an optional
``random.Random`` instance for seeding and never perform IO or mutate state.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

#: Valid die sizes for a standard RPG polyhedral set.
DIE_SIZES: frozenset[int] = frozenset({4, 6, 8, 10, 12, 20, 100})

_D20: int = 20

#: Maximum number of dice a single expression may roll. Guards against
#: unbounded ``[DAMAGE:<huge>d20]`` CPU denial-of-service from untrusted GM output.
MAX_DICE_COUNT: int = 100

#: Matches ``XdY``, ``dY``, and ``XdY±Z`` / ``dY±Z`` (case-insensitive).
_DICE_EXPR_RE: re.Pattern[str] = re.compile(
    r"^(?P<count>\d*)d(?P<die>\d+)(?P<mod>[+-]\d+)?$"
)

#: Matches a bare integer constant, optionally signed.
_INT_RE: re.Pattern[str] = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class CheckResult:
    """Immutable outcome of a d20 skill check against a difficulty class."""

    d20_value: int
    modifier: int
    total: int
    dc: int
    success: bool
    crit_success: bool
    crit_fail: bool


def _resolve_rng(rng: random.Random | None) -> random.Random:
    """Return the provided RNG or a fresh, unseeded one."""
    return rng if rng is not None else random.Random()


def roll(die: int, rng: random.Random | None = None) -> int:
    """Roll a single die, returning an int in ``[1, die]``.

    Raises:
        ValueError: If ``die`` is not a supported polyhedral size.
    """
    if die not in DIE_SIZES:
        valid = ", ".join(str(size) for size in sorted(DIE_SIZES))
        raise ValueError(f"Unsupported die size {die!r}; expected one of: {valid}")
    return _resolve_rng(rng).randint(1, die)


def _parse_expression(expression: str) -> tuple[int, int, int]:
    """Parse a dice expression into ``(count, die, modifier)``.

    A bare integer yields ``(0, 0, value)`` as a constant. Raises
    ``ValueError`` for anything that is not a valid expression.
    """
    expr = expression.strip().lower().replace(" ", "")
    if not expr:
        raise ValueError("Empty dice expression")

    if _INT_RE.fullmatch(expr):
        return 0, 0, int(expr)

    match = _DICE_EXPR_RE.fullmatch(expr)
    if match is None:
        raise ValueError(f"Invalid dice expression: {expression!r}")

    count = int(match.group("count") or "1")
    die = int(match.group("die"))
    modifier = int(match.group("mod") or "0")

    if count < 1 or count > MAX_DICE_COUNT:
        raise ValueError(
            f"Dice count {count} out of range 1..{MAX_DICE_COUNT} "
            f"in expression: {expression!r}"
        )
    if die not in DIE_SIZES:
        valid = ", ".join(str(size) for size in sorted(DIE_SIZES))
        raise ValueError(
            f"Unsupported die size {die!r} in {expression!r}; expected one of: {valid}"
        )

    return count, die, modifier


def roll_expression(expression: str, rng: random.Random | None = None) -> int:
    """Roll a ``XdY±Z`` expression (or bare number) and return the total.

    Examples: ``"2d6+3"``, ``"d20"``, ``"1d8-2"``, ``"5"``.
    """
    count, die, modifier = _parse_expression(expression)
    if count == 0:
        return modifier

    rng = _resolve_rng(rng)
    total = sum(rng.randint(1, die) for _ in range(count))
    return total + modifier


def _roll_two_d20(rng: random.Random) -> tuple[int, int]:
    """Roll two d20s, returning them in roll order."""
    return rng.randint(1, _D20), rng.randint(1, _D20)


def advantage(rng: random.Random | None = None) -> int:
    """Roll two d20s and keep the higher result."""
    first, second = _roll_two_d20(_resolve_rng(rng))
    return max(first, second)


def disadvantage(rng: random.Random | None = None) -> int:
    """Roll two d20s and keep the lower result."""
    first, second = _roll_two_d20(_resolve_rng(rng))
    return min(first, second)


def check(modifier: int, dc: int, rng: random.Random | None = None) -> CheckResult:
    """Resolve a d20 skill check against a difficulty class.

    ``success`` is ``total >= dc``. ``crit_success`` / ``crit_fail`` report
    natural 20 / natural 1 regardless of the modifier.
    """
    rng = _resolve_rng(rng)
    d20 = rng.randint(1, _D20)
    total = d20 + modifier
    return CheckResult(
        d20_value=d20,
        modifier=modifier,
        total=total,
        dc=dc,
        success=total >= dc,
        crit_success=d20 == _D20,
        crit_fail=d20 == 1,
    )
