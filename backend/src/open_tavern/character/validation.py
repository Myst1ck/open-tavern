"""Validation and normalization for untrusted AI-generated character sheets.

``validate`` reports every problem in a structured result (never raises).
``normalize`` turns a valid raw dict into a :class:`CharacterSheet`, filling
optional fields with safe defaults and recomputing all derived values.
"""

from __future__ import annotations

from dataclasses import dataclass

from open_tavern.character.models import (
    ABILITIES,
    HIT_DIE_SIZES,
    SKILLS,
    STATUS_VALUES,
    AbilityScores,
    CharacterSheet,
    Goal,
    Quest,
    max_hp_for,
    proficiency_bonus,
    resolve_ability,
    resolve_skill,
)

MIN_ABILITY_SCORE: int = 3
MAX_ABILITY_SCORE: int = 18

DEFAULT_NAME: str = ""
DEFAULT_LEVEL: int = 1
DEFAULT_HIT_DIE: int = 8
DEFAULT_BACKSTORY: str = ""
DEFAULT_PERSONALITY: str = ""
DEFAULT_APPEARANCE: str = ""
DEFAULT_MOTIVATION: str = ""
DEFAULT_CLASS_DESCRIPTION: str = ""
DEFAULT_OPENING: str = ""


@dataclass(frozen=True)
class ValidationResult:
    """Structured outcome of :func:`validate`; ``errors`` is empty when valid."""

    errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def validate(raw: object) -> ValidationResult:
    """Validate an untrusted character-sheet dict, returning a result object.

    Never raises — every problem is collected into ``errors``.
    """
    if not isinstance(raw, dict):
        return ValidationResult(errors=("character sheet must be a mapping",))

    errors: list[str] = []
    _validate_abilities(raw.get("abilities"), errors)
    _validate_class(raw.get("character_class"), errors)
    _validate_race(raw.get("race"), errors)
    _validate_level(raw.get("level"), errors)
    _validate_name(raw.get("name"), errors)
    _validate_skills(raw.get("skills"), errors)
    _validate_inventory(raw.get("inventory"), errors)
    _validate_conditions(raw.get("conditions"), errors)
    _validate_backstory(raw.get("backstory"), errors)
    _validate_personality(raw.get("personality"), errors)
    _validate_appearance(raw.get("appearance"), errors)
    _validate_motivation(raw.get("motivation"), errors)
    _validate_hit_die(raw.get("hit_die"), errors)
    _validate_class_description(raw.get("class_description"), errors)
    _validate_goals(raw.get("goals"), errors)
    _validate_quests(raw.get("quests"), errors)
    _validate_opening(raw.get("opening"), errors)
    return ValidationResult(errors=tuple(errors))


def normalize(raw: object) -> CharacterSheet:
    """Build a :class:`CharacterSheet` from ``raw``.

    Fills missing optional fields with safe defaults and recomputes every
    derived value (modifiers, proficiency bonus, hit points) from raw scores.
    Raises ``ValueError`` if ``raw`` fails validation.
    """
    result = validate(raw)
    if not result.is_valid:
        raise ValueError(f"Invalid character sheet: {'; '.join(result.errors)}")

    assert isinstance(raw, dict)  # guaranteed by validate above
    scores = _resolve_scores(raw["abilities"])
    abilities = AbilityScores(
        strength=scores["STR"],
        dexterity=scores["DEX"],
        constitution=scores["CON"],
        intelligence=scores["INT"],
        wisdom=scores["WIS"],
        charisma=scores["CHA"],
    )

    character_class = raw["character_class"]

    level = raw.get("level", DEFAULT_LEVEL)
    hit_die = raw.get("hit_die", DEFAULT_HIT_DIE)
    max_hp = max_hp_for(hit_die, level, abilities.constitution)

    return CharacterSheet(
        name=raw.get("name", DEFAULT_NAME),
        race=raw["race"],
        character_class=character_class,
        level=level,
        abilities=abilities,
        hp=max_hp,
        max_hp=max_hp,
        proficiency_bonus=proficiency_bonus(level),
        skills=_build_skills(raw.get("skills")),
        inventory=tuple(raw.get("inventory", ())),
        conditions=tuple(raw.get("conditions", ())),
        backstory=raw.get("backstory", DEFAULT_BACKSTORY),
        personality=raw.get("personality", DEFAULT_PERSONALITY),
        appearance=raw.get("appearance", DEFAULT_APPEARANCE),
        motivation=raw.get("motivation", DEFAULT_MOTIVATION),
        hit_die=hit_die,
        class_description=raw.get("class_description", DEFAULT_CLASS_DESCRIPTION),
        goals=_build_goals(raw.get("goals")),
        quests=_build_quests(raw.get("quests")),
        opening=raw.get("opening", DEFAULT_OPENING),
    )


def _resolve_scores(abilities: dict) -> dict[str, int]:
    """Resolve raw ability keys to canonical abbreviations, keyed by abbreviation."""
    resolved: dict[str, int] = {}
    for key, value in abilities.items():
        canonical = resolve_ability(key)
        if canonical is not None:
            resolved[canonical] = value
    return resolved


def _build_skills(raw_skills: object) -> dict[str, bool]:
    """Build a complete skill->proficient mapping, defaulting to non-proficient."""
    skills: dict[str, bool] = {skill: False for skill in SKILLS}
    if isinstance(raw_skills, dict):
        for key, value in raw_skills.items():
            canonical = resolve_skill(key)
            if canonical is not None:
                skills[canonical] = bool(value)
    return skills


def _build_goals(raw_goals: object) -> tuple[Goal, ...]:
    """Reconstruct :class:`Goal` objects from a raw list of dicts.

    Fills optional fields with safe defaults; non-mapping items are dropped
    (validation already rejects them, so this is defense in depth).
    """
    if not isinstance(raw_goals, (list, tuple)):
        return ()
    goals: list[Goal] = []
    for item in raw_goals:
        if not isinstance(item, dict):
            continue
        goals.append(
            Goal(
                title=item.get("title", ""),
                description=item.get("description", ""),
                status=item.get("status", "active"),
            )
        )
    return tuple(goals)


def _build_quests(raw_quests: object) -> tuple[Quest, ...]:
    """Reconstruct :class:`Quest` objects from a raw list of dicts (see :func:`_build_goals`)."""
    if not isinstance(raw_quests, (list, tuple)):
        return ()
    quests: list[Quest] = []
    for item in raw_quests:
        if not isinstance(item, dict):
            continue
        quests.append(
            Quest(
                title=item.get("title", ""),
                description=item.get("description", ""),
                status=item.get("status", "active"),
            )
        )
    return tuple(quests)


def _validate_abilities(abilities: object, errors: list[str]) -> None:
    if abilities is None:
        errors.append("missing 'abilities'")
        return
    if not isinstance(abilities, dict):
        errors.append("'abilities' must be a mapping")
        return

    resolved: dict[str, object] = {}
    for key, value in abilities.items():
        if not isinstance(key, str):
            errors.append(f"ability key {key!r} must be a string")
            continue
        canonical = resolve_ability(key)
        if canonical is None:
            errors.append(f"unknown ability key {key!r}")
            continue
        resolved[canonical] = value

    for ability in ABILITIES:
        if ability not in resolved:
            errors.append(f"missing ability score '{ability}'")
            continue
        score = resolved[ability]
        if isinstance(score, bool) or not isinstance(score, int):
            errors.append(f"ability '{ability}' score must be an integer")
        elif not (MIN_ABILITY_SCORE <= score <= MAX_ABILITY_SCORE):
            errors.append(
                f"ability '{ability}' score {score} out of range "
                f"{MIN_ABILITY_SCORE}..{MAX_ABILITY_SCORE}"
            )


def _validate_class(character_class: object, errors: list[str]) -> None:
    if character_class is None:
        errors.append("missing 'character_class'")
        return
    if not isinstance(character_class, str):
        errors.append("'character_class' must be a string")
        return
    if not character_class.strip():
        errors.append("'character_class' must be a non-empty string")


def _validate_race(race: object, errors: list[str]) -> None:
    if race is None:
        errors.append("missing 'race'")
        return
    if not isinstance(race, str):
        errors.append("'race' must be a string")


def _validate_level(level: object, errors: list[str]) -> None:
    if level is None:
        return  # defaults to 1
    if isinstance(level, bool) or not isinstance(level, int):
        errors.append("'level' must be an integer")
        return
    if level < 1:
        errors.append(f"'level' must be a positive integer, got {level}")


def _validate_name(name: object, errors: list[str]) -> None:
    if name is not None and not isinstance(name, str):
        errors.append("'name' must be a string")


def _validate_backstory(backstory: object, errors: list[str]) -> None:
    if backstory is not None and not isinstance(backstory, str):
        errors.append("'backstory' must be a string")


def _validate_personality(personality: object, errors: list[str]) -> None:
    if personality is not None and not isinstance(personality, str):
        errors.append("'personality' must be a string")


def _validate_appearance(appearance: object, errors: list[str]) -> None:
    if appearance is not None and not isinstance(appearance, str):
        errors.append("'appearance' must be a string")


def _validate_motivation(motivation: object, errors: list[str]) -> None:
    if motivation is not None and not isinstance(motivation, str):
        errors.append("'motivation' must be a string")


def _validate_skills(skills: object, errors: list[str]) -> None:
    if skills is None:
        return
    if not isinstance(skills, dict):
        errors.append("'skills' must be a mapping")
        return
    for key, value in skills.items():
        if not isinstance(key, str) or resolve_skill(key) is None:
            errors.append(f"unknown skill {key!r}")
            continue
        if not isinstance(value, bool):
            errors.append(f"skill '{key}' proficiency must be a boolean")


def _validate_inventory(inventory: object, errors: list[str]) -> None:
    if inventory is None:
        return
    if not isinstance(inventory, (list, tuple)):
        errors.append("'inventory' must be a list of strings")
        return
    if not all(isinstance(item, str) for item in inventory):
        errors.append("'inventory' items must be strings")


def _validate_conditions(conditions: object, errors: list[str]) -> None:
    if conditions is None:
        return
    if not isinstance(conditions, (list, tuple)):
        errors.append("'conditions' must be a list of strings")
        return
    if not all(isinstance(item, str) for item in conditions):
        errors.append("'conditions' items must be strings")


def _validate_hit_die(hit_die: object, errors: list[str]) -> None:
    if hit_die is None:
        return  # defaults to DEFAULT_HIT_DIE
    if isinstance(hit_die, bool) or not isinstance(hit_die, int):
        errors.append("'hit_die' must be an integer")
        return
    if hit_die not in HIT_DIE_SIZES:
        errors.append(f"'hit_die' must be one of {HIT_DIE_SIZES}")


def _validate_class_description(class_description: object, errors: list[str]) -> None:
    if class_description is not None and not isinstance(class_description, str):
        errors.append("'class_description' must be a string")


def _validate_opening(opening: object, errors: list[str]) -> None:
    if opening is not None and not isinstance(opening, str):
        errors.append("'opening' must be a string")


def _validate_goals(goals: object, errors: list[str]) -> None:
    if goals is None:
        return
    if not isinstance(goals, (list, tuple)):
        errors.append("'goals' must be a list of objects")
        return
    for index, item in enumerate(goals):
        _validate_tracked_item("goals", index, item, errors)


def _validate_quests(quests: object, errors: list[str]) -> None:
    if quests is None:
        return
    if not isinstance(quests, (list, tuple)):
        errors.append("'quests' must be a list of objects")
        return
    for index, item in enumerate(quests):
        _validate_tracked_item("quests", index, item, errors)


def _validate_tracked_item(
    field: str, index: int, item: object, errors: list[str]
) -> None:
    """Validate one goals/quests item: title, description, status shape."""
    if not isinstance(item, dict):
        errors.append(f"'{field}' item {index} must be an object")
        return

    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append(f"'{field}' item {index} 'title' must be a non-empty string")

    description = item.get("description")
    if description is not None and not isinstance(description, str):
        errors.append(f"'{field}' item {index} 'description' must be a string")

    status = item.get("status")
    if status is None:
        return  # defaults to "active"
    if not isinstance(status, str):
        errors.append(f"'{field}' item {index} 'status' must be a string")
        return
    if status not in STATUS_VALUES:
        errors.append(f"'{field}' item {index} 'status' must be one of {STATUS_VALUES}")
