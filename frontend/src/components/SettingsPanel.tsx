import { type FormEvent, useState } from "react";

import { getToken, setToken, type TavernSettings } from "../api";

interface SettingsPanelProps {
  initial: TavernSettings;
  onSave: (settings: TavernSettings) => void;
}

/** Collapsible panel for per-browser LLM connection settings. */
export default function SettingsPanel({ initial, onSave }: SettingsPanelProps) {
  const [draft, setDraft] = useState<TavernSettings>(initial);
  const [token, setTokenDraft] = useState<string>(getToken);
  const [saved, setSaved] = useState(false);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSave(draft);
    setToken(token);
    setSaved(true);
  };

  const update = (patch: Partial<TavernSettings>) => {
    setSaved(false);
    setDraft((prev) => ({ ...prev, ...patch }));
  };

  return (
    <details className="panel settings-panel">
      <summary>⚙ Settings</summary>
      <p className="muted settings-hint">
        Your API key and backend token are stored only in this browser and sent
        with each request. A custom Base URL enables local models like Ollama
        (e.g. <code>http://localhost:11434/v1</code>).
      </p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="settings-token">Backend token</label>
        <input
          id="settings-token"
          type="password"
          value={token}
          onChange={(event) => {
            setSaved(false);
            setTokenDraft(event.target.value);
          }}
          placeholder="OPEN_TAVERN_TOKEN"
          autoComplete="off"
        />
        <label htmlFor="settings-api-key">API key</label>
        <input
          id="settings-api-key"
          type="password"
          value={draft.apiKey}
          onChange={(event) => update({ apiKey: event.target.value })}
          placeholder="sk-..."
          autoComplete="off"
        />
        <label htmlFor="settings-base-url">Base URL</label>
        <input
          id="settings-base-url"
          type="text"
          value={draft.baseUrl}
          onChange={(event) => update({ baseUrl: event.target.value })}
          placeholder="https://api.openai.com/v1"
          autoComplete="off"
        />
        <label htmlFor="settings-model">Model</label>
        <input
          id="settings-model"
          type="text"
          value={draft.model}
          onChange={(event) => update({ model: event.target.value })}
          placeholder="gpt-4o-mini"
          autoComplete="off"
        />
        <button type="submit">Save</button>
        {saved && <p className="settings-saved">Saved.</p>}
      </form>
    </details>
  );
}
