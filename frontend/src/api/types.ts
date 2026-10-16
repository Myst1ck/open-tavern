/**
 * Backend request/response shapes, mirrored from
 * backend/src/open_tavern/api/schemas.py. Types only — no runtime code.
 */

// ── DM narration style ─────────────────────────────────────────

/** Preset tone key; mirrors the backend's `TONES` registry. */
export type Tone = "classic" | "gritty" | "heroic" | "whimsical" | "comedic";

/** Preset verbosity key; mirrors the backend's `VERBOSITIES` registry. */
export type Verbosity = "standard" | "concise" | "rich";

export interface DmStyle {
  tone: Tone;
  verbosity: Verbosity;
  custom_tone: string;
}

export interface Session {
  session_id: string;
  world_theme: string;
  dm_style: DmStyle | null;
}

export interface SessionSummary {
  id: string;
  title: string;
  world_theme: string;
  created_at: string;
  updated_at: string;
  character_name: string | null;
}

/** Persisted chat transcript entry (role/content only, no UI state). */
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface SessionDetail {
  meta: SessionSummary;
  state: GameState | null;
  character: CharacterSheet | null;
  messages: ChatMessage[];
  dm_style: DmStyle | null;
}

export interface AbilityScores {
  strength: number;
  dexterity: number;
  constitution: number;
  intelligence: number;
  wisdom: number;
  charisma: number;
}

export type GoalStatus = "active" | "complete" | "failed";

export type BaseType =
  "weapon" | "armor" | "consumable" | "quest" | "loot" | "key";

export interface ItemStats {
  damage: number;
  armor: number;
  value: number;
  weight: number;
  extra: Record<string, unknown>;
}

export interface Item {
  id: string;
  name: string;
  type: BaseType;
  tags: string[];
  stats: ItemStats;
  description: string;
  equipped: boolean;
  quantity: number;
}

export interface Goal {
  title: string;
  description: string;
  status: GoalStatus;
}

export interface Quest {
  title: string;
  description: string;
  status: GoalStatus;
}

export interface ClassDefinition {
  name: string;
  description: string;
  hit_die: number;
}

export interface CharacterSheet {
  name: string;
  race: string;
  character_class: string;
  level: number;
  abilities: AbilityScores;
  /** Canonical skill name -> proficiency flag. */
  skills: Record<string, boolean>;
  hp: number;
  max_hp: number;
  proficiency_bonus: number;
  inventory: Item[];
  conditions: string[];
  backstory: string;
  personality?: string;
  appearance?: string;
  motivation?: string;
  hit_die?: number;
  class_description?: string;
  goals?: Goal[];
  quests?: Quest[];
  opening?: string;
}

export interface RollOutcome {
  name: string;
  dc: number;
  modifier: number;
  d20: number;
  total: number;
  success: boolean;
  crit_success: boolean;
  crit_fail: boolean;
}

export interface GameState {
  current_hp: number;
  max_hp: number;
  conditions: string[];
  scene: string;
  character: CharacterSheet;
}

export interface CharacterResponse {
  character: CharacterSheet;
  opening: string;
}

export interface StateResponse {
  state: GameState;
}

export interface ActionResponse {
  narration: string;
  state: GameState;
  rolls: RollOutcome[];
}

/** How a player action is framed: in-character speech, declared action, or a
 * text-free scene continuation. Mirrors the backend `ActionRequest.kind`. */
export type ActionKind = "say" | "act" | "continue";

/**
 * Structured character-creation payload. All fields optional — a caller may
 * supply the new structured fields, the legacy free-text `description`, or both.
 */
export interface CharacterCreationPayload {
  name?: string;
  race?: string;
  class_concept?: string;
  class_name?: string;
  class_hit_die?: number;
  class_description?: string;
  backstory?: string;
  personality?: string;
  appearance?: string;
  motivation?: string;
  /** Legacy free-text description, still supported. */
  description?: string;
}

/**
 * Structured character-refine payload. All prose fields optional —
 * unspecified fields pass through unchanged on the backend.
 */
export interface RefinePayload {
  backstory?: string;
  personality?: string;
  appearance?: string;
  motivation?: string;
}

/** Response carrying post-refine prose values. */
export interface RefineResponse {
  backstory: string;
  personality: string;
  appearance: string;
  motivation: string;
}

// ── World generation API types ──────────────────────────────────

export interface WorldGenResponse {
  theme: string;
  premise: string;
}

// ── Item API types ──────────────────────────────────────────────

export interface ItemActionResponse {
  success: boolean;
  item: Item | null;
  message: string;
}
