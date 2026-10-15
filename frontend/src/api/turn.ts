import { LLM_TIMEOUT_MS, request } from "./http";
import type { ActionResponse } from "./types";

export function sendAction(
  sessionId: string,
  action: string,
): Promise<ActionResponse> {
  return request<ActionResponse>(
    `/sessions/${sessionId}/actions`,
    {
      method: "POST",
      body: JSON.stringify({ action }),
    },
    LLM_TIMEOUT_MS,
  );
}
