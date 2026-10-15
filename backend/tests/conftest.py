"""Shared pytest fixtures for open-tavern backend tests."""

import pytest

from open_tavern.api import guards


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset global rate limiters before each test so buckets never leak."""
    for limiter in (
        guards.action_limiter,
        guards.character_limiter,
        guards.create_limiter,
        guards.world_limiter,
        guards.delete_limiter,
        guards.item_limiter,
        guards.read_limiter,
    ):
        limiter.reset()
    yield
