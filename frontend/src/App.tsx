import { type FormEvent, useEffect, useState } from "react";

import {
  type CharacterSheet,
  createSession,
  deleteSession,
  type GameState,
  getSession,
  getState,
  listSessions,
  loadSettings,
  renameSession,
  saveSettings,
  sendAction,
  type Session,
  type SessionSummary,
  type TavernSettings,
} from "./api";
import CharacterCreationView from "./components/CharacterCreationView";
import CharacterSheetView from "./components/CharacterSheet";
import Chat, { type Message } from "./components/Chat";
import SavedTalesList from "./components/SavedTalesList";
import SettingsPanel from "./components/SettingsPanel";
import StateView from "./components/StateView";

type Phase = "start" | "character" | "play";

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function newId(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** Backend persists transcript roles as "user"/"assistant"; normalize for the UI. */
function toUiRole(role: string): "player" | "gm" {
  return role === "user" || role === "player" ? "player" : "gm";
}

/** Guard: a resumed session without a character arrives as an empty object. */
function isCharacterSheet(
  value: CharacterSheet | null,
): value is CharacterSheet {
  return value !== null && typeof value.name === "string" && value.name !== "";
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("start");
  const [session, setSession] = useState<Session | null>(null);
  const [character, setCharacter] = useState<CharacterSheet | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [settings, setSettings] = useState<TavernSettings>(loadSettings);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsBusy, setSessionsBusy] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const refreshSessions = async () => {
    setSessionsBusy(true);
    setSessionsError(null);
    try {
      setSessions(await listSessions());
    } catch (err) {
      setSessionsError(toMessage(err));
    } finally {
      setSessionsBusy(false);
    }
  };

  useEffect(() => {
    // Load the saved-tales list once on first mount.
    void refreshSessions();
  }, []);

  const handleSaveSettings = (next: TavernSettings) => {
    saveSettings(next);
    setSettings(next);
  };

  const handleStart = async (worldTheme: string) => {
    setBusy(true);
    setError(null);
    try {
      const created = await createSession(worldTheme);
      setSession(created);
      setPhase("character");
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleCharacterCreated = async (character: CharacterSheet) => {
    if (session === null) {
      return;
    }
    setCharacter(character);
    setPhase("play");
    const fallback: Message = {
      id: newId(),
      role: "gm",
      content: `The door creaks open. You are ${character.name}, and a story in ${session.world_theme} begins.`,
      rolls: [],
    };
    try {
      const detail = await getSession(session.session_id);
      const persisted: Message[] = detail.messages.map((message) => ({
        id: newId(),
        role: toUiRole(message.role),
        content: message.content,
        rolls: [],
      }));
      // The backend already persists the AI opening as the first assistant
      // message; only fall back to a default line when no opening was saved.
      setMessages(persisted.length > 0 ? persisted : [fallback]);
    } catch {
      setMessages([fallback]);
    }
    void loadInitialState(session.session_id);
  };

  const loadInitialState = async (sessionId: string) => {
    try {
      const response = await getState(sessionId);
      setState(response.state);
    } catch {
      // State is refreshed from every action response; absence here is fine.
      setState(null);
    }
  };

  const handleResume = async (id: string) => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await getSession(id);
      const character = isCharacterSheet(detail.character)
        ? detail.character
        : null;
      setSession({
        session_id: detail.meta.id,
        world_theme: detail.meta.world_theme,
      });
      setCharacter(character);
      setState(character !== null ? detail.state : null);
      // Persisted transcript as-is; the AI opening is already the first
      // assistant message. No synthetic intro is injected here.
      const persisted: Message[] = detail.messages.map((message) => ({
        id: newId(),
        role: toUiRole(message.role),
        content: message.content,
        rolls: [],
      }));
      setMessages(persisted);
      setPhase("play");
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleRename = async (id: string, title: string) => {
    try {
      await renameSession(id, title);
      await refreshSessions();
    } catch (err) {
      setSessionsError(toMessage(err));
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteSession(id);
      await refreshSessions();
    } catch (err) {
      setSessionsError(toMessage(err));
    }
  };

  const handleBackToTales = () => {
    // State already saved server-side on every action; just leave play.
    setSession(null);
    setCharacter(null);
    setState(null);
    setMessages([]);
    setError(null);
    setPhase("start");
    void refreshSessions();
  };

  const handleSendAction = async (action: string) => {
    if (session === null) {
      return;
    }
    setBusy(true);
    setError(null);
    const playerMessage: Message = {
      id: newId(),
      role: "player",
      content: action,
      rolls: [],
    };
    setMessages((prev) => [...prev, playerMessage]);
    try {
      const response = await sendAction(session.session_id, action);
      const gmMessage: Message = {
        id: newId(),
        role: "gm",
        content: response.narration,
        rolls: response.rolls,
      };
      setMessages((prev) => [...prev, gmMessage]);
      setState(response.state);
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>Open Tavern</h1>
        {session !== null && (
          <span className="session-tag">
            {session.world_theme} · {session.session_id.slice(0, 8)}
          </span>
        )}
      </header>
      <main className="app-main">
        {phase === "start" && (
          <>
            <SettingsPanel initial={settings} onSave={handleSaveSettings} />
            <StartView busy={busy} error={error} onStart={handleStart} />
            <SavedTalesList
              sessions={sessions}
              busy={sessionsBusy}
              error={sessionsError}
              onResume={handleResume}
              onRename={handleRename}
              onDelete={handleDelete}
            />
          </>
        )}
        {phase === "character" && session !== null && (
          <CharacterCreationView
            sessionId={session.session_id}
            onCharacterCreated={handleCharacterCreated}
          />
        )}
        {phase === "play" && (
          <>
            <button
              type="button"
              className="back-button"
              onClick={handleBackToTales}
            >
              ← Back to tales
            </button>
            <div className="play-grid">
              <Chat
                messages={messages}
                busy={busy}
                error={error}
                onSend={handleSendAction}
              />
              <aside className="play-sidebar">
                <StateView state={state} />
                {character !== null && (
                  <CharacterSheetView character={character} />
                )}
              </aside>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

interface StartViewProps {
  busy: boolean;
  error: string | null;
  onStart: (worldTheme: string) => void;
}

function StartView({ busy, error, onStart }: StartViewProps) {
  const [theme, setTheme] = useState("fantasy");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onStart(theme.trim() || "fantasy");
  };

  return (
    <section className="panel start-panel">
      <h2>Begin a New Tale</h2>
      <p className="muted">Name the world and the tavern door will open.</p>
      <form onSubmit={handleSubmit}>
        <label htmlFor="world-theme">World theme</label>
        <input
          id="world-theme"
          value={theme}
          onChange={(event) => setTheme(event.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy}>
          {busy ? "Opening..." : "Begin"}
        </button>
      </form>
      {error !== null && <p className="error">{error}</p>}
    </section>
  );
}
