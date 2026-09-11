"""Shared pytest fixtures for open-tavern backend tests."""

import pytest

from open_tavern.api import routes


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset global rate limiters before each test so buckets never leak."""
    for limiter in (
        routes._action_limiter,
        routes._character_limiter,
        routes._create_limiter,
        routes._brainstorm_limiter,
        routes._delete_limiter,
        routes._item_limiter,
    ):
        limiter.reset()
    yield
