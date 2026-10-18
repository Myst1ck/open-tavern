const SETTINGS_KEY = "open-tavern-settings";

export interface TavernSettings {
  apiKey: string;
  baseUrl: string;
  model: string;
}

/**
 * Read settings from localStorage, tolerating missing/corrupt values.
 *
 * SECURITY NOTE: the API key is persisted in plaintext in localStorage.
 * Any script running on this origin (or an XSS payload) can read it, and it
 * survives in the browser profile after logout. SettingsPanel should warn
 * users of this exposure; do not treat the stored key as a secret at rest.
 */
export function loadSettings(): TavernSettings {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw) as Partial<TavernSettings>;
      return {
        apiKey: typeof parsed.apiKey === "string" ? parsed.apiKey : "",
        baseUrl: typeof parsed.baseUrl === "string" ? parsed.baseUrl : "",
        model: typeof parsed.model === "string" ? parsed.model : "",
      };
    }
  } catch {
    // Corrupt settings fall through to defaults.
  }
  return { apiKey: "", baseUrl: "", model: "" };
}

/** Persist settings to localStorage. */
export function saveSettings(settings: TavernSettings): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  cachedSettings = { ...settings };
}

/**
 * Module-level cache of the parsed localStorage settings, refreshed on save.
 * Avoids re-reading and re-parsing localStorage on every API request.
 */
export let cachedSettings: TavernSettings = loadSettings();

export function settingsHeaders(
  settings: TavernSettings,
): Record<string, string> {
  const headers: Record<string, string> = {};
  if (settings.apiKey !== "") {
    headers["X-API-Key"] = settings.apiKey;
  }
  if (settings.model !== "") {
    headers["X-Model"] = settings.model;
  }
  if (settings.baseUrl !== "") {
    headers["X-Base-Url"] = settings.baseUrl;
  }
  return headers;
}
