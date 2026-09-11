/**
 * Thin typed client for the Open Tavern FastAPI backend.
 *
 * Mirrors the pydantic response shapes from
 * backend/src/open_tavern/api/schemas.py. No game logic lives here —
 * every call is a direct fetch against the backend.
 */

const DEFAULT_BASE_URL = `${window.location.protocol}//${window.location.hostname}:8000`;

const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL
).replace(/\/+$/, "");

const SETTINGS_KEY = "open-tavern-settings";

/** Abort in-flight fetches after this long to avoid hanging requests. */
const REQUEST_TIMEOUT_MS = 30_000;

export interface TavernSettings {
  apiKey: string;
  baseUrl: string;
  model: string;
}

/**
 * Read settings from localStorage, tolerating missing/corrupt values.
 *
 * SECURITY NOTE: the API key is persisted in plaintext in localStorage.
 * Any script running on this origin (or an XSS payload) can read it, and it
 * survives in the browser profile after logout. SettingsPanel should warn
 * users of this exposure; do not treat the stored key as a secret at rest.
 */
export function loadSettings(): TavernSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw) as Partial<TavernSettings>;
      return {
        apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : "",
        baseUrl: typeof parsed.baseUrl === "string" ? parsed.baseUrl : "",
        model: typeof parsed.model === "string" ? parsed.model : "",
      };
    }
  } catch {
    // Corrupt settings fall through to defaults.
  }
  return { apiKey: "", baseUrl: "", model: "" };
}

/** Persist settings to localStorage. */
export function saveSettings(settings: TavernSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  cachedSettings = { ...settings };
}

/**
 * Module-level cache of the parsed localStorage settings, refreshed on save.
 * Avoids re-reading and re-parsing localStorage on every API request.
 */
let cachedSettings: TavernSettings = loadSettings();

function settingsHeaders(settings: TavernSettings): Record<string, string> {
  const headers: Record<string, string> = {};
  if (settings.apiKey !== "") {
    headers["X-API-Key"] = settings.apiKey;
  }
  if (settings.baseUrl !== "") {
    headers["X-Base-URL"] = settings.baseUrl;
  }
  if (settings.model !== "") {
    headers["X-Model"] = settings.model;
  }
  return headers;
}

export interface Session {
  session_id: string;
  world_theme: string;
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

/** Alias for chat-message payloads sent to the backend. */
export type Message = ChatMessage;

export interface SessionDetail {
  meta: SessionSummary;
  state: GameState | null;
  character: CharacterSheet | null;
  messages: ChatMessage[];
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

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...settingsHeaders(cachedSettings),
      },
    });
    if (!response.ok) {
      throw new ApiError(response.status, await errorDetail(response));
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Non-JSON error body; fall through to the status text.
  }
  return response.statusText;
}

export function createSession(
  worldTheme: string,
  title?: string,
  premise?: string,
): Promise<Session> {
  return request<Session>("/sessions", {
    method: "POST",
    body: JSON.stringify({
      world_theme: worldTheme,
      ...(title !== undefined ? { title } : {}),
      ...(premise !== undefined ? { premise } : {}),
    }),
  });
}

export function listSessions(): Promise<SessionSummary[]> {
  return request<SessionSummary[]>("/sessions");
}

export function getSession(id: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/sessions/${id}`);
}

export function getMessages(id: string): Promise<ChatMessage[]> {
  return request<ChatMessage[]>(`/sessions/${id}/messages`);
}

export function renameSession(
  id: string,
  title: string,
): Promise<SessionSummary> {
  return request<SessionSummary>(`/sessions/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteSession(id: string): Promise<void> {
  return request<void>(`/sessions/${id}`, { method: "DELETE" });
}

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

/**
 * Create a character from a structured payload.
 *
 * Backward-compatible overload: passing a plain string behaves exactly like
 * the legacy `createCharacter(sessionId, description)` call.
 */
export function createCharacter(
  sessionId: string,
  description: string,
): Promise<CharacterResponse>;
export function createCharacter(
  sessionId: string,
  payload: CharacterCreationPayload,
): Promise<CharacterResponse>;
export function createCharacter(
  sessionId: string,
  payloadOrDescription: string | CharacterCreationPayload,
): Promise<CharacterResponse> {
  const body =
    typeof payloadOrDescription === "string"
      ? { description: payloadOrDescription }
      : payloadOrDescription;
  return request<CharacterResponse>(`/sessions/${sessionId}/character`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * Refine a character's prose fields (backstory, personality, appearance,
 * motivation) in one batch. Unspecified fields pass through unchanged.
 */
export function refineCharacter(
  sessionId: string,
  payload: RefinePayload,
): Promise<RefineResponse> {
  return request<RefineResponse>(`/sessions/${sessionId}/character/refine`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Generate a class definition from a free-text class concept.
 */
export function generateClass(
  sessionId: string,
  classConcept: string,
): Promise<{ class_definition: ClassDefinition }> {
  return request<{ class_definition: ClassDefinition }>(
    `/sessions/${sessionId}/character/class`,
    {
      method: "POST",
      body: JSON.stringify({ class_concept: classConcept }),
    },
  );
}

export function sendAction(
  sessionId: string,
  action: string,
): Promise<ActionResponse> {
  return request<ActionResponse>(`/sessions/${sessionId}/actions`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export function getState(sessionId: string): Promise<StateResponse> {
  return request<StateResponse>(`/sessions/${sessionId}/state`);
}

// ── Brainstorm API types ────────────────────────────────────────

export interface BrainstormResponse {
  theme: string;
  premise: string;
}

// ── Brainstorm API functions ────────────────────────────────────

/**
 * Generate a conversational theme + premise from a chat transcript.
 */
export function brainstorm(messages: Message[]): Promise<BrainstormResponse> {
  return request<BrainstormResponse>("/brainstorm", {
    method: "POST",
    body: JSON.stringify({ messages }),
  });
}

// ── Item API types ──────────────────────────────────────────────

export type ItemResponse = Item;

export interface ItemListResponse {
  items: Item[];
}

export interface ItemActionResponse {
  success: boolean;
  item: Item | null;
  message: string;
}

export interface CreateItemRequest {
  name: string;
  type?: BaseType;
  stats?: Partial<ItemStats>;
  tags?: string[];
  description?: string;
}

// ── Item API functions ───────────────────────────────────────────

export function createItem(
  sessionId: string,
  characterId: string,
  data: CreateItemRequest,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items`,
    { method: "POST", body: JSON.stringify(data) },
  );
}

export function listItems(
  sessionId: string,
  characterId: string,
): Promise<ItemListResponse> {
  return request<ItemListResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items`,
  );
}

export function getItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemResponse> {
  return request<ItemResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}`,
  );
}

export function deleteItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}`,
    { method: "DELETE" },
  );
}

export function equipItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}/equip`,
    { method: "POST" },
  );
}

export function unequipItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}/unequip`,
    { method: "POST" },
  );
}

export function useItem(
  sessionId: string,
  characterId: string,
  itemId: string,
): Promise<ItemActionResponse> {
  return request<ItemActionResponse>(
    `/sessions/${sessionId}/characters/${characterId}/items/${itemId}/use`,
    { method: "POST" },
  );
}
