"""Story engine: LLM client, GM prompts, two-phase turn loop, character generation."""

from open_tavern.story.character_gen import (
    CharacterGenerationError,
    ClassDefinition,
    generate_character,
    generate_class,
)
from open_tavern.story.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    OpenAIClient,
)
from open_tavern.story.game import RollOutcome, TurnResult, turn
from open_tavern.story.prompts import (
    character_gen_prompt,
    gm_system_prompt,
    roll_result_prompt,
    user_action_prompt,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TEMPERATURE",
    "OpenAIClient",
    "CharacterGenerationError",
    "ClassDefinition",
    "generate_character",
    "generate_class",
    "RollOutcome",
    "TurnResult",
    "turn",
    "character_gen_prompt",
    "gm_system_prompt",
    "roll_result_prompt",
    "user_action_prompt",
]
