"""Session lifecycle, transcript, and state endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from open_tavern.api import guards
from open_tavern.api.runtime import (
    current_state,
    get_storage,
    invalidate_state,
    session_lock_ctx,
)
from open_tavern.api.schemas import (
    CreateSessionRequest,
    CreateSessionResponse,
    DmStyleRequest,
    RenameSessionRequest,
    SessionDetail,
    SessionSummary,
    StateResponse,
    character_to_dict,
    dm_style_to_dict,
    state_to_dict,
)
from open_tavern.storage import Storage

router = APIRouter()


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
    guards.enforce_rate_limit(request, guards.create_limiter, "create")
    style = body.dm_style.to_style() if body.dm_style is not None else None
    session_id = storage.create_session(
        body.world_theme, body.title, premise=body.premise, dm_style=style
    )
    return CreateSessionResponse(
        session_id=session_id,
        world_theme=body.world_theme,
        premise=body.premise,
        dm_style=dm_style_to_dict(style),
    )


@router.get(
    "/sessions/{session_id}/state",
    response_model=StateResponse,
)
def get_state(
    session_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> StateResponse:
    """Return the current game state for the session."""
    guards.enforce_rate_limit(request, guards.read_limiter, "read")
    guards.ensure_session(storage, session_id)
    character = guards.require_character(storage, session_id)
    state = current_state(storage, session_id, character)
    return StateResponse(state=state_to_dict(state))


@router.get("/sessions", response_model=list[SessionSummary])
def list_sessions(
    request: Request,
    storage: Storage = Depends(get_storage),
) -> list[SessionSummary]:
    """Return all saved sessions, newest activity first."""
    guards.enforce_rate_limit(request, guards.read_limiter, "read")
    return [SessionSummary(**row) for row in storage.list_sessions()]


@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> SessionDetail:
    """Return a full resume bundle for ``session_id`` (404 if unknown)."""
    guards.enforce_rate_limit(request, guards.read_limiter, "read")
    meta = _session_summary(storage, session_id)
    style = storage.session_dm_style(session_id)
    character = storage.load_character(session_id)
    if character is None:
        return SessionDetail(
            meta=meta,
            state={},
            character={},
            messages=[],
            dm_style=dm_style_to_dict(style),
        )
    state = current_state(storage, session_id, character)
    return SessionDetail(
        meta=meta,
        state=state_to_dict(state),
        character=character_to_dict(character),
        messages=storage.load_messages(session_id),
        dm_style=dm_style_to_dict(style),
    )


@router.get("/sessions/{session_id}/messages", response_model=list[dict])
def get_messages(
    session_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> list[dict]:
    """Return the ordered ``[{role, content}]`` transcript for a session."""
    guards.enforce_rate_limit(request, guards.read_limiter, "read")
    guards.ensure_session(storage, session_id)
    return storage.load_messages(session_id)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> SessionSummary:
    """Rename ``session_id`` and return its updated summary."""
    guards.enforce_rate_limit(request, guards.delete_limiter, "rename")
    if not storage.rename_session(session_id, body.title):
        raise HTTPException(status_code=404, detail="session not found")
    return _session_summary(storage, session_id)


@router.put("/sessions/{session_id}/style", response_model=dict)
def update_session_style(
    session_id: str,
    body: DmStyleRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> dict:
    """Set the DM narration style for ``session_id`` and echo the value.

    Unknown ``tone``/``verbosity`` keys are rejected with 422 by the schema;
    unknown sessions return 404.
    """
    guards.enforce_rate_limit(request, guards.delete_limiter, "style")
    style = body.to_style()
    if not storage.update_dm_style(session_id, style):
        raise HTTPException(status_code=404, detail="session not found")
    return dm_style_to_dict(style)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    request: Request,
    storage: Storage = Depends(get_storage),
) -> None:
    """Delete ``session_id`` and drop any cached live state (404 if unknown)."""
    guards.enforce_rate_limit(request, guards.delete_limiter, "delete")
    with session_lock_ctx(session_id):
        if not storage.delete_session(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        invalidate_state(session_id)
