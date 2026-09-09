import { useCallback, useEffect, useMemo, useState } from "react";

import {
  type CharacterSheet,
  createSession,
  deleteItem,
  deleteSession,
  equipItem,
  type GameState,
  getSession,
  getState,
  type Item,
  listSessions,
  loadSettings,
  renameSession,
  saveSettings,
  sendAction,
  type Session,
  type SessionSummary,
  type TavernSettings,
  unequipItem,
  useItem as callUseItem,
} from "./api";
import BrainstormView from "./components/BrainstormView";
import CharacterCreationView from "./components/CharacterCreationView";
import CharacterSheetView from "./components/CharacterSheet";
import Chat, { type Message } from "./components/Chat";
import FilterBar, { type FilterState } from "./components/FilterBar";
import InventoryGrid from "./components/InventoryGrid";
import ItemModal from "./components/ItemModal";
import ItemTooltip from "./components/ItemTooltip";
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
  const [filter, setFilter] = useState<FilterState>({
    sortBy: "name",
    sortDir: "asc",
  });
  const [hoveredItem, setHoveredItem] = useState<Item | null>(null);
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 });
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);

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

  const filteredItems: Item[] = useMemo(() => {
    const tagFilter = filter.tag?.toLowerCase();
    return (character?.inventory ?? [])
      .filter((item) => {
        if (filter.type && item.type !== filter.type) return false;
        if (
          tagFilter &&
          !item.tags.some((t) => t.toLowerCase().includes(tagFilter))
        )
          return false;
        return true;
      })
      .sort((a, b) => {
        const dir = filter.sortDir === "asc" ? 1 : -1;
        switch (filter.sortBy) {
          case "name":
            return a.name.localeCompare(b.name) * dir;
          case "type":
            return a.type.localeCompare(b.type) * dir;
          case "value":
            return (a.stats.value - b.stats.value) * dir;
          case "weight":
            return (a.stats.weight - b.stats.weight) * dir;
          default:
            return 0;
        }
      });
  }, [character?.inventory, filter]);

  const handleItemHover = useCallback((item: Item | null) => {
    setHoveredItem(item);
  }, []);

  useEffect(() => {
    if (!hoveredItem) return;
    const onMove = (e: MouseEvent) =>
      setHoverPos({ x: e.clientX, y: e.clientY });
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [hoveredItem]);

  const handleItemClick = useCallback((item: Item) => {
    setSelectedItem(item);
  }, []);

  const handleItemAction = useCallback(
    async (action: string, item: Item) => {
      if (!session || !character) return;
      try {
        const charId = session.session_id;
        let res;
        switch (action) {
          case "equip":
            res = await equipItem(session.session_id, charId, item.id);
            break;
          case "unequip":
            res = await unequipItem(session.session_id, charId, item.id);
            break;
          case "use":
            res = await callUseItem(session.session_id, charId, item.id);
            break;
          case "drop":
            res = await deleteItem(session.session_id, charId, item.id);
            break;
          default:
            return;
        }
        if (res.success) {
          const fresh = await getState(session.session_id);
          setState(fresh.state);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Item action failed");
      }
      setSelectedItem(null);
    },
    [session, character],
  );

  const handleSaveSettings = (next: TavernSettings) => {
    saveSettings(next);
    setSettings(next);
  };

  const handleStart = async (worldTheme: string, premise: string) => {
    setBusy(true);
    setError(null);
    try {
      const created = await createSession(worldTheme, undefined, premise);
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
            <BrainstormView onBegin={handleStart} />
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
                {character !== null && character.inventory.length > 0 && (
                  <section className="panel">
                    <h2>Inventory</h2>
                    <FilterBar
                      currentFilter={filter}
                      onFilterChange={setFilter}
                    />
                    <InventoryGrid
                      items={filteredItems}
                      onItemClick={handleItemClick}
                      onItemHover={handleItemHover}
                    />
                  </section>
                )}
              </aside>
            </div>
            {selectedItem !== null && (
              <ItemModal
                item={selectedItem}
                onClose={() => setSelectedItem(null)}
                onEquip={(item) => handleItemAction("equip", item)}
                onUnequip={(item) => handleItemAction("unequip", item)}
                onUse={(item) => handleItemAction("use", item)}
                onDrop={(item) => handleItemAction("drop", item)}
              />
            )}
            {hoveredItem !== null && (
              <ItemTooltip
                item={hoveredItem}
                position={hoverPos}
                visible={true}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
