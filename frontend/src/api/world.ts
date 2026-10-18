import { LLM_TIMEOUT_MS, request } from "./http";
import type { WorldGenResponse } from "./types";

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
