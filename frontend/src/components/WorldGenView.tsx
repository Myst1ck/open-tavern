import { type FormEvent, useState } from "react";

import { generateWorld } from "../api";

export interface WorldGenViewProps {
  onAccept: (theme: string, premise: string) => Promise<void> | void;
  onBack: () => void;
}

interface WorldPreview {
  theme: string;
  premise: string;
}

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Pre-game world generation. The player describes a world (or asks to be
 * surprised); the backend returns a theme + premise, which the player may
 * regenerate or accept. No session exists until "Accept" is clicked.
 */
export default function WorldGenView({
  onAccept,
  onBack,
}: WorldGenViewProps) {
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<WorldPreview | null>(null);
  const [lastSurprise, setLastSurprise] = useState(false);

  const handleGenerate = async (surprise: boolean) => {
    if (busy) {
      return;
    }
    const text = description.trim();
    // A surprise world needs no description; a described world does.
    if (!surprise && text === "") {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await generateWorld(text, surprise);
      setPreview({ theme: response.theme, premise: response.premise });
      setLastSurprise(surprise);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    void handleGenerate(false);
  };

  const handleAccept = async () => {
    if (busy || preview === null) {
      return;
    }
    // Keep both Accept and Back disabled while the session is created, so a
    // Back click mid-await cannot orphan the in-flight session.
    setBusy(true);
    setError(null);
    try {
      await onAccept(preview.theme, preview.premise);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel worldgen-panel">
      <button
        type="button"
        className="back-button"
        onClick={onBack}
        disabled={busy}
      >
        ← Back
      </button>
      <h2>Forge your world</h2>
      <p className="muted">Describe the world you want to play in.</p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="world-description">World description</label>
        <textarea
          id="world-description"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="A drowned empire where the dead sail iron ships..."
          maxLength={2000}
          disabled={busy}
        />
        <div className="worldgen-actions">
          <button type="submit" disabled={busy || description.trim() === ""}>
            {busy ? "Weaving worlds..." : "Generate World"}
          </button>
          <button
            type="button"
            className="wizard-switch"
            onClick={() => void handleGenerate(true)}
            disabled={busy}
          >
            Surprise me
          </button>
        </div>
      </form>
      {error !== null && <p className="error">{error}</p>}
      {preview !== null && (
        <div className="panel world-preview">
          <h3>{preview.theme}</h3>
          <p className="muted">{preview.premise}</p>
          <div className="refine-actions">
            <button type="button" onClick={() => void handleAccept()} disabled={busy}>
              Accept
            </button>
            <button
              type="button"
              className="wizard-switch"
              onClick={() =>
                void handleGenerate(
                  description.trim() === "" ? lastSurprise : false,
                )
              }
              disabled={busy}
            >
              Generate Again
            </button>
          </div>
        </div>
      )}
    </section>
  );
}