"""Request guards shared by the router modules.

Rate limiters plus the small policy checks that reject a request before it
touches storage. Route modules read the limiter objects through attribute access
on this module (``guards.item_limiter``) so tests can swap a limiter in place
without rebinding a name that was resolved when the handler module was imported.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from open_tavern.api.ratelimit import RateLimiter
from open_tavern.character import CharacterSheet
from open_tavern.storage import Storage

#: Per-client rate limits for the paid-LLM endpoints (see :mod:`ratelimit`).
action_limiter = RateLimiter(max_requests=10, window_seconds=60.0)
character_limiter = RateLimiter(max_requests=5, window_seconds=60.0)
#: Limits for unauthenticated lifecycle endpoints (resource exhaustion guard).
create_limiter = RateLimiter(max_requests=30, window_seconds=60.0)
#: Limits for the stateless world-generation endpoint (paid LLM call).
world_limiter = RateLimiter(max_requests=30, window_seconds=60.0)
#: Limits for session mutations (delete/rename/style) — cheap but unbounded writes.
delete_limiter = RateLimiter(max_requests=10, window_seconds=60.0)
#: Limits for item CRUD operations.
item_limiter = RateLimiter(max_requests=30, window_seconds=60.0)
#: Shared limit for cheap read endpoints (list/get) — scraping guard.
read_limiter = RateLimiter(max_requests=120, window_seconds=60.0)


def enforce_rate_limit(request: Request, limiter: RateLimiter, scope: str) -> None:
    """Reject (429) when the caller has exceeded ``limiter`` for ``scope``.

    The rate-limit key is the client host by default. ``X-Forwarded-For`` is
    only trusted when ``OPEN_TAVERN_TRUST_PROXY=1`` — the header is trivially
    spoofable, so it must never be honored unless the deployment sits behind a
    proxy that overwrites it. When trusted, the leftmost (client) address is
    used.
    """
    host = request.client.host if request.client is not None else "unknown"
    if os.environ.get("OPEN_TAVERN_TRUST_PROXY", "").strip() == "1":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            host = forwarded.split(",")[0].strip()
    if not limiter.allow(f"{scope}:{host}"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def ensure_session(storage: Storage, session_id: str) -> None:
    """Raise 404 if ``session_id`` is not a known session.

    Uses the cheap ``session_exists`` probe instead of ``load_session`` (which
    loads the full character JSON and transcript just to be discarded).
    """
    if not storage.session_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")


def require_character_id(storage: Storage, session_id: str, character_id: str) -> None:
    """Raise 404 unless ``character_id`` names the session's stored character.

    Each session owns exactly one character row and the API contract uses the
    session id as the character reference (see the frontend client), so any
    other ``character_id`` points at nothing real.
    """
    if character_id != session_id or not storage.character_exists(session_id):
        raise HTTPException(status_code=404, detail="character not found")


def require_character(storage: Storage, session_id: str) -> CharacterSheet:
    """Return the session's character or raise 409 if none was generated yet."""
    character = storage.load_character(session_id)
    if character is None:
        raise HTTPException(
            status_code=409,
            detail="character has not been generated for this session",
        )
    return character
