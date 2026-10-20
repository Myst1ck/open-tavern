import { type FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Virtuoso } from "react-virtuoso";

import type { ActionKind } from "../api/types";
import type { RollSetEntry, TranscriptEntry } from "../transcript";
import RollCard from "./RollCard";

interface ChatProps {
  /** Transcript entries in order: narration bubbles and d20 roll sets. */
  entries: TranscriptEntry[];
  busy: boolean;
  error: string | null;
  onSend: (action: string, kind: ActionKind) => void;
}

const MODE_STORAGE_KEY = "tavern.action-mode";

const MODES: ActionKind[] = ["say", "act", "continue"];

const MODE_LABELS: Record<ActionKind, string> = {
  say: "Say",
  act: "Act",
  continue: "Continue",
};

const MODE_PLACEHOLDERS: Record<ActionKind, string> = {
  say: "What do you say?",
  act: "Describe your action...",
  continue: "The scene advances without text",
};

/** Sticky action mode, read lazily on mount (defaults to "act"). */
function readStoredMode(): ActionKind {
  const stored = window.localStorage.getItem(MODE_STORAGE_KEY);
  return stored === "say" || stored === "act" || stored === "continue"
    ? stored
    : "act";
}

export default function Chat({
  entries,
  busy,
  error,
  onSend,
}: ChatProps) {
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<ActionKind>(readStoredMode);

  const isContinue = mode === "continue";

  const selectMode = (next: ActionKind) => {
    // Keep any typed text: switching to Continue disables the input but must
    // not destroy what the user typed, so it round-trips back to say/act.
    setMode(next);
    window.localStorage.setItem(MODE_STORAGE_KEY, next);
  };

  // One button cycles the mode (say -> act -> continue -> say) so the input
  // keeps its width on narrow screens.
  const cycleMode = () => {
    selectMode(MODES[(MODES.indexOf(mode) + 1) % MODES.length]);
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (busy) {
      return;
    }
    if (mode === "continue") {
      // Continue is the only text-free mode; the GM advances the scene.
      onSend("", "continue");
      return;
    }
    const action = input.trim();
    if (action === "") {
      return;
    }
    setInput("");
    onSend(action, mode);
  };

  return (
    <section className="panel chat-panel">
      {entries.length === 0 ? (
        <p className="chat-empty muted">The tavern is quiet. What do you do?</p>
      ) : (
        <Virtuoso
          className="chat-list"
          data={entries}
          followOutput="smooth"
          initialTopMostItemIndex={Math.max(0, entries.length - 1)}
          computeItemKey={(_index, entry) => entry.id}
          itemContent={(_index, entry) => (
            <div className="chat-row">
              {entry.kind === "message" ? (
                <MessageBubble entry={entry} />
              ) : (
                <RollSetBlock entry={entry} />
              )}
            </div>
          )}
        />
      )}
      {error !== null && <p className="error chat-error">{error}</p>}
      <form className="chat-form" onSubmit={handleSubmit}>
        <button
          type="button"
          className="mode-toggle"
          onClick={cycleMode}
          disabled={busy}
          title={`Action mode: ${MODE_LABELS[mode]} — click to switch`}
          aria-label={`Action mode: ${MODE_LABELS[mode]}. Click to switch.`}
        >
          {MODE_LABELS[mode]}
          <svg
            className="mode-toggle-icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M21 4v6h-6" />
            <path d="M21 10a9 9 0 1 1-2.12-9.36L21 10" />
          </svg>
        </button>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={MODE_PLACEHOLDERS[mode]}
          disabled={busy || isContinue}
          aria-label="Action input"
        />
        <button
          type="submit"
          className="send-button"
          disabled={busy || (!isContinue && input.trim() === "")}
        >
          {busy ? "..." : "Send"}
        </button>
      </form>
    </section>
  );
}

/** A narration bubble: the player's action or the GM's reply. */
type MessageEntry = Extract<TranscriptEntry, { kind: "message" }>;

function MessageBubble({ entry }: { entry: MessageEntry }) {
  const isPlayer = entry.role === "user";
  // Player continue turns (and any empty player body) collapse to a muted
  // placeholder; GM narration never uses it.
  const isPlaceholder =
    isPlayer && (entry.actionKind === "continue" || entry.content === "");
  const className = [
    "chat-message",
    isPlayer ? "player" : "gm",
    entry.actionKind === "say" ? "say" : null,
    isPlaceholder ? "placeholder" : null,
  ]
    .filter((part) => part !== null)
    .join(" ");

  return (
    <div className={className}>
      <span className="chat-author">{isPlayer ? "You" : "The Tavern"}</span>
      {isPlaceholder ? (
        <p className="chat-placeholder">— scene continues —</p>
      ) : (
        <div className="chat-prose">
          <ReactMarkdown>{entry.content}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}

interface RollSetBlockProps {
  entry: RollSetEntry;
}

/**
 * Mounts every card at once: the dice resolved together server-side, so they
 * tumble in parallel. Each card runs its own short timer (RollCard). Revealed
 * sets (resumed transcripts) mount already shown.
 */
function RollSetBlock({ entry }: RollSetBlockProps) {
  return (
    <div className="roll-set">
      {entry.rolls.map((roll, index) => (
        <RollCard
          key={`${entry.id}-${index}`}
          roll={roll}
          initialRevealed={entry.state === "revealed"}
        />
      ))}
    </div>
  );
}
