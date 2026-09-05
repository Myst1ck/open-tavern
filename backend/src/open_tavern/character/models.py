"""D&D 5e character sheet models.

Pure data structures and derived-value math for a player character. Every
derived value (ability modifiers, proficiency bonus, hit points) is computed
by code from raw scores/level — never trusted from input.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from open_tavern.character.items import Item
from open_tavern.dice.dice import CheckResult, check

#: The six ability scores, in canonical abbreviated form.
ABILITIES: tuple[str, ...] = ("STR", "DEX", "CON", "INT", "WIS", "CHA")

#: Maps a canonical ability abbreviation to its ``AbilityScores`` field name.
_ABILITY_FIELDS: dict[str, str] = {
    "STR": "strength",
    "DEX": "dexterity",
    "CON": "constitution",
    "INT": "intelligence",
    "WIS": "wisdom",
    "CHA": "charisma",
}

#: Full-name aliases that resolve to a canonical ability abbreviation.
_ABILITY_ALIASES: dict[str, str] = {
    "STRENGTH": "STR",
    "DEXTERITY": "DEX",
    "CONSTITUTION": "CON",
    "INTELLIGENCE": "INT",
    "WISDOM": "WIS",
    "CHARISMA": "CHA",
}

#: Standard 5e skill list mapped to the governing ability.
SKILL_ABILITIES: dict[str, str] = {
    "Acrobatics": "DEX",
    "Animal Handling": "WIS",
    "Arcana": "INT",
    "Athletics": "STR",
    "Deception": "CHA",
    "History": "INT",
    "Insight": "WIS",
    "Intimidation": "CHA",
    "Investigation": "INT",
    "Medicine": "WIS",
    "Nature": "INT",
    "Perception": "WIS",
    "Performance": "CHA",
    "Persuasion": "CHA",
    "Religion": "INT",
    "Sleight of Hand": "DEX",
    "Stealth": "DEX",
    "Survival": "WIS",
}

#: All known skills, in canonical form.
SKILLS: tuple[str, ...] = tuple(SKILL_ABILITIES)

#: Case-insensitive lookup from any skill spelling to its canonical name.
_SKILL_LOOKUP: dict[str, str] = {skill.lower(): skill for skill in SKILLS}

#: Allowed hit die sizes for a character class.
HIT_DIE_SIZES: tuple[int, ...] = (6, 8, 10, 12)

#: Valid status values for goals and quests.
STATUS_VALUES: tuple[str, ...] = ("active", "complete", "failed")


def resolve_ability(name: str) -> str | None:
    """Return the canonical ability abbreviation for ``name``, or ``None``.

    Accepts abbreviations (``"STR"``) and full names (``"strength"``),
    case-insensitively.
    """
    key = name.strip().upper()
    if key in _ABILITY_FIELDS:
        return key
    return _ABILITY_ALIASES.get(key)


def resolve_skill(name: str) -> str | None:
    """Return the canonical skill name for ``name`` (case-insensitive), or ``None``."""
    return _SKILL_LOOKUP.get(name.strip().lower())


@dataclass(frozen=True)
class AbilityScores:
    """Frozen container for the six raw ability scores."""

    strength: int
    dexterity: int
    constitution: int
    intelligence: int
    wisdom: int
    charisma: int

    def get(self, ability: str) -> int:
        """Return the raw score for ``ability`` (abbreviation or full name)."""
        canonical = resolve_ability(ability)
        if canonical is None:
            raise ValueError(f"Unknown ability: {ability!r}")
        return getattr(self, _ABILITY_FIELDS[canonical])


def ability_modifier(score: int) -> int:
    """D&D ability modifier for a raw score: floor((score - 10) / 2)."""
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    """D&D proficiency bonus for a character level: ``2 + (level - 1) // 4``."""
    return 2 + (level - 1) // 4


def max_hp_for(hit_die: int, level: int, con_score: int) -> int:
    """Maximum hit points for a hit-die size/level given a CON score.

    Level 1 grants the full hit die plus the CON modifier. Each later level
    adds the fixed average hit-die roll (rounded up) plus the CON modifier.
    """
    con_mod = ability_modifier(con_score)
    average_roll = hit_die // 2 + 1
    return hit_die + con_mod + (level - 1) * (average_roll + con_mod)


@dataclass(frozen=True)
class Goal:
    """A character goal. Status is one of :data:`STATUS_VALUES`."""

    title: str
    description: str = ""
    status: str = "active"


@dataclass(frozen=True)
class Quest:
    """A character quest. Status is one of :data:`STATUS_VALUES`."""

    title: str
    description: str = ""
    status: str = "active"


@dataclass(frozen=True)
class CharacterSheet:
    """Immutable D&D 5e character sheet with code-computed derived values."""

    race: str
    character_class: str
    level: int
    abilities: AbilityScores
    skills: dict[str, bool]
    hp: int
    max_hp: int
    proficiency_bonus: int
    name: str = ""
    inventory: tuple[Item, ...] = ()
    conditions: tuple[str, ...] = ()
    backstory: str = ""
    personality: str = ""
    appearance: str = ""
    motivation: str = ""
    hit_die: int = 8
    class_description: str = ""
    goals: tuple[Goal, ...] = ()
    quests: tuple[Quest, ...] = ()
    opening: str = ""

    def ability_modifier(self, name: str) -> int:
        """Ability modifier for ``name`` (e.g. ``"STR"``)."""
        return ability_modifier(self.abilities.get(name))

    def skill_modifier(self, skill: str) -> int:
        """Total modifier for ``skill``: ability mod + proficiency bonus if proficient."""
        canonical = resolve_skill(skill)
        if canonical is None:
            raise ValueError(f"Unknown skill: {skill!r}")
        total = self.ability_modifier(SKILL_ABILITIES[canonical])
        if self.skills.get(canonical, False):
            total += self.proficiency_bonus
        return total

    def roll_check(
        self, skill: str, dc: int, rng: random.Random | None = None
    ) -> CheckResult:
        """Resolve a d20 skill check against ``dc`` using the derived modifier."""
        return check(self.skill_modifier(skill), dc, rng=rng)
