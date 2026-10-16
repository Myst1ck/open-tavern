import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useRef,
  useState,
} from "react";

import { sendAction } from "./api/turn";
import type { ActionKind, GameState } from "./api/types";
import { newEntryId, type TranscriptEntry } from "./transcript";

interface TurnStreamOptions {
  /** Transcript store owned by the caller, so resume paths can replace it. */
  setEntries: Dispatch<SetStateAction<TranscriptEntry[]>>;
  setBusy: Dispatch<SetStateAction<boolean>>;
  setError: Dispatch<SetStateAction<string | null>>;
  /** Fired once a turn has fully landed (all rolls revealed + narration shown). */
  onTurnComplete: (state: GameState) => void;
}

export interface TurnStream {
  /** Roll cards already revealed in the active set (0 = only the first is up). */
  revealCount: number;
  send: (sessionId: string, action: string, kind?: ActionKind) => void;
  /** RollCard callback: a card finished its reveal animation. */
  onRollRevealed: (rollSetId: string, index: number) => void;
  /** Abandon an in-flight turn (leaving play) and drop its pending state. */
  reset: () => void;
}

interface ActiveRollSet {
  id: string;
  total: number;
  revealed: number;
}

interface BufferedMessage {
  narration: string;
  state: GameState;
}

/**
 * Drives one turn end to end: optimistic player entry, streamed roll set,
 * sequential per-card reveal, then the buffered narration. The narration frame
 * usually arrives after the roll frames (it waits on the phase-2 LLM call), but
 * a fast model can beat the ~2s-per-card animation, so the message is buffered
 * until every card has revealed.
 */
export function useTurnStream({
  setEntries,
  setBusy,
  setError,
  onTurnComplete,
}: TurnStreamOptions): TurnStream {
  const [revealCount, setRevealCount] = useState(0);
  const onTurnCompleteRef = useRef(onTurnComplete);
  onTurnCompleteRef.current = onTurnComplete;

  // Bumped to invalidate an abandoned turn's still-pending continuations.
  const epochRef = useRef(0);
  const streamingRef = useRef(false);
  const activeSetRef = useRef<ActiveRollSet | null>(null);
  const bufferedRef = useRef<BufferedMessage | null>(null);

  const clearActiveSet = useCallback(() => {
    activeSetRef.current = null;
    bufferedRef.current = null;
    streamingRef.current = false;
    setRevealCount(0);
  }, []);

  /** Append the buffered narration once every card in the set has revealed. */
  const completeTurn = useCallback(() => {
    const buffered = bufferedRef.current;
    if (buffered === null) {
      return;
    }
    const active = activeSetRef.current;
    if (active !== null && active.revealed < active.total) {
      return;
    }
    clearActiveSet();
    setEntries((prev) => [
      ...prev,
      {
        kind: "message",
        id: newEntryId(),
        role: "assistant",
        content: buffered.narration,
      },
    ]);
    setBusy(false);
    onTurnCompleteRef.current(buffered.state);
  }, [clearActiveSet, setBusy, setEntries]);

  const onRollRevealed = useCallback(
    (rollSetId: string, index: number) => {
      const active = activeSetRef.current;
      // Only the newest card can advance the set; stale or foreign cards are
      // ignored (a resumed transcript's cards also report here).
      if (
        active === null ||
        active.id !== rollSetId ||
        index !== active.revealed
      ) {
        return;
      }
      active.revealed += 1;
      setRevealCount(active.revealed);
      if (active.revealed >= active.total) {
        setEntries((prev) =>
          prev.map((entry): TranscriptEntry =>
            entry.kind === "roll-set" && entry.id === active.id
              ? { ...entry, state: "revealed" }
              : entry,
          ),
        );
        completeTurn();
      }
    },
    [completeTurn, setEntries],
  );

  const reset = useCallback(() => {
    epochRef.current += 1;
    clearActiveSet();
    setBusy(false);
  }, [clearActiveSet, setBusy]);

  const send = useCallback(
    (sessionId: string, action: string, kind: ActionKind = "act") => {
      if (streamingRef.current) {
        return;
      }
      streamingRef.current = true;
      const epoch = ++epochRef.current;
      activeSetRef.current = null;
      bufferedRef.current = null;
      setRevealCount(0);
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
            const id = newEntryId();
            activeSetRef.current = { id, total: rolls.length, revealed: 0 };
            setRevealCount(0);
            setEntries((prev) => [
              ...prev,
              { kind: "roll-set", id, rolls, state: "pending" },
            ]);
          });
          if (epoch !== epochRef.current) {
            return;
          }
          bufferedRef.current = {
            narration: response.narration,
            state: response.state,
          };
          completeTurn();
        } catch (err) {
          if (epoch !== epochRef.current) {
            return;
          }
          // Roll back the optimistic player entry and any unshown roll set so
          // a failed turn leaves no dangling transcript entry.
          clearActiveSet();
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
    [clearActiveSet, completeTurn, setBusy, setEntries, setError],
  );

  return { revealCount, send, onRollRevealed, reset };
}
