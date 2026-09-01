import type { AbilityScores, CharacterSheet, Goal, GoalStatus } from "../api";

const ABILITY_LABELS: Array<{ short: string; key: keyof AbilityScores }> = [
  { short: "STR", key: "strength" },
  { short: "DEX", key: "dexterity" },
  { short: "CON", key: "constitution" },
  { short: "INT", key: "intelligence" },
  { short: "WIS", key: "wisdom" },
  { short: "CHA", key: "charisma" },
];

/** Canonical 5e skill -> governing ability, mirroring the backend model. */
const SKILL_ABILITIES: Record<string, keyof AbilityScores> = {
  Acrobatics: "dexterity",
  "Animal Handling": "wisdom",
  Arcana: "intelligence",
  Athletics: "strength",
  Deception: "charisma",
  History: "intelligence",
  Insight: "wisdom",
  Intimidation: "charisma",
  Investigation: "intelligence",
  Medicine: "wisdom",
  Nature: "intelligence",
  Perception: "wisdom",
  Performance: "charisma",
  Persuasion: "charisma",
  Religion: "intelligence",
  "Sleight of Hand": "dexterity",
  Stealth: "dexterity",
  Survival: "wisdom",
};

function abilityModifier(score: number): number {
  return Math.floor((score - 10) / 2);
}

function formatModifier(value: number): string {
  return value >= 0 ? `+${value}` : String(value);
}

/** Coerce a possibly-missing ability score to a safe default (0). */
function safeScore(score: number | undefined): number {
  return typeof score === "number" ? score : 0;
}

interface CharacterSheetProps {
  character: CharacterSheet;
}

export default function CharacterSheetView({ character }: CharacterSheetProps) {
  const personality = character.personality?.trim() ?? "";
  const appearance = character.appearance?.trim() ?? "";
  const motivation = character.motivation?.trim() ?? "";
  const hasPersona =
    personality !== "" || appearance !== "" || motivation !== "";
  const backstory = character.backstory?.trim() ?? "";
  return (
    <section className="panel sheet-panel">
      <header className="sheet-header">
        <h2>{character.name}</h2>
        <p className="muted">
          {character.race} · {character.character_class} · Level{" "}
          {character.level}
        </p>
      </header>
      {personality !== "" && (
        <div className="sheet-persona-block">
          <h3>Personality</h3>
          <p className="sheet-persona">{personality}</p>
        </div>
      )}
      {appearance !== "" && (
        <div className="sheet-persona-block">
          <h3>Appearance</h3>
          <p className="sheet-persona">{appearance}</p>
        </div>
      )}
      {motivation !== "" && (
        <div className="sheet-persona-block">
          <h3>Motivation</h3>
          <p className="sheet-persona">{motivation}</p>
        </div>
      )}
      {!hasPersona && backstory !== "" && (
        <p className="sheet-backstory">{backstory}</p>
      )}
      <div className="sheet-stats">
        <span>
          HP {character.hp}/{character.max_hp}
        </span>
        <span>Proficiency +{character.proficiency_bonus}</span>
      </div>
      <h3>Abilities</h3>
      <ul className="ability-grid">
        {ABILITY_LABELS.map(({ short, key }) => (
          <li key={short}>
            <span className="ability-short">{short}</span>
            <span className="ability-score">
              {safeScore(character.abilities[key])}
            </span>
            <span className="ability-mod">
              {formatModifier(
                abilityModifier(safeScore(character.abilities[key])),
              )}
            </span>
          </li>
        ))}
      </ul>
      <h3>Skills</h3>
      <ul className="skill-list">
        {Object.entries(character.skills).map(([skill, proficient]) => {
          const abilityKey = SKILL_ABILITIES[skill] ?? "strength";
          const total =
            abilityModifier(safeScore(character.abilities[abilityKey])) +
            (proficient ? character.proficiency_bonus : 0);
          return (
            <li key={skill}>
              <span className="skill-name">{skill}</span>
              <span className={proficient ? "skill-tag trained" : "skill-tag"}>
                {proficient ? "trained" : "untrained"}
              </span>
              <span className="skill-mod">{formatModifier(total)}</span>
            </li>
          );
        })}
      </ul>
      <ItemList title="Inventory" items={character.inventory} />
      <ItemList title="Conditions" items={character.conditions} />
      <GoalList title="Goals" items={character.goals} />
      <GoalList title="Quests" items={character.quests} />
    </section>
  );
}

function ItemList({ title, items }: { title: string; items: string[] }) {
  return (
    <>
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul className="chip-list">
          {items.map((item, index) => (
            <li key={`${item}-${index}`} className="chip">
              {item}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

const STATUS_META: Record<string, { label: string; className: string }> = {
  active: { label: "Active", className: "status-tag active" },
  complete: { label: "Complete", className: "status-tag complete" },
  failed: { label: "Failed", className: "status-tag failed" },
};

/**
 * Map a goal/quest status to badge text + style. Unknown or missing statuses
 * fall back to a neutral badge so legacy/malformed data still renders.
 */
function statusMeta(status: GoalStatus | undefined): {
  label: string;
  className: string;
} {
  const meta = status !== undefined ? STATUS_META[status] : undefined;
  return meta ?? { label: status ?? "Unknown", className: "status-tag" };
}

/**
 * Shared renderer for Goals and Quests. Items are structurally identical
 * ({ title, description, status }), so one component serves both sections.
 */
function GoalList({
  title,
  items,
}: {
  title: string;
  items: Goal[] | undefined;
}) {
  return (
    <>
      <h3>{title}</h3>
      {items === undefined || items.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul className="goal-list">
          {items.map((goal, index) => {
            const meta = statusMeta(goal?.status);
            return (
              <li key={`${goal?.title ?? ""}-${index}`} className="goal-entry">
                <span className="goal-title">{goal?.title ?? "Untitled"}</span>
                <span className={meta.className}>{meta.label}</span>
                {goal?.description ? (
                  <p className="goal-description">{goal.description}</p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
