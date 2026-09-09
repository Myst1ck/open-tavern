/**
 * Corrupt-tolerant localStorage helper for character creation wizard draft
 * values. Mirrors the load/save pattern from api.ts.
 */

export const CHAR_DRAFT_KEY = "open-tavern-char-draft";

/** Read draft from localStorage, tolerating missing/corrupt values. */
export function loadCharDraft(): Record<string, string> {
  try {
    const raw = localStorage.getItem(CHAR_DRAFT_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      const draft: Record<string, string> = {};
      for (const [key, value] of Object.entries(parsed)) {
        if (typeof value === "string") {
          draft[key] = value;
        }
      }
      return draft;
    }
  } catch {
    // Corrupt draft falls through to empty object.
  }
  return {};
}

/** Persist draft to localStorage, trimming all string values. */
export function saveCharDraft(draft: Record<string, string>): void {
  const trimmed: Record<string, string> = {};
  for (const [key, value] of Object.entries(draft)) {
    trimmed[key] = value.trim();
  }
  try {
    localStorage.setItem(CHAR_DRAFT_KEY, JSON.stringify(trimmed));
  } catch {
    // Draft is convenience data; ignore quota/private-mode failures.
  }
}

/** Remove the draft from localStorage. */
export function clearCharDraft(): void {
  localStorage.removeItem(CHAR_DRAFT_KEY);
}
