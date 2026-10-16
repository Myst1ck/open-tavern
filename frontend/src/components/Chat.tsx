import { type FormEvent, useEffect, useRef, useState } from "react";

import type { RollSetEntry, TranscriptEntry } from "../transcript";
import RollCard from "./RollCard";

interface ChatProps {
  entries: TranscriptEntry[];
  busy: boolean;
  error: string | null;
  onSend: (action: string) => void;
  /** Roll cards already revealed in the active set (0 = only the first is up). */
  revealCount: number;
  onRollRevealed: (rollSetId: string, index: number) => void;
}

export default function Chat({
  entries,
  busy,
  error,
  onSend,
  revealCount,
  onRollRevealed,
}: ChatProps) {
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = listRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [entries, revealCount]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    const action = input.trim();
    if (action === "" || busy) {
      return;
    }
    setInput("");
    onSend(action);
  };

  return (
    <section className="panel chat-panel">
      <div className="chat-list" ref={listRef}>
        {entries.length === 0 && (
          <p className="chat-empty muted">
            The tavern is quiet. What do you do?
          </p>
        )}
        {entries.map((entry) =>
          entry.kind === "message" ? (
            <div
              key={entry.id}
              className={`chat-message ${entry.role === "user" ? "player" : "gm"}`}
            >
              <span className="chat-author">
                {entry.role === "user" ? "You" : "The Tavern"}
              </span>
              <p>{entry.content}</p>
            </div>
          ) : (
            <RollSetBlock
              key={entry.id}
              entry={entry}
              revealCount={revealCount}
              onRevealed={onRollRevealed}
            />
          ),
        )}
      </div>
      {error !== null && <p className="error chat-error">{error}</p>}
      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Describe your action..."
          disabled={busy}
          aria-label="Action input"
        />
        <button type="submit" disabled={busy || input.trim() === ""}>
          {busy ? "..." : "Act"}
        </button>
      </form>
    </section>
  );
}

interface RollSetBlockProps {
  entry: RollSetEntry;
  revealCount: number;
  onRevealed: (rollSetId: string, index: number) => void;
}

/**
 * Mounts cards one at a time so each die starts tumbling only once the previous
 * one has revealed — RollCard starts its own timer on mount. Revealed sets
 * (resumed transcripts) mount everything at once, already revealed.
 */
function RollSetBlock({ entry, revealCount, onRevealed }: RollSetBlockProps) {
  const mounted =
    entry.state === "pending"
      ? Math.min(revealCount + 1, entry.rolls.length)
      : entry.rolls.length;
  return (
    <div className="roll-set">
      {entry.rolls.slice(0, mounted).map((roll, index) => (
        <RollCard
          key={`${entry.id}-${index}`}
          roll={roll}
          initialRevealed={entry.state === "revealed"}
          onRevealed={() => onRevealed(entry.id, index)}
        />
      ))}
    </div>
  );
}
