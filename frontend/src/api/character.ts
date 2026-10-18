import { LLM_TIMEOUT_MS, request } from "./http";
import type {
  CharacterCreationPayload,
  CharacterResponse,
  ClassDefinition,
  RefinePayload,
  RefineResponse,
} from "./types";

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
