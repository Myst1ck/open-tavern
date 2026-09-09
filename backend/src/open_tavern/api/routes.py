"""FastAPI route handlers for the Open Tavern API.

Endpoints wire the story engine to the storage layer. Both dependencies — the
LLM chat client and the database — are injectable via :func:`get_client` and
:func:`get_storage`, so tests substitute fakes through
``app.dependency_overrides`` without touching the network or disk.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import replace
from functools import lru_cache
from typing import Protocol

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from open_tavern.api.ratelimit import RateLimiter
from open_tavern.api.schemas import (
    ActionRequest,
    ActionResponse,
    BrainstormRequest,
    BrainstormResponse,
    CharacterRequest,
    CharacterResponse,
    ClassRequest,
    ClassResponse,
    CreateItemRequest,
    CreateSessionRequest,
    CreateSessionResponse,
    ItemActionResponse,
    ItemListResponse,
    ItemResponse,
    RefineRequest,
    RefineResponse,
    RenameSessionRequest,
    SessionDetail,
    SessionSummary,
    StateResponse,
    character_to_dict,
    roll_to_dict,
    state_to_dict,
)
from open_tavern.character import CharacterSheet
from open_tavern.character.items import BaseType, Item, ItemStats
from open_tavern.state import GameState, new_state
from open_tavern.storage import Storage
from open_tavern.story import (
    CharacterGenerationError,
    OpenAIClient,
    generate_character,
    generate_class,
    turn,
)
from open_tavern.story.character_gen import _parse_json
from open_tavern.story.client import LLMClientError
from open_tavern.story.prompts import brainstorm_prompt
from open_tavern.story.refine import refine_prose


class ChatClient(Protocol):
    """Structural interface for the LLM chat client used by the story engine."""

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str: ...


@lru_cache
def get_client() -> OpenAIClient:
    """Provide the LLM client, configured from environment variables."""
    return OpenAIClient()


def build_client_from_headers(
    api_key: str | None,
    base_url: str | None,
    model: str | None,
) -> OpenAIClient:
    """Build an LLM client from non-empty header values.

    Each non-empty value overrides the corresponding environment fallback inside
    :class:`OpenAIClient`; empty/absent values are dropped so the constructor's
    env-based defaults apply. Always returns a fresh, network-free client.
    """
    kwargs: dict[str, str] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    if model:
        kwargs["model"] = model
    try:
        return OpenAIClient(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_per_request_client(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_base_url: str | None = Header(default=None, alias="X-Base-URL"),
    x_model: str | None = Header(default=None, alias="X-Model"),
    env_client: ChatClient = Depends(get_client),
) -> ChatClient:
    """Resolve the LLM client from per-request headers, else the env client.

    Non-empty ``X-API-Key``/``X-Base-URL``/``X-Model`` headers override the
    environment-configured :class:`OpenAIClient`; without any of them the shared
    environment client (or its dependency-override test fake) is used unchanged.
    """
    if not (x_api_key or x_base_url or x_model):
        return env_client
    return build_client_from_headers(x_api_key, x_base_url, x_model)


@lru_cache
def get_storage() -> Storage:
    """Provide the storage layer, opening the SQLite database from env."""
    store = Storage(os.environ.get("OPEN_TAVERN_DB", "open_tavern.db"))
    store.init()
    return store


router = APIRouter()

#: In-memory LRU cache of live :class:`GameState` keyed by session id.
#:
#: Storage persists the running state via ``save_state``/``load_state``, so the
#: cache only avoids re-reading it on every request. Capped at
#: ``_STATE_CACHE_MAXLEN`` entries (oldest evicted) so long-running servers
#: cannot grow it unbounded. Guarded by ``_STATE_LOCK`` so concurrent requests
#: cannot race; all access must go through that lock.
_STATE_CACHE_MAXLEN: int = 100
_STATE_CACHE: OrderedDict[str, GameState] = OrderedDict()
_STATE_LOCK = threading.Lock()


def _cache_state(session_id: str, state: GameState) -> None:
    """Store ``state`` for ``session_id``, evicting the oldest entry when full."""
    with _STATE_LOCK:
        _STATE_CACHE[session_id] = state
        _STATE_CACHE.move_to_end(session_id)
        if len(_STATE_CACHE) > _STATE_CACHE_MAXLEN:
            _STATE_CACHE.popitem(last=False)


def _invalidate_state(session_id: str) -> None:
    """Drop ``session_id`` from the state cache if present."""
    with _STATE_LOCK:
        _STATE_CACHE.pop(session_id, None)


#: Per-client rate limits for the paid-LLM endpoints (see :mod:`ratelimit`).
_action_limiter = RateLimiter(max_requests=10, window_seconds=60.0)
_character_limiter = RateLimiter(max_requests=5, window_seconds=60.0)
#: Limits for unauthenticated lifecycle endpoints (resource exhaustion guard).
_create_limiter = RateLimiter(max_requests=30, window_seconds=60.0)
_brainstorm_limiter = RateLimiter(max_requests=30, window_seconds=60.0)
_delete_limiter = RateLimiter(max_requests=10, window_seconds=60.0)
#: Limits for item CRUD operations.
_item_limiter = RateLimiter(max_requests=30, window_seconds=60.0)

#: Per-session locks serialize read-modify-write of a single session's state so
#: concurrent actions cannot lose updates. Keyed by session id.
#: Entries use ``(lock, refcount)`` tuples — the lock is only deleted when no
#: thread is waiting or holding it (refcount == 0), preventing the
#: replacement-race where a new lock is created while a waiter still holds
#: the old one.
_SESSION_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def _session_lock(session_id: str) -> threading.Lock:
    """Return the per-session lock for ``session_id``, incrementing the refcount."""
    with _SESSION_LOCKS_GUARD:
        entry = _SESSION_LOCKS.get(session_id)
        if entry is None:
            lock = threading.Lock()
            _SESSION_LOCKS[session_id] = (lock, 1)
            return lock
        lock, refcount = entry
        _SESSION_LOCKS[session_id] = (lock, refcount + 1)
        return lock


@contextmanager
def _session_lock_ctx(session_id: str):
    """Acquire the per-session lock and decrement the refcount on exit.

    The lock mapping is only removed when the refcount drops to zero, so
    a thread still queued on the lock will not see its lock replaced.
    """
    lock = _session_lock(session_id)
    try:
        with lock:
            yield
    finally:
        with _SESSION_LOCKS_GUARD:
            entry = _SESSION_LOCKS.get(session_id)
            if entry is not None:
                lock_obj, refcount = entry
                if lock_obj is lock:
                    if refcount <= 1:
                        _SESSION_LOCKS.pop(session_id, None)
                    else:
                        _SESSION_LOCKS[session_id] = (lock, refcount - 1)


def _enforce_rate_limit(request: Request, limiter: RateLimiter, scope: str) -> None:
    """Reject (429) when the caller has exceeded ``limiter`` for ``scope``."""
    host = request.client.host if request.client is not None else "unknown"
    if not limiter.allow(f"{scope}:{host}"):
        raise HTTPException(status_code=429, detail="rate limit exceeded")


def _ensure_session(storage: Storage, session_id: str) -> None:
    """Raise 404 if ``session_id`` is not a known session.

    Uses the cheap ``session_exists`` probe instead of ``load_session`` (which
    loads the full character JSON and transcript just to be discarded).
    """
    if not storage.session_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")


def _require_character_id(storage: Storage, session_id: str, character_id: str) -> None:
    """Raise 404 unless ``character_id`` names the session's stored character.

    Each session owns exactly one character row and the API contract uses the
    session id as the character reference (see the frontend client), so any
    other ``character_id`` points at nothing real.
    """
    if character_id != session_id or not storage.character_exists(session_id):
        raise HTTPException(status_code=404, detail="character not found")


def _require_character(storage: Storage, session_id: str) -> CharacterSheet:
    """Return the session's character or raise 409 if none was generated yet."""
    character = storage.load_character(session_id)
    if character is None:
        raise HTTPException(
            status_code=409,
            detail="character has not been generated for this session",
        )
    return character


def _current_state(
    storage: Storage, session_id: str, character: CharacterSheet
) -> GameState:
    """Return the live state for a session.

    Prefer the in-memory cache; on a cache miss load the persisted state from
    storage, falling back to a fresh :func:`new_state` when nothing was saved.
    """
    with _STATE_LOCK:
        cached = _STATE_CACHE.get(session_id)
        if cached is not None:
            _STATE_CACHE.move_to_end(session_id)
    if cached is not None:
        return cached
    persisted = storage.load_state(session_id, character)
    if persisted is not None:
        _cache_state(session_id, persisted)
        return persisted
    return new_state(character)


def _session_summary(storage: Storage, session_id: str) -> SessionSummary:
    """Return the summary row for ``session_id`` or raise 404.

    Uses a targeted single-row query (``Storage.session_summary``) rather than
    scanning the full session list, so renames stay O(1).
    """
    row = storage.session_summary(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    return SessionSummary(**row)


@router.post(
    "/sessions",
    response_model=CreateSessionResponse,
    status_code=201,
)
def create_session(
    body: CreateSessionRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> CreateSessionResponse:
    """Create a new game session and persist it."""
    _enforce_rate_limit(request, _create_limiter, "create")
    session_id = storage.create_session(
        body.world_theme, body.title, premise=body.premise
    )
    return CreateSessionResponse(
        session_id=session_id,
        world_theme=body.world_theme,
        premise=body.premise,
    )


@router.post(
    "/sessions/{session_id}/character",
    response_model=CharacterResponse,
)
def create_character(
    session_id: str,
    body: CharacterRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> CharacterResponse:
    """Generate a validated character sheet, persist it, and seed the story.

    Class overrides from the request take precedence over the LLM-derived
    class. The generated opening scene is saved into game state and the
    opening narration (when non-empty) opens the session transcript as the
    first assistant message.
    """
    _ensure_session(storage, session_id)
    _enforce_rate_limit(request, _character_limiter, "character")
    session_meta = storage.load_session(session_id)
    premise = session_meta.get("premise") if session_meta else None
    try:
        sheet, opening, scene = generate_character(
            body.description or "",
            client,
            name=body.name or "",
            race=body.race or "",
            class_concept=body.class_concept or "",
            backstory=body.backstory or "",
            personality=body.personality or "",
            appearance=body.appearance or "",
            motivation=body.motivation or "",
            class_name=body.class_name or "",
            class_hit_die=body.class_hit_die,
            class_description=body.class_description or "",
            premise=premise,
        )
    except CharacterGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    storage.save_character(session_id, sheet)
    state = new_state(sheet)
    if scene:
        state = replace(state, scene=scene)
    storage.save_state(session_id, state)
    _cache_state(session_id, state)
    if opening:
        storage.append_message(session_id, "assistant", opening)
    return CharacterResponse(character=character_to_dict(sheet), opening=opening)


@router.post(
    "/sessions/{session_id}/character/class",
    response_model=ClassResponse,
)
def create_class_preview(
    session_id: str,
    body: ClassRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> ClassResponse:
    """Generate a class definition preview from a concept; nothing is persisted."""
    _ensure_session(storage, session_id)
    _enforce_rate_limit(request, _character_limiter, "class")
    try:
        definition = generate_class(body.class_concept, client)
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ClassResponse(
        class_definition={
            "name": definition.name,
            "description": definition.description,
            "hit_die": definition.hit_die,
        }
    )


@router.post(
    "/brainstorm",
    response_model=BrainstormResponse,
)
def brainstorm(
    body: BrainstormRequest,
    request: Request,
    client: ChatClient = Depends(get_per_request_client),
) -> BrainstormResponse:
    """Distill a pre-game brainstorm chat into theme + premise (stateless).

    Prepend the brainstorm system prompt to the conversation, ask the LLM for
    a JSON ``{"theme", "premise"}`` object, and parse it. Nothing is persisted;
    any LLM or parse failure surfaces as 502.
    """
    _enforce_rate_limit(request, _brainstorm_limiter, "brainstorm")
    messages = [{"role": "system", "content": brainstorm_prompt()}, *body.messages]
    try:
        data = _parse_json(client.chat(messages, temperature=0.8))
    except (LLMClientError, CharacterGenerationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM response was not valid JSON")
    theme = data.get("theme")
    premise = data.get("premise")
    if not isinstance(theme, str) or not isinstance(premise, str):
        raise HTTPException(
            status_code=502, detail="LLM response missing theme or premise"
        )
    return BrainstormResponse(theme=theme.strip(), premise=premise.strip())


@router.post(
    "/sessions/{session_id}/character/refine",
    response_model=RefineResponse,
)
def refine_character(
    session_id: str,
    body: RefineRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> RefineResponse:
    """Preview-refine the session character's prose fields; nothing is persisted.

    Request prose fields override the stored sheet values for prompt context;
    stored name/race/class/level always anchor the prompt. On ANY LLM failure
    (``refine_prose`` returns ``None``) the original stored prose is returned
    verbatim — a silent fallback, never an error.
    """
    _ensure_session(storage, session_id)
    _enforce_rate_limit(request, _character_limiter, "refine")
    character = _require_character(storage, session_id)
    context = replace(
        character,
        backstory=(
            body.backstory if body.backstory is not None else character.backstory
        ),
        personality=(
            body.personality if body.personality is not None else character.personality
        ),
        appearance=(
            body.appearance if body.appearance is not None else character.appearance
        ),
        motivation=(
            body.motivation if body.motivation is not None else character.motivation
        ),
    )
    refined = refine_prose(context, client)
    if refined is None:
        return RefineResponse(
            backstory=character.backstory,
            personality=character.personality,
            appearance=character.appearance,
            motivation=character.motivation,
        )
    return RefineResponse(**refined)


@router.post(
    "/sessions/{session_id}/actions",
    response_model=ActionResponse,
)
def send_action(
    session_id: str,
    body: ActionRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> ActionResponse:
    """Process a player action and return narration plus updated state."""
    _ensure_session(storage, session_id)
    _enforce_rate_limit(request, _action_limiter, "action")

    with _session_lock_ctx(session_id):
        character = _require_character(storage, session_id)
        state = _current_state(storage, session_id, character)
        history = storage.load_messages(session_id)
        session_meta = storage.load_session(session_id)
        premise = session_meta.get("premise") if session_meta else None

        try:
            result = turn(body.action, state, history, client, premise=premise)
        except LLMClientError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        storage.save_state(session_id, result.state)
        _cache_state(session_id, result.state)
        storage.append_message(session_id, "user", body.action)
        storage.append_message(session_id, "assistant", result.narration)

    return ActionResponse(
        narration=result.narration,
        state=state_to_dict(result.state),
        rolls=[roll_to_dict(roll) for roll in result.rolls],
    )


@router.get(
    "/sessions/{session_id}/state",
    response_model=StateResponse,
)
def get_state(
    session_id: str,
    storage: Storage = Depends(get_storage),
) -> StateResponse:
    """Return the current game state for the session."""
    _ensure_session(storage, session_id)
    character = _require_character(storage, session_id)
    state = _current_state(storage, session_id, character)
    return StateResponse(state=state_to_dict(state))


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    storage: Storage = Depends(get_storage),
) -> list[SessionSummary]:
    """Return all saved sessions, newest activity first."""
    return [SessionSummary(**row) for row in storage.list_sessions()]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    storage: Storage = Depends(get_storage),
) -> SessionDetail:
    """Return a full resume bundle for ``session_id`` (404 if unknown)."""
    meta = _session_summary(storage, session_id)
    character = storage.load_character(session_id)
    if character is None:
        return SessionDetail(meta=meta, state={}, character={}, messages=[])
    state = _current_state(storage, session_id, character)
    return SessionDetail(
        meta=meta,
        state=state_to_dict(state),
        character=character_to_dict(character),
        messages=storage.load_messages(session_id),
    )


@router.get("/sessions/{session_id}/messages", response_model=list[dict])
def get_messages(
    session_id: str,
    storage: Storage = Depends(get_storage),
) -> list[dict]:
    """Return the ordered ``[{role, content}]`` transcript for a session."""
    _ensure_session(storage, session_id)
    return storage.load_messages(session_id)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    storage: Storage = Depends(get_storage),
) -> SessionSummary:
    """Rename ``session_id`` and return its updated summary."""
    if not storage.rename_session(session_id, body.title):
        raise HTTPException(status_code=404, detail="session not found")
    return _session_summary(storage, session_id)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> None:
    """Delete ``session_id`` and drop any cached live state (404 if unknown)."""
    _enforce_rate_limit(request, _delete_limiter, "delete")
    if not storage.delete_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    _invalidate_state(session_id)
    with _SESSION_LOCKS_GUARD:
        _SESSION_LOCKS.pop(session_id, None)


# ── Item Endpoints ────────────────────────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items",
    response_model=ItemActionResponse,
    status_code=201,
)
def create_item(
    session_id: str,
    character_id: str,
    body: CreateItemRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Create a new item for a character and persist it."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)
    _enforce_rate_limit(request, _item_limiter, "item")

    with _session_lock_ctx(session_id):
        try:
            item_type = BaseType(body.type) if body.type else BaseType.loot
        except ValueError as err:
            valid = ", ".join(t.value for t in BaseType)
            raise HTTPException(
                status_code=422,
                detail=f"Invalid item type '{body.type}'. Must be one of: {valid}",
            ) from err
        stats = ItemStats.from_dict(body.stats or {})
        item = Item(
            name=body.name,
            type=item_type,
            stats=stats,
            tags=tuple(body.tags or []),
            description=body.description or "",
        )
        storage.save_item(session_id, character_id, item)

    _invalidate_state(session_id)
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**item.to_dict()),
        message=f"Item '{item.name}' created",
    )


@router.get(
    "/sessions/{session_id}/characters/{character_id}/items",
    response_model=ItemListResponse,
)
def list_items(
    session_id: str,
    character_id: str,
    storage: Storage = Depends(get_storage),
) -> ItemListResponse:
    """Return all items for a character."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)

    items = storage.load_items(session_id, character_id)
    return ItemListResponse(items=[ItemResponse(**item.to_dict()) for item in items])


@router.get(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}",
    response_model=ItemResponse,
)
def get_item(
    session_id: str,
    character_id: str,
    item_id: str,
    storage: Storage = Depends(get_storage),
) -> ItemResponse:
    """Return a single item by id."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)

    item = storage.load_item(session_id, character_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    return ItemResponse(**item.to_dict())


@router.delete(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}",
    response_model=ItemActionResponse,
)
def delete_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Delete an item by id."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)
    _enforce_rate_limit(request, _item_limiter, "item")

    with _session_lock_ctx(session_id):
        deleted = storage.delete_item(session_id, character_id, item_id)

    _invalidate_state(session_id)
    if not deleted:
        return ItemActionResponse(success=False, message="item not found")
    return ItemActionResponse(success=True, message="item deleted")


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}/equip",
    response_model=ItemActionResponse,
)
def equip_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Set item equipped=true."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)
    _enforce_rate_limit(request, _item_limiter, "item")

    with _session_lock_ctx(session_id):
        item = storage.load_item(session_id, character_id, item_id)
        if item is None:
            return ItemActionResponse(success=False, message="item not found")
        equipped = replace(item, equipped=True)
        storage.update_item(session_id, character_id, equipped)

    _invalidate_state(session_id)
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**equipped.to_dict()),
        message=f"Item '{item.name}' equipped",
    )


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}/unequip",
    response_model=ItemActionResponse,
)
def unequip_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Set item equipped=false."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)
    _enforce_rate_limit(request, _item_limiter, "item")

    with _session_lock_ctx(session_id):
        item = storage.load_item(session_id, character_id, item_id)
        if item is None:
            return ItemActionResponse(success=False, message="item not found")
        unequipped = replace(item, equipped=False)
        storage.update_item(session_id, character_id, unequipped)

    _invalidate_state(session_id)
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**unequipped.to_dict()),
        message=f"Item '{item.name}' unequipped",
    )


@router.post(
    "/sessions/{session_id}/characters/{character_id}/items/{item_id}/use",
    response_model=ItemActionResponse,
)
def use_item(
    session_id: str,
    character_id: str,
    item_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> ItemActionResponse:
    """Use a consumable item — decrement quantity or delete when depleted."""
    _ensure_session(storage, session_id)
    _require_character_id(storage, session_id, character_id)
    _enforce_rate_limit(request, _item_limiter, "item")

    with _session_lock_ctx(session_id):
        item = storage.load_item(session_id, character_id, item_id)
        if item is None:
            return ItemActionResponse(success=False, message="item not found")
        if item.type != BaseType.consumable:
            return ItemActionResponse(
                success=False,
                item=ItemResponse(**item.to_dict()),
                message=f"Item '{item.name}' is not consumable",
            )
        if item.quantity > 1:
            used = replace(item, quantity=item.quantity - 1)
            storage.update_item(session_id, character_id, used)
        else:
            storage.delete_item(session_id, character_id, item_id)
            _invalidate_state(session_id)
            return ItemActionResponse(
                success=True,
                item=None,
                message=f"Item '{item.name}' used and depleted",
            )

    _invalidate_state(session_id)
    return ItemActionResponse(
        success=True,
        item=ItemResponse(**used.to_dict()),
        message=f"Item '{item.name}' used",
    )
