import { useState, type FormEvent } from "react";
import type { SessionSummary } from "../api";

interface SavedTalesListProps {
  sessions: SessionSummary[];
  busy: boolean;
  error: string | null;
  onResume: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

function formatUpdatedAt(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString();
}

export default function SavedTalesList({
  sessions,
  busy,
  error,
  onResume,
  onRename,
  onDelete,
}: SavedTalesListProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);

  const beginEdit = (session: SessionSummary) => {
    setEditingId(session.id);
    setDraftTitle(session.title);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setDraftTitle("");
  };

  const submitRename = async (event: FormEvent, id: string) => {
    event.preventDefault();
    const title = draftTitle.trim();
    if (title === "" || pendingId !== null) {
      return;
    }
    setPendingId(id);
    try {
      await onRename(id, title);
      setEditingId(null);
    } finally {
      setPendingId(null);
    }
  };

  const handleDelete = async (session: SessionSummary) => {
    if (!window.confirm(`Delete "${session.title}"? This cannot be undone.`)) {
      return;
    }
    setPendingId(session.id);
    try {
      await onDelete(session.id);
    } finally {
      setPendingId(null);
    }
  };

  return (
    <section className="panel tales-panel">
      <h2>Saved Tales</h2>
      {busy && sessions.length === 0 && (
        <p className="muted">Loading your tales...</p>
      )}
      {!busy && sessions.length === 0 && (
        <p className="muted">No saved tales yet. Begin a new tale above.</p>
      )}
      {error !== null && <p className="error">{error}</p>}
      {sessions.length > 0 && (
        <ul className="tales-list">
          {sessions.map((session) => {
            const isEditing = editingId === session.id;
            const isPending = pendingId === session.id;
            return (
              <li key={session.id} className="tale-row">
                <div className="tale-info">
                  <span className="tale-title">
                    {session.title || "Untitled tale"}
                  </span>
                  <span className="tale-meta muted">
                    {session.world_theme} · {formatUpdatedAt(session.updated_at)}
                  </span>
                </div>
                {isEditing ? (
                  <form
                    className="tale-rename"
                    onSubmit={(event) => submitRename(event, session.id)}
                  >
                    <input
                      value={draftTitle}
                      onChange={(event) => setDraftTitle(event.target.value)}
                      disabled={isPending}
                      autoFocus
                      aria-label="Rename tale"
                    />
                    <button
                      type="submit"
                      disabled={isPending || draftTitle.trim() === ""}
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={cancelEdit}
                      disabled={isPending}
                    >
                      Cancel
                    </button>
                  </form>
                ) : (
                  <div className="tale-actions">
                    <button
                      type="button"
                      onClick={() => onResume(session.id)}
                      disabled={busy || isPending}
                    >
                      Resume
                    </button>
                    <button
                      type="button"
                      onClick={() => beginEdit(session)}
                      disabled={busy || isPending}
                    >
                      Rename
                    </button>
                    <button
                      type="button"
                      className="tale-delete"
                      onClick={() => handleDelete(session)}
                      disabled={busy || isPending}
                    >
                      Delete
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
