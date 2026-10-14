import { type FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Virtuoso } from "react-virtuoso";

import { type ActionKind, type RollOutcome } from "../api";

export interface Message {
  id: string;
  role: "player" | "gm";
  content: string;
  rolls: RollOutcome[];
  kind?: ActionKind;
}

interface ChatProps {
  messages: Message[];
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

export default function Chat({ messages, busy, error, onSend }: ChatProps) {
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
      {messages.length === 0 ? (
        <p className="chat-empty muted">The tavern is quiet. What do you do?</p>
      ) : (
        <Virtuoso
          className="chat-list"
          data={messages}
          followOutput="smooth"
          initialTopMostItemIndex={Math.max(0, messages.length - 1)}
          computeItemKey={(_index, message) => message.id}
          itemContent={(_index, message) => (
            <div className="chat-row">
              <MessageBubble message={message} />
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
          disabled={busy || (!isContinue && input.trim() === "")}
        >
          {busy ? "..." : "Send"}
        </button>
      </form>
    </section>
  );
}

function MessageBubble({ message }: { message: Message }) {
  // Player continue turns (and any empty player body) collapse to a muted
  // placeholder; GM narration never uses it.
  const isPlaceholder =
    message.role === "player" &&
    (message.kind === "continue" || message.content === "");
  const className = [
    "chat-message",
    message.role,
    message.kind === "say" ? "say" : null,
    isPlaceholder ? "placeholder" : null,
  ]
    .filter((part) => part !== null)
    .join(" ");

  return (
    <div className={className}>
      <span className="chat-author">
        {message.role === "player" ? "You" : "The Tavern"}
      </span>
      {isPlaceholder ? (
        <p className="chat-placeholder">— scene continues —</p>
      ) : (
        <div className="chat-prose">
          <ReactMarkdown>{message.content}</ReactMarkdown>
        </div>
      )}
      {message.rolls.length > 0 && <RollsDisplay rolls={message.rolls} />}
    </div>
  );
}

function RollsDisplay({ rolls }: { rolls: RollOutcome[] }) {
  return (
    <ul className="rolls">
      {rolls.map((roll, index) => {
        const mod =
          roll.modifier >= 0
            ? `+ ${roll.modifier}`
            : `- ${Math.abs(roll.modifier)}`;
        const result = roll.crit_success
          ? " CRITICAL SUCCESS"
          : roll.crit_fail
            ? " CRITICAL FAILURE"
            : roll.success
              ? " SUCCESS"
              : " FAILURE";
        return (
          <li
            key={`${roll.name}-${index}`}
            className={roll.success ? "roll-success" : "roll-fail"}
          >
            {roll.name}: d20 {roll.d20} ({mod}) = {roll.total}
            {result}
          </li>
        );
      })}
    </ul>
  );
}
