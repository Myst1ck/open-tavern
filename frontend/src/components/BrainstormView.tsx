import { type FormEvent, useEffect, useRef, useState } from "react";

import { brainstorm, type Message } from "../api";

export interface BrainstormViewProps {
  onBegin: (theme: string, premise: string) => void;
}

interface BrainstormMessage {
  role: "user" | "assistant";
  content: string;
}

/**
 * Pre-game brainstorm chat. The player converses with the LLM to shape the
 * world theme and premise; no session exists until "Start Adventure" is
 * clicked, at which point the resolved theme + premise are handed up.
 */
export default function BrainstormView({ onBegin }: BrainstormViewProps) {
  const [messages, setMessages] = useState<BrainstormMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<string | null>(null);
  const [premise, setPremise] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = listRef.current;
    if (element !== null) {
      element.scrollTop = element.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const text = input.trim();
    if (text === "" || busy) {
      return;
    }
    setInput("");
    setError(null);

    const nextMessages: BrainstormMessage[] = [
      ...messages,
      { role: "user", content: text },
    ];
    setMessages(nextMessages);
    setBusy(true);
    try {
      const payload: Message[] = nextMessages.map((message) => ({
        role: message.role,
        content: message.content,
      }));
      const response = await brainstorm(payload);
      setTheme(response.theme);
      setPremise(response.premise);
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: `Theme: ${response.theme}\n\nPremise: ${response.premise}`,
        },
      ]);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Brainstorm request failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const ready = theme !== null && premise !== null;

  return (
    <section className="panel chat-panel" aria-label="World brainstorm">
      <div className="chat-list" ref={listRef}>
        {messages.length === 0 && (
          <p className="chat-empty muted">
            The tavern keeper leans in. Describe the world you want to play in.
          </p>
        )}
        {messages.map((message, index) => (
          <div
            key={index}
            className={`chat-message ${message.role === "user" ? "player" : "gm"}`}
          >
            <span className="chat-author">
              {message.role === "user" ? "You" : "The Tavern"}
            </span>
            <p>{message.content}</p>
          </div>
        ))}
      </div>
      {error !== null && <p className="error chat-error">{error}</p>}
      {ready && (
        <div className="panel brainstorm-summary">
          <p>
            <strong>Theme:</strong> {theme}
          </p>
          <p>
            <strong>Premise:</strong> {premise}
          </p>
        </div>
      )}
      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Describe your world..."
          disabled={busy}
          aria-label="Brainstorm input"
        />
        <button type="submit" disabled={busy || input.trim() === ""}>
          {busy ? "..." : "Send"}
        </button>
      </form>
      <button
        type="button"
        className="brainstorm-start"
        disabled={!ready || busy}
        onClick={() => {
          if (theme !== null && premise !== null) {
            onBegin(theme, premise);
          }
        }}
      >
        Start Adventure
      </button>
    </section>
  );
}
