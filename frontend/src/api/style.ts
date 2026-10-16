import type { DmStyle, Tone, Verbosity } from "./types";

/**
 * DM narration style choices, mirroring the backend's `TONES` and
 * `VERBOSITIES` registries. Runtime constants live here (types.ts stays
 * types-only).
 */

export const TONE_OPTIONS: ReadonlyArray<{ value: Tone; label: string }> = [
  { value: "classic", label: "Classic" },
  { value: "gritty", label: "Gritty" },
  { value: "heroic", label: "Heroic" },
  { value: "whimsical", label: "Whimsical" },
  { value: "comedic", label: "Comedic" },
];

export const VERBOSITY_OPTIONS: ReadonlyArray<{
  value: Verbosity;
  label: string;
}> = [
  { value: "standard", label: "Standard" },
  { value: "concise", label: "Concise" },
  { value: "rich", label: "Rich" },
];

/** Untouched default: the backend renders the classic prompt for this. */
export const DEFAULT_DM_STYLE: DmStyle = {
  tone: "classic",
  verbosity: "standard",
  custom_tone: "",
};
