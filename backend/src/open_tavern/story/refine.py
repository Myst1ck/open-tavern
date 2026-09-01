"""One-shot prose refinement for an existing character sheet.

Batches the four prose fields (backstory, personality, appearance,
motivation) into a SINGLE LLM call. LLM output is untrusted JSON parsed
defensively; ANY failure (client error, invalid JSON, missing or non-string
fields) returns ``None`` so the caller can pass the original text through
unchanged. Never raises.
"""

from __future__ import annotations

from open_tavern.character.models import CharacterSheet
from open_tavern.story.character_gen import CharacterGenerationError, _parse_json
from open_tavern.story.client import LLMClientError
from open_tavern.story.prompts import refine_prose_prompt

#: Prose fields rewritten by refinement, in output-key order.
PROSE_FIELDS: tuple[str, ...] = ("backstory", "personality", "appearance", "motivation")


def refine_prose(character: CharacterSheet, client=None) -> dict[str, str] | None:
    """Rewrite ``character``'s four prose fields via one LLM call.

    Builds the refinement prompt from the full sheet context, sends exactly
    ONE ``client.chat(..., json_mode=True)`` call, and parses the response
    with the defensive ``character_gen._parse_json`` pattern (fence
    stripping + substring recovery).

    Returns a dict with exactly ``backstory``/``personality``/``appearance``/
    ``motivation`` string values on success, ``None`` on ANY failure
    (``LLMClientError``, parse failure, or missing/non-string fields) —
    never raises.
    """
    prompt = refine_prose_prompt(
        name=character.name,
        race=character.race,
        character_class=character.character_class,
        level=character.level,
        backstory=character.backstory,
        personality=character.personality,
        appearance=character.appearance,
        motivation=character.motivation,
    )
    try:
        text = client.chat([{"role": "user", "content": prompt}], json_mode=True)
        raw = _parse_json(text)
    except (LLMClientError, CharacterGenerationError):
        return None
    if not isinstance(raw, dict):
        return None
    refined: dict[str, str] = {}
    for field in PROSE_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str):
            return None
        refined[field] = value.strip()
    return refined
