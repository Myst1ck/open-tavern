"""Stateless world-generation endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from open_tavern.api import guards
from open_tavern.api.llm import ChatClient, get_per_request_client, llm_failure
from open_tavern.api.runtime import run_llm_task
from open_tavern.api.schemas import WorldGenerateRequest, WorldGenerateResponse
from open_tavern.story import CharacterGenerationError
from open_tavern.story.character_gen import _parse_json
from open_tavern.story.client import LLMClientError
from open_tavern.story.prompts import world_gen_prompt

router = APIRouter()


@router.post(
    "/world/generate",
    response_model=WorldGenerateResponse,
)
async def generate_world(
    body: WorldGenerateRequest,
    request: Request,
    client: ChatClient = Depends(get_per_request_client),
) -> WorldGenerateResponse:
    """Expand a world description into theme + premise (stateless).

    Requires a non-empty ``description`` unless ``surprise`` is set; otherwise
    422. Nothing is persisted; any LLM or parse failure surfaces as 502.
    """
    description = (body.description or "").strip()
    if not description and not body.surprise:
        raise HTTPException(
            status_code=422,
            detail="description is required unless surprise is true",
        )
    guards.enforce_rate_limit(request, guards.world_limiter, "world")
    prompt = world_gen_prompt(description, surprise=body.surprise)

    def _call():
        try:
            return _parse_json(
                client.chat([{"role": "user", "content": prompt}], json_mode=True)
            )
        except CharacterGenerationError as exc:
            # Our own parser text (same shape as the return-value checks below)
            # and the only clue the caller gets when the model emits bad JSON.
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except LLMClientError as exc:
            raise llm_failure(exc) from exc

    data = await run_llm_task(_call)
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM response was not valid JSON")
    theme = data.get("theme")
    premise = data.get("premise")
    if not isinstance(theme, str) or not isinstance(premise, str):
        raise HTTPException(
            status_code=502, detail="LLM response missing theme or premise"
        )
    return WorldGenerateResponse(theme=theme.strip(), premise=premise.strip())
