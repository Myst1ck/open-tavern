import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useRef,
} from "react";

import { sendAction } from "./api/turn";
import type { ActionKind, GameState } from "./api/types";
import { newEntryId, type TranscriptEntry } from "./transcript";

interface TurnStreamOptions {
  /** Transcript store owned by the caller, so resume paths can replace it. */
  setEntries: Dispatch<SetStateAction<TranscriptEntry[]>>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  /** Fired once the narration has landed and the turn is over on the wire. */
  onTurnComplete: (state: GameState) => void;
}

export interface TurnStream {
  send: (sessionId: string, action: string, kind?: ActionKind) => void;
  /** Abandon an in-flight turn (leaving play) and drop its pending state. */
  reset: () => void;
}

/**
 * Drives one player turn end to end: optimistic player entry, streamed roll
 * set, and the narration the instant it lands.
 *
 * The dice never gate the response: the engine resolves rolls before the
 * narration call is issued, so by the time a `roll` frame arrives the result is
 * already known and the LLM call is already in flight. Roll cards animate as
 * loading decoration only — a message that beats the animation is shown
 * immediately. A set that is still marked pending when its message arrives is
 * settled to "revealed" in the same update, so a later failed turn's rollback
 * can never strip a completed turn's rolls.
 */
export function useTurnStream({
  setEntries,
  setBusy,
  setError,
  onTurnComplete,
}: TurnStreamOptions): TurnStream {
  const onTurnCompleteRef = useRef(onTurnComplete);
  onTurnCompleteRef.current = onTurnComplete;

  // Bumped to invalidate an abandoned turn's still-pending continuations.
  const epochRef = useRef(0);
  const streamingRef = useRef(false);

  const reset = useCallback(() => {
    epochRef.current += 1;
    streamingRef.current = false;
    setBusy(false);
  }, [setBusy]);

  const send = useCallback(
    (sessionId: string, action: string, kind: ActionKind = "act") => {
      if (streamingRef.current) {
        return;
      }
      streamingRef.current = true;
      const epoch = ++epochRef.current;
      setBusy(true);
      setError(null);
      const playerId = newEntryId();
      setEntries((prev) => [
        ...prev,
        {
          kind: "message",
          id: playerId,
          role: "user",
          content: action,
          actionKind: kind,
        },
      ]);

      void (async () => {
        try {
          const response = await sendAction(sessionId, action, kind, (rolls) => {
            if (epoch !== epochRef.current || rolls.length === 0) {
              return;
            }
            setEntries((prev) => [
              ...prev,
              {
                kind: "roll-set",
                id: newEntryId(),
                rolls,
                state: "pending",
              },
            ]);
          });
          if (epoch !== epochRef.current) {
            return;
          }
          // Land the narration immediately; settle any still-pending roll set
          // in the same update so error rollback cannot touch it later.
          setEntries((prev) => [
            ...prev.map((entry): TranscriptEntry =>
              entry.kind === "roll-set" && entry.state === "pending"
                ? { ...entry, state: "revealed" }
                : entry,
            ),
            {
              kind: "message",
              id: newEntryId(),
              role: "assistant",
              content: response.narration,
            },
          ]);
          streamingRef.current = false;
          setBusy(false);
          onTurnCompleteRef.current(response.state);
        } catch (err) {
          if (epoch !== epochRef.current) {
            return;
          }
          // Roll back the optimistic player entry and any unshown roll set so
          // a failed turn leaves no dangling transcript entry.
          streamingRef.current = false;
          setEntries((prev) =>
            prev.filter((entry) =>
              entry.kind === "message"
                ? entry.id !== playerId
                : entry.state !== "pending",
            ),
          );
          setError(err instanceof Error ? err.message : String(err));
          setBusy(false);
        }
      })();
    },
    [setBusy, setEntries, setError],
  );

  return { send, reset };
}
