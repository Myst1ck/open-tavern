import { parseSseStream } from "../sse";
import { ApiError, LLM_TIMEOUT_MS, prepareRequest } from "./http";
import type { ActionKind, ActionResponse, RollOutcome } from "./types";

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
  kind: ActionKind = "act",
  onRolls?: (rolls: RollOutcome[]) => void,
): Promise<ActionResponse> {
  const { response, timer, signal } = await prepareRequest(
    `/sessions/${sessionId}/actions`,
    {
      method: "POST",
      body: JSON.stringify({ action, kind }),
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
    if (signal.aborted) {
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
