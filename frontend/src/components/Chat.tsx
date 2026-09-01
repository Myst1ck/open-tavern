import { type FormEvent, useEffect, useRef, useState } from "react";

import type { RollOutcome } from "../api";

export interface Message {
  id: string;
  role: "player" | "gm";
  content: string;
  rolls: RollOutcome[];
}

interface ChatProps {
  messages: Message[];
  busy: boolean;
  error: string | null;
  onSend: (action: string) => void;
}

export default function Chat({ messages, busy, error, onSend }: ChatProps) {
  const [input, setInput] = useState("");
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = listRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [messages]);

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
        {messages.length === 0 && (
          <p className="chat-empty muted">
            The tavern is quiet. What do you do?
          </p>
        )}
        {messages.map((message) => (
          <div key={message.id} className={`chat-message ${message.role}`}>
            <span className="chat-author">
              {message.role === "player" ? "You" : "The Tavern"}
            </span>
            <p>{message.content}</p>
            {message.rolls.length > 0 && <RollsDisplay rolls={message.rolls} />}
          </div>
        ))}
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
