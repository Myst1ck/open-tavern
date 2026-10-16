import { useState } from "react";

import { updateSessionStyle } from "../api/sessions";
import { TONE_OPTIONS, VERBOSITY_OPTIONS } from "../api/style";
import type { DmStyle, Tone, Verbosity } from "../api/types";

export interface DmStyleFieldsProps {
  value: DmStyle;
  onChange: (next: DmStyle) => void;
  disabled?: boolean;
}

/** Shared tone/verbosity/note controls for the panel and world generation. */
export function DmStyleFields({
  value,
  onChange,
  disabled = false,
}: DmStyleFieldsProps) {
  return (
    <>
      <label htmlFor="dm-tone">Tone</label>
      <select
        id="dm-tone"
        value={value.tone}
        disabled={disabled}
        onChange={(event) =>
          onChange({ ...value, tone: event.target.value as Tone })
        }
      >
        {TONE_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      <label htmlFor="dm-verbosity">Verbosity</label>
      <select
        id="dm-verbosity"
        value={value.verbosity}
        disabled={disabled}
        onChange={(event) =>
          onChange({ ...value, verbosity: event.target.value as Verbosity })
        }
      >
        {VERBOSITY_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>

      <label htmlFor="dm-custom-tone">Custom note</label>
      <textarea
        id="dm-custom-tone"
        value={value.custom_tone}
        onChange={(event) =>
          onChange({ ...value, custom_tone: event.target.value })
        }
        placeholder="Anything special — e.g. speak like a sea dog."
        maxLength={1000}
        rows={3}
        disabled={disabled}
      />
    </>
  );
}

export interface DmStylePanelProps {
  sessionId: string;
  value: DmStyle;
  onChange: (next: DmStyle) => void;
}

/**
 * Mid-game DM narration editor shown in the play sidebar. Saves optimistically
 * via `PUT /sessions/{id}/style`, rolling back both the draft and the parent
 * state when the request fails.
 */
export default function DmStylePanel({
  sessionId,
  value,
  onChange,
}: DmStylePanelProps) {
  const [draft, setDraft] = useState<DmStyle>(value);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    if (busy) {
      return;
    }
    const previous = value;
    setBusy(true);
    setError(null);
    setSaved(false);
    onChange(draft);
    try {
      const persisted = await updateSessionStyle(sessionId, draft);
      setDraft(persisted);
      onChange(persisted);
      setSaved(true);
    } catch (err) {
      // Optimistic save failed: roll the draft and the parent state back.
      setDraft(previous);
      onChange(previous);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel dm-style-panel">
      <h2>DM voice</h2>
      <DmStyleFields value={draft} onChange={setDraft} disabled={busy} />
      <button type="button" onClick={() => void handleSave()} disabled={busy}>
        {busy ? "Saving..." : "Save"}
      </button>
      {saved && <p className="saved-hint">Saved.</p>}
      {error !== null && <p className="error">{error}</p>}
    </section>
  );
}
