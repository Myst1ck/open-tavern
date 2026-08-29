"""Shared pytest fixtures for open-tavern backend tests."""

import pytest

from open_tavern.api import routes


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset global rate limiters before each test so buckets never leak."""
    routes._action_limiter.reset()
    routes._character_limiter.reset()
    yield
