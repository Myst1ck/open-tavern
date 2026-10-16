import { useCallback, useEffect, useMemo, useState } from "react";

import {
  deleteItem,
  equipItem,
  unequipItem,
  useItem as callUseItem,
} from "./api/items";
import {
  createSession,
  deleteSession,
  getSession,
  getState,
  listSessions,
  renameSession,
} from "./api/sessions";
import {
  loadSettings,
  saveSettings,
  type TavernSettings,
} from "./api/settings";
import { DEFAULT_DM_STYLE } from "./api/style";
import {
  type ActionKind,
  type CharacterSheet,
  type ChatMessage,
  type DmStyle,
  type GameState,
  type Item,
  type Session,
  type SessionSummary,
} from "./api/types";
import CharacterCreationView from "./components/CharacterCreationView";
import CharacterSheetView from "./components/CharacterSheet";
import Chat from "./components/Chat";
import CreateTaleCard from "./components/CreateTaleCard";
import DmStylePanel from "./components/DmStylePanel";
import FilterBar, { type FilterState } from "./components/FilterBar";
import InstallButton from "./components/InstallButton";
import InventoryGrid from "./components/InventoryGrid";
import ItemModal from "./components/ItemModal";
import ItemTooltip from "./components/ItemTooltip";
import PlayTabs, { type PlayTabId } from "./components/PlayTabs";
import SavedTalesList from "./components/SavedTalesList";
import SettingsPanel from "./components/SettingsPanel";
import StateView from "./components/StateView";
import UpdateToast from "./components/UpdateToast";
import WorldGenView from "./components/WorldGenView";
import { newEntryId, type TranscriptEntry } from "./transcript";
import { useTurnStream } from "./useTurnStream";

type Phase = "home" | "worldgen" | "character" | "play";

function toMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Map the persisted transcript onto UI entries: an assistant turn's saved rolls
 * become a static, already-revealed roll set placed before its narration.
 */
function toTranscriptEntries(messages: ChatMessage[]): TranscriptEntry[] {
  const entries: TranscriptEntry[] = [];
  for (const message of messages) {
    if (message.rolls !== undefined && message.rolls.length > 0) {
      entries.push({
        kind: "roll-set",
        id: newEntryId(),
        rolls: message.rolls,
        state: "revealed",
      });
    }
    entries.push({
      kind: "message",
      id: newEntryId(),
      role: message.role,
      content: message.content,
    });
  }
  return entries;
}

/** Guard: a resumed session without a character arrives as an empty object. */
function isCharacterSheet(
  value: CharacterSheet | null,
): value is CharacterSheet {
  return value !== null && typeof value.name === "string" && value.name !== "";
}

interface InventoryPanelProps {
  items: Item[];
  onItemClick: (item: Item) => void;
}

/**
 * Owns tooltip/hover state so hovering an inventory card re-renders only this
 * subtree, not the whole play view (Chat, StateView, ...).
 */
function InventoryPanel({ items, onItemClick }: InventoryPanelProps) {
  const [hovered, setHovered] = useState<{
    item: Item;
    point?: { x: number; y: number };
  } | null>(null);
  return (
    <>
      <InventoryGrid
        items={items}
        onItemClick={onItemClick}
        onItemHover={(item, point) =>
          setHovered(item !== null ? { item, point } : null)
        }
      />
      {hovered !== null && (
        <ItemTooltip
          item={hovered.item}
          visible={true}
          position={hovered.point}
        />
      )}
    </>
  );
}

export default function App() {
  const [phase, setPhase] = useState<Phase>("home");
  const [session, setSession] = useState<Session | null>(null);
  const [dmStyle, setDmStyle] = useState<DmStyle>(DEFAULT_DM_STYLE);
  const [character, setCharacter] = useState<CharacterSheet | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
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
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const [itemBusy, setItemBusy] = useState(false);
  const [playTab, setPlayTab] = useState<PlayTabId>("campaign");

  const handleTurnComplete = useCallback((next: GameState) => {
    setState(next);
    setCharacter(next.character);
  }, []);

  const turn = useTurnStream({
    setEntries,
    setBusy,
    setError,
    onTurnComplete: handleTurnComplete,
  });

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

  const handleItemClick = useCallback((item: Item) => {
    setSelectedItem(item);
  }, []);

  const handleItemAction = useCallback(
    async (action: string, item: Item) => {
      // ``busy`` too: an item mutation mid-turn would race the state snapshot
      // the turn response is about to write.
      if (!session || !character || busy || itemBusy) return;
      setItemBusy(true);
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
          setCharacter(fresh.state.character);
          // Close only on success; a failed action keeps the modal open.
          setSelectedItem(null);
        } else {
          // A 200 with success: false still carries a reason; surface it.
          setError(res.message !== "" ? res.message : "Item action failed");
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Item action failed");
      } finally {
        setItemBusy(false);
      }
    },
    [session, character, busy, itemBusy],
  );

  const handleSaveSettings = (next: TavernSettings) => {
    saveSettings(next);
    setSettings(next);
  };

  const handleStart = async (
    worldTheme: string,
    premise: string,
    style: DmStyle,
  ) => {
    setBusy(true);
    setError(null);
    try {
      const created = await createSession(
        worldTheme,
        undefined,
        premise,
        style,
      );
      setSession(created);
      // A fresh session resets any character progress from a prior world.
      setCharacter(null);
      setState(null);
      setEntries([]);
      setDmStyle(style);
      setPhase("character");
    } catch (err) {
      setError(toMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleBackToWorldGen = () => {
    // Abandon the pending session; accepting a world creates a new one.
    setSession(null);
    setCharacter(null);
    setState(null);
    setEntries([]);
    setError(null);
    setPhase("worldgen");
  };

  const handleExitWorldGen = () => {
    // Leaving world generation discards any pending session/preview state.
    setSession(null);
    setCharacter(null);
    setState(null);
    setEntries([]);
    setError(null);
    setPhase("home");
  };

  const handleCharacterCreated = async (character: CharacterSheet) => {
    if (session === null) {
      return;
    }
    // Hold the busy flag across the load so a player turn cannot be sent (and
    // then wiped by the persisted transcript) while it is still arriving.
    setBusy(true);
    setCharacter(character);
    setPlayTab("campaign");
    setPhase("play");
    const fallback: TranscriptEntry = {
      kind: "message",
      id: newEntryId(),
      role: "assistant",
      content: `The door creaks open. You are ${character.name}, and a story in ${session.world_theme} begins.`,
    };
    try {
      const detail = await getSession(session.session_id);
      const persisted = toTranscriptEntries(detail.messages);
      // The backend already persists the AI opening as the first assistant
      // message; only fall back to a default line when no opening was saved.
      setEntries(persisted.length > 0 ? persisted : [fallback]);
    } catch (err) {
      // The opening is persisted server-side; say so rather than silently
      // showing a line the transcript does not contain.
      setEntries([fallback]);
      setError(`Could not load the transcript: ${toMessage(err)}`);
    } finally {
      setBusy(false);
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
        dm_style: detail.dm_style,
      });
      setCharacter(character);
      setState(character !== null ? detail.state : null);
      setDmStyle(detail.dm_style ?? DEFAULT_DM_STYLE);
      // Persisted transcript as-is; the AI opening is already the first
      // assistant message. No synthetic intro is injected here. Saved turn
      // rolls come back as static, already-revealed roll sets.
      setEntries(toTranscriptEntries(detail.messages));
      setPlayTab("campaign");
      // A session without a character has no play view to land in.
      setPhase(character !== null ? "play" : "character");
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

  const handleBackToHome = () => {
    // State already saved server-side on every action; just leave play. An
    // in-flight turn (e.g. mid-reveal) is abandoned, not awaited.
    turn.reset();
    setSession(null);
    setCharacter(null);
    setState(null);
    setEntries([]);
    setError(null);
    setPlayTab("campaign");
    setPhase("home");
    void refreshSessions();
  };

  /**
   * Hand one player turn to the stream driver: it appends the optimistic player
   * entry, renders the streamed roll set, and reveals the buffered narration
   * once every card has landed. The `kind` frames the action for the backend and
   * styles the player bubble.
   */
  const handleSendAction = (action: string, kind: ActionKind) => {
    // A turn sent while an item mutation is in flight would persist state
    // computed before that mutation committed.
    if (session === null || busy || itemBusy) {
      return;
    }
    turn.send(session.session_id, action, kind);
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
        <InstallButton />
      </header>
      <UpdateToast />
      <main className="app-main">
        {phase === "home" && (
          <>
            {error !== null && <p className="error">{error}</p>}
            <SettingsPanel initial={settings} onSave={handleSaveSettings} />
            <CreateTaleCard onCreate={() => setPhase("worldgen")} />
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
        {phase === "worldgen" && (
          <>
            {error !== null && <p className="error">{error}</p>}
            <WorldGenView onAccept={handleStart} onBack={handleExitWorldGen} />
          </>
        )}
        {phase === "character" && session !== null && (
          <CharacterCreationView
            sessionId={session.session_id}
            onCharacterCreated={handleCharacterCreated}
            onBack={handleBackToWorldGen}
          />
        )}
        {phase === "play" && session !== null && (
          <>
            <div className="play-topbar">
              <button
                type="button"
                className="back-button play-back"
                aria-label="Back to tales"
                title="Back to tales"
                onClick={handleBackToHome}
                disabled={busy}
              >
                ← Tales
              </button>
              <PlayTabs active={playTab} onChange={setPlayTab} />
            </div>
            <div className="play-content">
              {/* Chat stays mounted so scroll position and input survive tab
                  round-trips; hidden via CSS rather than unmounted. */}
              <div
                className={`play-tab-panel${playTab === "campaign" ? "" : " play-tab-hidden"}`}
                role="tabpanel"
                id="play-panel-campaign"
                aria-labelledby="play-tab-campaign"
              >
                <Chat
                  entries={entries}
                  busy={busy}
                  error={error}
                  onSend={handleSendAction}
                  revealCount={turn.revealCount}
                  onRollRevealed={turn.onRollRevealed}
                />
              </div>
              {playTab === "character" && (
                <div
                  className="play-tab-panel"
                  role="tabpanel"
                  id="play-panel-character"
                  aria-labelledby="play-tab-character"
                >
                  <StateView state={state} />
                  {character !== null && (
                    <CharacterSheetView character={character} />
                  )}
                </div>
              )}
              {playTab === "inventory" && (
                <div
                  className="play-tab-panel"
                  role="tabpanel"
                  id="play-panel-inventory"
                  aria-labelledby="play-tab-inventory"
                >
                  <section className="panel">
                    <h2>Inventory</h2>
                    <FilterBar
                      currentFilter={filter}
                      onFilterChange={setFilter}
                    />
                    <InventoryPanel
                      items={filteredItems}
                      onItemClick={handleItemClick}
                    />
                  </section>
                </div>
              )}
              {playTab === "dm-style" && (
                <div
                  className="play-tab-panel"
                  role="tabpanel"
                  id="play-panel-dm-style"
                  aria-labelledby="play-tab-dm-style"
                >
                  <DmStylePanel
                    sessionId={session.session_id}
                    value={dmStyle}
                    onChange={setDmStyle}
                  />
                </div>
              )}
            </div>
            {selectedItem !== null && (
              <ItemModal
                item={selectedItem}
                busy={itemBusy}
                onClose={() => setSelectedItem(null)}
                onEquip={(item) => handleItemAction("equip", item)}
                onUnequip={(item) => handleItemAction("unequip", item)}
                onUse={(item) => handleItemAction("use", item)}
                onDrop={(item) => handleItemAction("drop", item)}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
