import { LLM_TIMEOUT_MS, request } from "./http";
import type { ActionKind, ActionResponse } from "./types";

export function sendAction(
  sessionId: string,
  action: string,
  kind: ActionKind = "act",
): Promise<ActionResponse> {
  return request<ActionResponse>(
    `/sessions/${sessionId}/actions`,
    {
      method: "POST",
      body: JSON.stringify({ action, kind }),
    },
    LLM_TIMEOUT_MS,
  );
}
