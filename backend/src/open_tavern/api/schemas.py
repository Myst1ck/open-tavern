"""Pydantic request/response schemas and JSON serialization helpers.

Serialization converts the immutable domain models
(:class:`~open_tavern.character.models.CharacterSheet`,
:class:`~open_tavern.state.models.GameState`) into plain JSON-friendly dicts.
Tuples and frozensets become lists so the payloads encode cleanly.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any, overload

from pydantic import BaseModel, Field, field_validator

from open_tavern.character import CharacterSheet
from open_tavern.state import GameState
from open_tavern.story import RollOutcome
from open_tavern.story.style import (
    DEFAULT_TONE,
    DEFAULT_VERBOSITY,
    TONES,
    VERBOSITIES,
    DmStyle,
    normalize_dm_style,
)


class WorldGenerateRequest(BaseModel):
    """Request body for stateless world generation from a description.

    ``description`` is the player's free-text world idea; ``surprise`` asks the
    LLM to invent a world when no description is given. At least one of the two
    must be supplied — the route returns 422 otherwise.
    """

    description: str | None = Field(default=None, max_length=2000)
    surprise: bool = False


class WorldGenerateResponse(BaseModel):
    """Response carrying a generated campaign theme and premise."""

    theme: str
    premise: str


class DmStyleRequest(BaseModel):
    """Request body for the DM narration style.

    ``tone`` and ``verbosity`` must be registry keys (:data:`TONES`,
    :data:`VERBOSITIES`) — unknown keys fail with 422 instead of silently
    defaulting. ``custom_tone`` is a free-form note, capped at 1000 chars by
    the field below and sanitized by the prompt builder.
    """

    tone: str = Field(default=DEFAULT_TONE, max_length=200)
    verbosity: str = Field(default=DEFAULT_VERBOSITY, max_length=200)
    custom_tone: str = Field(default="", max_length=1000)

    @field_validator("tone")
    @classmethod
    def _known_tone(cls, value: str) -> str:
        if value not in TONES:
            raise ValueError(f"unknown tone: expected one of {sorted(TONES)}")
        return value

    @field_validator("verbosity")
    @classmethod
    def _known_verbosity(cls, value: str) -> str:
        if value not in VERBOSITIES:
            raise ValueError(
                f"unknown verbosity: expected one of {sorted(VERBOSITIES)}"
            )
        return value

    def to_style(self) -> DmStyle:
        """Return the normalized :class:`DmStyle` for this request."""
        return normalize_dm_style(self.model_dump())


class CreateSessionRequest(BaseModel):
    """Request body for creating a new game session."""

    world_theme: str = Field(max_length=200)
    title: str | None = Field(default=None, max_length=200)
    premise: str | None = Field(default=None, max_length=2000)
    dm_style: DmStyleRequest | None = None


class CreateSessionResponse(BaseModel):
    """Response for a newly created session."""

    session_id: str
    world_theme: str
    premise: str | None = None
    dm_style: dict | None = None


class CharacterRequest(BaseModel):
    """Request body for generating a character.

    Accepts either a legacy free-text ``description`` or a set of optional
    structured fields. Backward compatible: a body with only ``description``
    still validates.
    """

    description: str | None = Field(default=None, max_length=2000)
    name: str | None = Field(default=None, max_length=2000)
    race: str | None = Field(default=None, max_length=2000)
    class_concept: str | None = Field(default=None, max_length=2000)
    backstory: str | None = Field(default=None, max_length=2000)
    personality: str | None = Field(default=None, max_length=2000)
    appearance: str | None = Field(default=None, max_length=2000)
    motivation: str | None = Field(default=None, max_length=2000)
    class_name: str | None = Field(default=None, max_length=2000)
    class_hit_die: int | None = None
    class_description: str | None = Field(default=None, max_length=2000)


class CharacterResponse(BaseModel):
    """Response carrying a generated character sheet and its opening narration.

    ``opening`` is the LLM-generated opening scene prose, seeded as the first
    assistant message; empty when the model produced none.
    """

    character: dict
    opening: str = ""


class RefineRequest(BaseModel):
    """Request body for refining a character's prose fields.

    All fields optional: unspecified fields pass through unchanged.
    """

    backstory: str | None = Field(default=None, max_length=2000)
    personality: str | None = Field(default=None, max_length=2000)
    appearance: str | None = Field(default=None, max_length=2000)
    motivation: str | None = Field(default=None, max_length=2000)


class RefineResponse(BaseModel):
    """Response carrying post-refine prose values."""

    backstory: str
    personality: str
    appearance: str
    motivation: str


class ClassRequest(BaseModel):
    """Request body for previewing a character class from a concept."""

    class_concept: str = Field(min_length=1, max_length=2000)


class ClassResponse(BaseModel):
    """Response carrying a generated class definition (preview, not persisted)."""

    class_definition: dict


class ActionRequest(BaseModel):
    """Request body for submitting a player action."""

    action: str = Field(max_length=2000)


class ActionResponse(BaseModel):
    """Response for a processed player turn."""

    narration: str
    state: dict
    rolls: list[dict]


class StateResponse(BaseModel):
    """Response carrying the current game state."""

    state: dict


class SessionSummary(BaseModel):
    """Lightweight summary of a saved session for list views."""

    id: str
    title: str
    world_theme: str
    created_at: str
    updated_at: str
    character_name: str | None = None


class SessionDetail(BaseModel):
    """Full resume bundle: session metadata plus play state and transcript."""

    meta: SessionSummary
    state: dict
    character: dict
    messages: list[dict]
    dm_style: dict | None = None


class RenameSessionRequest(BaseModel):
    """Request body for renaming a session."""

    title: str = Field(max_length=200)


class ItemResponse(BaseModel):
    """Response carrying a single item's data."""

    id: str
    name: str
    type: str
    tags: list[str]
    stats: dict
    description: str
    equipped: bool
    quantity: int


class ItemListResponse(BaseModel):
    """Response carrying a list of items."""

    items: list[ItemResponse]


class ItemActionResponse(BaseModel):
    """Response for item mutation operations."""

    success: bool
    item: ItemResponse | None = None
    message: str


class CreateItemRequest(BaseModel):
    """Request body for creating a new item.

    ``stats`` is intentionally freeform (``dict[str, Any]``); numeric coercion
    and clamping happen in :meth:`ItemStats.from_dict`.
    """

    name: str = Field(max_length=200)
    type: str | None = Field(default=None, max_length=50)
    stats: dict[str, Any] | None = None
    tags: list[Annotated[str, Field(max_length=50)]] | None = Field(
        default=None, max_length=20
    )
    description: str | None = Field(default=None, max_length=2000)


@overload
def dm_style_to_dict(style: DmStyle) -> dict: ...


@overload
def dm_style_to_dict(style: None) -> None: ...


def dm_style_to_dict(style: DmStyle | None) -> dict | None:
    """Serialize a :class:`DmStyle` into a JSON-friendly dict."""
    if style is None:
        return None
    return asdict(style)


def character_to_dict(character: CharacterSheet) -> dict:
    """Serialize a :class:`CharacterSheet` into a JSON-friendly dict."""
    return {
        "name": character.name,
        "race": character.race,
        "character_class": character.character_class,
        "level": character.level,
        "abilities": asdict(character.abilities),
        "skills": dict(character.skills),
        "hp": character.hp,
        "max_hp": character.max_hp,
        "proficiency_bonus": character.proficiency_bonus,
        "inventory": [item.to_dict() for item in character.inventory],
        "conditions": list(character.conditions),
        "backstory": character.backstory,
        "personality": character.personality,
        "appearance": character.appearance,
        "motivation": character.motivation,
        "hit_die": character.hit_die,
        "class_description": character.class_description,
        "goals": [asdict(g) for g in character.goals],
        "quests": [asdict(q) for q in character.quests],
        "opening": character.opening,
    }


def state_to_dict(state: GameState) -> dict:
    """Serialize a :class:`GameState` into a JSON-friendly dict."""
    return {
        "current_hp": state.current_hp,
        "max_hp": state.max_hp,
        "conditions": sorted(state.conditions),
        "scene": state.scene,
        "character": character_to_dict(state.character),
    }


def roll_to_dict(roll: RollOutcome) -> dict:
    """Serialize a single :class:`RollOutcome` into a plain dict."""
    return asdict(roll)
