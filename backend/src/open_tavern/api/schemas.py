"""Pydantic request/response schemas and JSON serialization helpers.

Serialization converts the immutable domain models
(:class:`~open_tavern.character.models.CharacterSheet`,
:class:`~open_tavern.state.models.GameState`) into plain JSON-friendly dicts.
Tuples and frozensets become lists so the payloads encode cleanly.
"""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, Field

from open_tavern.character import CharacterSheet
from open_tavern.state import GameState
from open_tavern.story import RollOutcome


class CreateSessionRequest(BaseModel):
    """Request body for creating a new game session."""

    world_theme: str = Field(max_length=200)
    title: str | None = Field(default=None, max_length=200)


class CreateSessionResponse(BaseModel):
    """Response for a newly created session."""

    session_id: str
    world_theme: str


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


class RenameSessionRequest(BaseModel):
    """Request body for renaming a session."""

    title: str = Field(max_length=200)


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
        "inventory": list(character.inventory),
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
        "inventory": list(state.inventory),
        "conditions": sorted(state.conditions),
        "scene": state.scene,
        "character": character_to_dict(state.character),
    }


def roll_to_dict(roll: RollOutcome) -> dict:
    """Serialize a single :class:`RollOutcome` into a plain dict."""
    return asdict(roll)
