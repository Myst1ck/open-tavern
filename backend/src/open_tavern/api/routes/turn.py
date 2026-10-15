"""Player-action endpoint that advances a session's story."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from open_tavern.api import guards
from open_tavern.api.llm import ChatClient, get_per_request_client, llm_failure
from open_tavern.api.runtime import (
    cache_state,
    current_state,
    get_storage,
    run_llm_task,
    session_lock_ctx,
)
from open_tavern.api.schemas import (
    ActionRequest,
    ActionResponse,
    roll_to_dict,
    state_to_dict,
)
from open_tavern.storage import Storage
from open_tavern.story import turn
from open_tavern.story.client import LLMClientError

router = APIRouter()


@router.post(
    "/sessions/{session_id}/actions",
    response_model=ActionResponse,
)
async def send_action(
    session_id: str,
    body: ActionRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> ActionResponse:
    """Process a player action and return narration plus updated state.

    The whole lock-held section (state load, LLM turn, atomic persistence)
    runs on the bounded executor, so the per-session lock is only ever
    waited on from an executor worker — never the shared threadpool.
    """
    guards.enforce_rate_limit(request, guards.action_limiter, "action")
    await asyncio.to_thread(guards.ensure_session, storage, session_id)

    def _run_turn():
        with session_lock_ctx(session_id):
            # Re-check under the lock: a delete queued ahead of this action
            # would otherwise surface as 409 (missing character) instead of
            # 404.
            guards.ensure_session(storage, session_id)
            character = guards.require_character(storage, session_id)
            state = current_state(storage, session_id, character)
            history = storage.load_messages(session_id)
            premise = storage.session_premise(session_id)

            try:
                result = turn(body.action, state, history, client, premise=premise)
            except LLMClientError as exc:
                raise llm_failure(exc) from exc

            # State + both transcript messages commit as a single storage
            # transaction so a crash cannot leave state and transcript
            # diverging (e.g. state advanced but the player message lost).
            storage.save_turn(session_id, result.state, body.action, result.narration)
            cache_state(session_id, result.state)
        return result

    result = await run_llm_task(_run_turn)
    return ActionResponse(
        narration=result.narration,
        state=state_to_dict(result.state),
        rolls=[roll_to_dict(roll) for roll in result.rolls],
    )
