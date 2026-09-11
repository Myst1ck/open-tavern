"""Tests for the pure dice engine."""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError

import pytest

from open_tavern.dice import (
    DIE_SIZES,
    CheckResult,
    advantage,
    check,
    disadvantage,
    roll,
    roll_expression,
)

# --- roll() -------------------------------------------------------------


def test_roll_bounds_for_every_die_size():
    for die in DIE_SIZES:
        rng = random.Random(2026)
        results = [roll(die, rng=rng) for _ in range(2000)]
        assert all(1 <= value <= die for value in results)
        assert min(results) == 1
        assert max(results) == die


def test_roll_rejects_unsupported_die_sizes():
    for die in (0, 3, 7, 13, -6):
        with pytest.raises(ValueError):
            roll(die)


# --- roll_expression() --------------------------------------------------


def test_roll_expression_standard_variants():
    rng = random.Random(42)
    assert 5 <= roll_expression("2d6+3", rng=rng) <= 15
    assert 1 <= roll_expression("d20", rng=rng) <= 20
    assert -1 <= roll_expression("1d8-2", rng=rng) <= 6
    assert 2 <= roll_expression("2d6", rng=rng) <= 12


def test_roll_expression_bare_number():
    assert roll_expression("5") == 5
    assert roll_expression("-3") == -3
    assert roll_expression(" 7 ") == 7


def test_roll_expression_bounds_are_exact():
    rng = random.Random(7)
    results = [roll_expression("2d6+3", rng=rng) for _ in range(1000)]
    assert min(results) == 5
    assert max(results) == 15


def test_roll_expression_invalid_raises():
    for bad in ("abc", "d", "2d", "2x6", "", "2d6+", "d7", "0d6"):
        with pytest.raises(ValueError):
            roll_expression(bad)


# --- advantage / disadvantage ------------------------------------------


def test_advantage_disadvantage_keep_correct_extreme():
    seed = 99
    rng = random.Random(seed)
    first = rng.randint(1, 20)
    second = rng.randint(1, 20)

    assert advantage(rng=random.Random(seed)) == max(first, second)
    assert disadvantage(rng=random.Random(seed)) == min(first, second)


def test_advantage_at_least_disadvantage_same_seed():
    seed = 1234
    assert advantage(rng=random.Random(seed)) >= disadvantage(rng=random.Random(seed))


def test_advantage_disadvantage_in_bounds():
    rng = random.Random(5)
    for _ in range(100):
        assert 1 <= advantage(rng=rng) <= 20
        assert 1 <= disadvantage(rng=rng) <= 20


# --- check() ------------------------------------------------------------


def test_check_success_and_fail():
    rng = random.Random(10)
    d20 = rng.randint(1, 20)
    result = check(3, 15, rng=random.Random(10))
    assert result.d20_value == d20
    assert result.total == d20 + 3
    assert result.success == (result.total >= 15)


def test_check_exact_total():
    seed = 77
    d20 = random.Random(seed).randint(1, 20)
    result = check(5, 20, rng=random.Random(seed))
    assert result.d20_value == d20
    assert result.total == d20 + 5
    assert result.modifier == 5
    assert result.dc == 20


def test_check_crit_success_on_natural_20():
    seed = 5  # first d20 roll is a natural 20
    result = check(0, 30, rng=random.Random(seed))
    assert result.d20_value == 20
    assert result.crit_success is True
    assert result.crit_fail is False


def test_check_crit_fail_on_natural_1():
    seed = 31  # first d20 roll is a natural 1
    result = check(10, 5, rng=random.Random(seed))
    assert result.d20_value == 1
    assert result.crit_fail is True
    assert result.crit_success is False


def test_check_result_is_frozen():
    result = check(0, 10, rng=random.Random(0))
    assert isinstance(result, CheckResult)
    with pytest.raises(FrozenInstanceError):
        result.total = 99  # type: ignore[misc]


# --- determinism --------------------------------------------------------


def test_seeded_rng_is_deterministic():
    def sample() -> list[int]:
        rng = random.Random(31337)
        return [
            roll(20, rng=rng),
            roll(6, rng=rng),
            roll_expression("2d6+3", rng=rng),
            advantage(rng=rng),
            disadvantage(rng=rng),
            check(2, 10, rng=rng).total,
        ]

    assert sample() == sample()


def test_different_seeds_differ():
    assert roll(20, rng=random.Random(1)) != roll(20, rng=random.Random(2))
