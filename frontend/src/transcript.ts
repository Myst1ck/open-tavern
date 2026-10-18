import type { ActionKind, RollOutcome } from "./api/types";

/**
 * One entry in the play transcript: a narration line or a resolved d20 roll
 * set. Roll sets are first-class entries (not part of the narration message) so
 * the live turn can insert them between the player action and the narration as
 * the backend streams results.
 */
export type TranscriptEntry =
  | {
      kind: "message";
      id: string;
      role: "user" | "assistant";
      content: string;
      /**
       * How the player framed the turn (`say`/`act`/`continue`), for the action
       * bubble styling and the text-free "continue" placeholder. Absent on
       * narration and on transcript entries restored from persisted history.
       */
      actionKind?: ActionKind;
    }
  | {
      kind: "roll-set";
      id: string;
      rolls: RollOutcome[];
      state: "pending" | "revealed";
    };

/** A roll-set entry (narrowed alias for consumers that render rolls). */
export type RollSetEntry = Extract<TranscriptEntry, { kind: "roll-set" }>;

/** Stable id for a transcript entry; UUID when available, else a counter-ish. */
export function newEntryId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}
