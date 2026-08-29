"""AI character generation from a free-text description.

The LLM produces an untrusted JSON blob; this module parses it defensively and
defers every semantic decision to :mod:`open_tavern.character.validation`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from open_tavern.character import (
    CharacterSheet,
    HIT_DIE_SIZES,
    normalize,
    validate,
)
from open_tavern.story.prompts import (
    character_gen_prompt,
    class_gen_prompt,
    structured_character_gen_prompt,
)


class CharacterGenerationError(ValueError):
    """Raised when the LLM's character sheet cannot be parsed or validated."""


@dataclass(frozen=True)
class ClassDefinition:
    """A single class/role definition: name, prose description, hit die size.

    ``hit_die`` is one of :data:`open_tavern.character.HIT_DIE_SIZES` (6, 8, 10,
    12) — the engine, never the LLM, owns that constraint.
    """

    name: str
    description: str
    hit_die: int


#: Structured persona/identity fields that trigger the structured prompt path.
_STRUCTURED_FIELDS: tuple[str, ...] = (
    "name",
    "race",
    "class_concept",
    "backstory",
    "personality",
    "appearance",
    "motivation",
)


def generate_character(
    description: str = "",
    client=None,
    *,
    name: str = "",
    race: str = "",
    class_concept: str = "",
    backstory: str = "",
    personality: str = "",
    appearance: str = "",
    motivation: str = "",
    class_name: str = "",
    class_hit_die: int | None = None,
    class_description: str = "",
) -> tuple[CharacterSheet, str, str]:
    """Generate a validated, normalized :class:`CharacterSheet`.

    When any structured field is non-empty the structured prompt is used;
    otherwise the legacy free-text ``description`` path applies. Both paths
    render player input as delimited untrusted data. ``level`` defaults to 1
    via :func:`normalize`.

    Returns ``(character, opening, scene)``: the sheet, its opening narration
    (stripped), and the LLM's opening-scene description (stripped, ``""`` when
    absent) so the route can seed game state and the transcript.

    Player-supplied ``class_name``/``class_hit_die``/``class_description``
    override the LLM-derived values for the generated sheet — see
    :func:`_apply_class_override`.
    """
    description = description or ""
    structured_values: dict[str, str] = {
        "name": name,
        "race": race,
        "class_concept": class_concept,
        "backstory": backstory,
        "personality": personality,
        "appearance": appearance,
        "motivation": motivation,
    }
    if any((structured_values[field] or "").strip() for field in _STRUCTURED_FIELDS):
        prompt = structured_character_gen_prompt(
            name=name,
            race=race,
            class_concept=class_concept,
            backstory=backstory,
            personality=personality,
            appearance=appearance,
            motivation=motivation,
            description=description,
        )
    else:
        prompt = character_gen_prompt(description)
    text = client.chat([{"role": "user", "content": prompt}], json_mode=True)
    data = _parse_json(text)
    _apply_class_override(data, class_name, class_hit_die, class_description)
    result = validate(data)
    if not result.is_valid:
        raise CharacterGenerationError(
            "invalid character sheet: " + "; ".join(result.errors)
        )
    sheet = normalize(data)
    opening = (sheet.opening or "").strip()
    scene = _extract_scene(data)
    return sheet, opening, scene


def _apply_class_override(
    raw: object,
    class_name: str = "",
    class_hit_die: int | None = None,
    class_description: str = "",
) -> None:
    """Overlay player-supplied class values onto ``raw`` when non-empty.

    Overrides take precedence over the LLM-derived values, but blank/absent
    overrides are ignored so they cannot wipe a valid generated value. A hit
    die outside :data:`HIT_DIE_SIZES` is likewise ignored — the engine, never
    the caller, owns that constraint. Mutates ``raw`` in place when it is a
    mapping; non-mappings (which fail validation anyway) are left untouched.
    """
    if not isinstance(raw, dict):
        return
    name = (class_name or "").strip()
    if name:
        raw["character_class"] = name
    if class_hit_die in HIT_DIE_SIZES:
        raw["hit_die"] = class_hit_die
    description = (class_description or "").strip()
    if description:
        raw["class_description"] = description


def _extract_scene(raw: object) -> str:
    """Return the LLM's opening-scene description, stripped; ``""`` when absent."""
    if not isinstance(raw, dict):
        return ""
    scene = raw.get("scene")
    if not isinstance(scene, str):
        return ""
    return scene.strip()


def generate_class(class_concept: str, client=None) -> ClassDefinition:
    """Generate a :class:`ClassDefinition` from a free-text concept (preview only).

    Renders ``class_concept`` as delimited untrusted data and requests JSON.
    Never raises on malformed LLM output — every parse/validation failure falls
    back to a safe :class:`ClassDefinition`. Engine owns validation: ``name``
    must be non-empty, ``hit_die`` coerced and constrained to
    :data:`HIT_DIE_SIZES`, ``description`` forced to a string.
    """
    prompt = class_gen_prompt(class_concept)
    text = client.chat([{"role": "user", "content": prompt}], json_mode=True)
    try:
        raw = _parse_json(text)
    except CharacterGenerationError:
        raw = None
    fallback_name = class_concept.strip() or "adventurer"
    return _class_definition_from(raw, fallback_name)


def _class_definition_from(raw: object, fallback_name: str) -> ClassDefinition:
    """Build a safe :class:`ClassDefinition` from untrusted LLM output.

    Non-mapping payloads, missing/malformed fields, and out-of-range hit dice
    all resolve to safe defaults — never an exception.
    """
    if not isinstance(raw, dict):
        return ClassDefinition(name=fallback_name, description="", hit_die=8)
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        name = fallback_name
    else:
        name = name.strip()
    description = raw.get("description")
    if not isinstance(description, str):
        description = ""
    hit_die = raw.get("hit_die")
    try:
        hit_die = int(hit_die)
    except (TypeError, ValueError):
        hit_die = 8
    if hit_die not in HIT_DIE_SIZES:
        hit_die = 8
    return ClassDefinition(name=name, description=description, hit_die=hit_die)


def _parse_json(text: str) -> object:
    """Parse an LLM response into a JSON object, tolerating markdown fences."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise CharacterGenerationError("LLM response was not valid JSON") from exc
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as inner:
            raise CharacterGenerationError(
                f"LLM response was not valid JSON: {inner}"
            ) from inner


def _strip_fences(text: str) -> str:
    """Strip leading/trailing markdown code fences, if present."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    return cleaned
