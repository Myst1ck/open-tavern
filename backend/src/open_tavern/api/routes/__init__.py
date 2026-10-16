"""Router modules for the Open Tavern API.

Each module owns the endpoints for one resource; ``ROUTERS`` collects their
routers in mount order so :mod:`open_tavern.api.main` can include them all.
"""

from __future__ import annotations

from fastapi import APIRouter

from open_tavern.api.routes import character, items, sessions, turn, world

ROUTERS: tuple[APIRouter, ...] = (
    sessions.router,
    character.router,
    world.router,
    turn.router,
    items.router,
)
