"""Character generation, class preview, and prose refine endpoints."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request

from open_tavern.api import guards
from open_tavern.api.llm import ChatClient, get_per_request_client, llm_failure
from open_tavern.api.runtime import (
    cache_state,
    get_storage,
    run_llm_task,
    session_lock_ctx,
)
from open_tavern.api.schemas import (
    CharacterRequest,
    CharacterResponse,
    ClassRequest,
    ClassResponse,
    RefineRequest,
    RefineResponse,
    character_to_dict,
)
from open_tavern.state import new_state
from open_tavern.storage import Storage
from open_tavern.story import (
    CharacterGenerationError,
    generate_character,
    generate_class,
)
from open_tavern.story.client import LLMClientError
from open_tavern.story.refine import refine_prose

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/sessions/{session_id}/character",
    response_model=CharacterResponse,
)
async def create_character(
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

    The whole lock-held section (premise read, LLM generation, persistence)
    runs on the bounded executor, so the per-session lock is only ever
    waited on from an executor worker — never the shared threadpool.
    """
    guards.enforce_rate_limit(request, guards.character_limiter, "character")
    await asyncio.to_thread(guards.ensure_session, storage, session_id)

    def _generate() -> CharacterResponse:
        with session_lock_ctx(session_id):
            # Re-check under the lock: a delete queued ahead of this generation
            # would otherwise leave orphan character and message rows.
            guards.ensure_session(storage, session_id)
            # Targeted single-column probe: the premise is the only session
            # field needed here, so skip the full character + transcript load
            # that ``load_session`` performs.
            premise = storage.session_premise(session_id)
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
                # Our own validator text — no upstream URL or body — and the
                # only clue the player gets when the model emits a bad sheet.
                logger.warning("Character generation failed: %s", exc)
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            except LLMClientError as exc:
                raise llm_failure(exc) from exc
            storage.save_character(session_id, sheet)
            state = new_state(sheet)
            if scene:
                state = replace(state, scene=scene)
            # State + opening message commit as one transaction (same
            # invariant as send_action's ``save_turn``).
            storage.save_opening(session_id, state, opening or None)
            cache_state(session_id, state)
        return CharacterResponse(character=character_to_dict(sheet), opening=opening)

    return await run_llm_task(_generate)


@router.post(
    "/sessions/{session_id}/character/class",
    response_model=ClassResponse,
)
async def create_class_preview(
    session_id: str,
    body: ClassRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> ClassResponse:
    """Generate a class definition preview from a concept; nothing is persisted."""
    guards.enforce_rate_limit(request, guards.character_limiter, "class")
    await asyncio.to_thread(guards.ensure_session, storage, session_id)

    def _preview():
        try:
            return generate_class(body.class_concept, client)
        except LLMClientError as exc:
            raise llm_failure(exc) from exc

    definition = await run_llm_task(_preview)
    return ClassResponse(
        class_definition={
            "name": definition.name,
            "description": definition.description,
            "hit_die": definition.hit_die,
        }
    )


@router.post(
    "/sessions/{session_id}/character/refine",
    response_model=RefineResponse,
)
async def refine_character(
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
    guards.enforce_rate_limit(request, guards.character_limiter, "refine")
    await asyncio.to_thread(guards.ensure_session, storage, session_id)
    character = await asyncio.to_thread(guards.require_character, storage, session_id)
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

    def _refine():
        return refine_prose(context, client)

    refined = await run_llm_task(_refine)
    if refined is None:
        return RefineResponse(
            backstory=character.backstory,
            personality=character.personality,
            appearance=character.appearance,
            motivation=character.motivation,
        )
    return RefineResponse(**refined)
