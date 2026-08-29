<!-- Context: project-intelligence/business | Priority: critical | Version: 1.0 | Updated: 2026-08-28 -->

# Business Domain

**Purpose**: Game rules, D&D 5e character model, and GM turn flow for Open Tavern.
**Last Updated**: 2026-08-28

## Quick Reference
**Update Triggers**: New game mechanics | Tag protocol change | Character model change
**Audience**: Developers, AI agents

## Core Concept
Open Tavern is an open-source AI text RPG. The AI is the GM/narrator only — a deterministic Python engine owns ALL dice, hit points, inventory, and conditions. The AI never does math or state; it narrates and emits instruction tags the engine applies.

## Key Rules
1. **Engine owns the world** — AI output is untrusted; engine parses/validates/applies every mechanic.
2. **Tag protocol is the wire format** — GM embeds `[TAG:payload]` in narration; engine strips tags and applies typed actions.
3. **D&D 5e model** — abilities, 18 skills, proficiency, hit dice drive all resolution.
4. **Defensive parsing** — malformed tags silently dropped, unrecognized `[x:y]` left as prose, parser never raises.
5. **Two-phase turn** — GM narrates → engine resolves rolls → result fed back → GM continues.

## GM Tag Protocol
| Tag                                 | Grammar                | Effect                |
| ----------------------------------- | ---------------------- | --------------------- |
| `[CHECK:name DC<int>]`              | ability or skill check | d20 + modifier vs DC  |
| `[DAMAGE:2d6+3]`                    | dice expression        | roll + subtract HP    |
| `[ITEM:+sword]` / `[ITEM:-sword]`   | signed item            | add/remove inventory  |
| `[HP:+5]` / `[HP:-3]`               | signed int             | change hit points     |
| `[CONDITION:+poisoned]` / `-poisoned` | signed name          | apply/clear condition |

Example narration:
```
You swing at the goblin. [CHECK:strength DC15] [DAMAGE:1d8+3]
```

## Dice & Check Rules
- Die sizes: `{4, 6, 8, 10, 12, 20, 100}`.
- Check: `total = d20 + modifier`; success = `total >= dc`.
- Crit success = natural 20; crit fail = natural 1 (regardless of modifier).
- Advantage = roll 2d20 keep high; disadvantage = keep low.
- Damage rolls: `roll_expression("2d6+3")`.

## Character Model (D&D 5e)
- 6 abilities: `STR DEX CON INT WIS CHA`.
- 18 skills mapped to governing ability (e.g. `Athletics→STR`, `Perception→WIS`).
- `ability_modifier = (score - 10) // 2`.
- `proficiency_bonus = 2 + (level - 1) // 4`.
- Skill mod = ability mod + proficiency (if proficient).
- Classes + hit die: fighter 10, wizard 6, rogue 8, cleric 8, barbarian 12, ranger 10.
- Max HP: level 1 = full hit die + CON mod; later = `hit_die//2 + 1` + CON mod.
- Derived values computed by code — never trusted from AI input.

## Turn Flow
1. Player action → `user_action_prompt`.
2. GM narrates with embedded tags.
3. Engine `parse()` → `ParsedTurn` (clean narration + ordered actions).
4. Engine applies actions (checks, damage, items, HP, conditions).
5. `roll_result_prompt` feeds resolved outcomes back to GM.
6. GM continues narration → repeat.

## Character Generation
- Player gives free-text description → AI emits JSON sheet.
- Engine parses defensively, `validate()` + `normalize()`, computes derived values.

## 📂 Codebase References
**Tag parser**: `backend/src/open_tavern/protocol/parser.py` — `parse()`, `ParsedTurn`, action dataclasses.
**Dice engine**: `backend/src/open_tavern/dice/dice.py` — `check()`, `roll_expression()`, `advantage()`, `CheckResult`.
**Character model**: `backend/src/open_tavern/character/models.py` — `CharacterSheet`, `SKILL_ABILITIES`, `proficiency_bonus()`, `max_hp_for()`.
**Story engine**: `backend/src/open_tavern/story/` — `turn()`, `generate_character()`, prompts.
**Frontend sheet**: `frontend/src/components/CharacterSheet.tsx` — mirrors model.
**Docs**: `README.md` (architecture), `SETUP.md` (bring-up).

## Related Files
- Technical Domain (`technical-domain.md`) — stack & code patterns.
- Decisions Log (`decisions-log.md`) — architecture decisions.
