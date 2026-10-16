/**
 * Thin typed client for the Open Tavern FastAPI backend.
 *
 * Mirrors the pydantic response shapes from
 * backend/src/open_tavern/api/schemas.py. No game logic lives here —
 * every call is a direct fetch against the backend.
 */

import { parseSseStream } from "./sse";

// API calls are same-origin. When the app is served under a subpath (e.g.
// /tavern/ via tailscale serve), Vite's BASE_URL carries that prefix, so
// absolute paths like /world/generate become /tavern/world/generate.
// VITE_API_BASE_URL overrides this for split-origin deployments.
const DEFAULT_BASE_URL = import.meta.env.BASE_URL;

const API_BASE_URL = (() => {
  const raw = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_BASE_URL).replace(
    /\/+$/,
    "",
  );
  // Root serving yields "" or "/" — both mean no prefix.
  return raw === "/" ? "" : raw;
})();

const SETTINGS_KEY = "open-tavern-settings";

/** Abort in-flight fetches after this long to avoid hanging requests. */
const REQUEST_TIMEOUT_MS = 30_000;

/**
 * LLM-backed endpoints can take far longer than cheap reads; give them a
 * generous ceiling so generation is not aborted mid-flight.
 */
const LLM_TIMEOUT_MS = 120_000;

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
  if (settings.model !== "") {
    headers["X-Model"] = settings.model;
  }
  if (settings.baseUrl !== "") {
    headers["X-Base-Url"] = settings.baseUrl;
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

/** Persisted chat transcript entry (role/content, plus turn rolls if any). */
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  rolls?: RollOutcome[];
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

/**
 * Handle returned by `setTimeout`; Node and the DOM disagree on the concrete
 * type, so name the inferred one here instead of leaking `ReturnType`.
 */
type TimeoutHandle = ReturnType<typeof setTimeout>;

/**
 * Shared request preamble for both buffered and streaming calls. Sends the
 * request with the settings headers, aborts it once the total `timeoutMs`
 * budget elapses, and turns a non-OK response into an `ApiError` carrying the
 * backend's `detail` — so pre-stream failures keep today's semantics.
 *
 * The timeout timer stays armed for as long as the caller holds the returned
 * handle: buffered callers clear it after parsing the body, streaming callers
 * only after the whole stream finishes (the budget covers the entire stream,
 * not each frame). Callers MUST `clearTimeout(timer)` when done.
 */
async function prepareRequest(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<{ response: Response; timer: TimeoutHandle }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
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
    return { response, timer };
  } catch (err) {
    clearTimeout(timer);
    throw err;
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const { response, timer } = await prepareRequest(path, init, timeoutMs);
  try {
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
  return request<CharacterResponse>(
    `/sessions/${sessionId}/character`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
    LLM_TIMEOUT_MS,
  );
}

/**
 * Refine a character's prose fields (backstory, personality, appearance,
 * motivation) in one batch. Unspecified fields pass through unchanged.
 */
export function refineCharacter(
  sessionId: string,
  payload: RefinePayload,
): Promise<RefineResponse> {
  return request<RefineResponse>(
    `/sessions/${sessionId}/character/refine`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    LLM_TIMEOUT_MS,
  );
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
    LLM_TIMEOUT_MS,
  );
}

/**
 * Send a player action and consume the turn's server-sent event stream.
 *
 * The backend emits zero or more `roll` frames as the d20 checks resolve, then
 * exactly one terminal frame: `message` (the full `ActionResponse`) or `error`
 * (`{detail, status}`). `onRolls` is invoked for every `roll` frame with that
 * frame's resolved checks. The returned promise resolves with the `message`
 * payload and rejects with an `ApiError` on an `error` frame, on the total
 * timeout abort, or when the stream ends without a terminal frame. Failures
 * before the stream opens keep the same `ApiError` shape as `request()`, so
 * the caller's rollback semantics are unchanged.
 */
export async function sendAction(
  sessionId: string,
  action: string,
  onRolls?: (rolls: RollOutcome[]) => void,
): Promise<ActionResponse> {
  const { response, timer } = await prepareRequest(
    `/sessions/${sessionId}/actions`,
    {
      method: "POST",
      body: JSON.stringify({ action }),
    },
    LLM_TIMEOUT_MS,
  );

  const reader = response.body?.getReader();
  if (reader === undefined) {
    clearTimeout(timer);
    throw new ApiError(response.status, "Response body is not readable");
  }

  let payload: ActionResponse | null = null;
  let failure: ApiError | null = null;

  try {
    await parseSseStream(reader, (frame) => {
      if (frame.event === "roll") {
        try {
          const { rolls } = JSON.parse(frame.data) as { rolls: RollOutcome[] };
          onRolls?.(rolls);
        } catch {
          // A malformed roll frame only costs the animation, never the turn.
        }
        return;
      }
      try {
        if (frame.event === "message") {
          payload = JSON.parse(frame.data) as ActionResponse;
        } else if (frame.event === "error") {
          const { detail, status } = JSON.parse(frame.data) as {
            detail: string;
            status: number;
          };
          failure = new ApiError(status, detail);
        }
      } catch {
        // A terminal frame cut mid-JSON means the stream ended without a result.
        failure = new ApiError(0, "The turn stream ended without a result");
      }
    });
  } catch (err) {
    clearTimeout(timer);
    try {
      await reader.cancel();
    } catch {
      // The stream already failed; there is nothing left to release.
    }
    if (failure !== null) {
      throw failure;
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(0, "The action timed out before the turn completed");
    }
    throw err;
  }

  clearTimeout(timer);
  if (failure !== null) {
    throw failure;
  }
  if (payload === null) {
    throw new ApiError(0, "The turn stream ended without a result");
  }
  return payload;
}

export function getState(sessionId: string): Promise<StateResponse> {
  return request<StateResponse>(`/sessions/${sessionId}/state`);
}

// ── World generation API types ──────────────────────────────────

export interface WorldGenResponse {
  theme: string;
  premise: string;
}

// ── World generation API functions ──────────────────────────────

/**
 * Generate a world theme + premise from a free-text description.
 * Pass `surprise` to let the backend invent a world from no description.
 */
export function generateWorld(
  description: string,
  surprise = false,
): Promise<WorldGenResponse> {
  return request<WorldGenResponse>(
    "/world/generate",
    {
      method: "POST",
      body: JSON.stringify({ description, surprise }),
    },
    LLM_TIMEOUT_MS,
  );
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
