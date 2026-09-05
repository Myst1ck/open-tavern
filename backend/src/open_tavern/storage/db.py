"""SQLite persistence for sessions, characters, and messages.

Uses the standard-library ``sqlite3`` module (no ORM). A single connection is
held for the lifetime of a :class:`Storage` instance so that ``:memory:``
databases survive across method calls. All SQL is parameterized — values are
never interpolated into query strings.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from open_tavern.character import CharacterSheet, normalize
from open_tavern.character.items import Item
from open_tavern.state import GameState, state_from_persistable, state_to_persistable

#: Current schema version, tracked in the ``meta`` table.
#:
#: Version history:
#:   * 1 — original layout: ``sessions``/``characters``/``messages`` tables,
#:     unversioned (no ``meta`` table). Version-1 saves are INCOMPATIBLE
#:     with the current schema: when ``init`` meets a legacy database (meta
#:     row missing), the data tables are dropped and recreated — old saves
#:     are deleted, never preserved, backfilled, or migrated.
#:   * 2 — this change: adds the ``meta`` table with a ``schema_version`` row
#:     so incompatible layouts are detected and dropped/recreated.
SCHEMA_VERSION: int = 3

#: ``meta`` row key holding the schema version written by :meth:`Storage.init`.
_SCHEMA_VERSION_KEY: str = "schema_version"

#: DDL for the version-tracking table. Must exist before version can be read.
_META_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

#: DDL for all data tables. ``IF NOT EXISTS`` keeps ``init`` idempotent.
_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    world_theme TEXT NOT NULL,
    title TEXT,
    updated_at TEXT,
    state_json TEXT
);

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    data_json TEXT NOT NULL,
    character_name TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_items_session ON items(session_id, character_id);
"""


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


class Storage:
    """Thin, thread-unsafe wrapper around a single SQLite connection."""

    def __init__(self, db_path: str) -> None:
        # ``check_same_thread=False`` lets the single connection be used from
        # FastAPI's threadpool workers; access is serialized by ``self._lock``.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def init(self) -> None:
        """Create tables if needed, then ensure the schema is current.

        Behavior depends on the stored ``schema_version``:

        * no ``meta`` row + no tables — brand-new database: create schema,
          record ``SCHEMA_VERSION``.
        * no ``meta`` row + tables present — unversioned legacy database with
          incompatible version-1 saves: drop and recreate the data tables
          (destructive, approved), record ``SCHEMA_VERSION``.
        * stored version == ``SCHEMA_VERSION`` — no-op (idempotent).
        * stored version != ``SCHEMA_VERSION`` — versioned mismatch: layout is
          old (or from a newer build) and incompatible, so the data tables are
          dropped and recreated, then the version recorded.
        """
        with self._lock, self._conn:
            # The meta table must exist before the version can be read.
            self._conn.executescript(_META_SCHEMA)
            version = self._read_schema_version()
            if version == SCHEMA_VERSION:
                # Already migrated; run the idempotent DDL as a repair.
                self._conn.executescript(_SCHEMA)
                return
            if version is None and not self._table_exists("sessions"):
                # Brand-new database: nothing to drop.
                self._conn.executescript(_SCHEMA)
                self._write_schema_version()
                return
            # Destructive path: legacy unversioned DB or versioned
            # mismatch. Old/incompatible saves are deleted (approved).
            self._conn.executescript(
                "DROP TABLE IF EXISTS sessions;"
                "DROP TABLE IF EXISTS characters;"
                "DROP TABLE IF EXISTS messages;"
                "DROP TABLE IF EXISTS items;"
            )
            self._conn.executescript(_SCHEMA)
            self._write_schema_version()

    def _table_exists(self, name: str) -> bool:
        """Return ``True`` if a table named ``name`` exists in this database."""
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def _read_schema_version(self) -> int | None:
        """Return the stored schema version, or ``None`` if no row exists.

        An unparseable stored value is treated as ``0`` so it fails the
        version check and takes the destructive path.
        """
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (_SCHEMA_VERSION_KEY,)
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def _write_schema_version(self) -> None:
        """Upsert the current schema version into the ``meta`` table."""
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_SCHEMA_VERSION_KEY, str(SCHEMA_VERSION)),
        )

    # ── Items ────────────────────────────────────────────────────────────────

    def save_item(self, session_id: str, character_id: str, item: Item) -> None:
        """INSERT OR REPLACE ``item`` for ``session_id`` + ``character_id``."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO items (id, session_id, character_id, item_json) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "item_json = excluded.item_json",
                (item.id, session_id, character_id, json.dumps(item.to_dict())),
            )

    def load_items(self, session_id: str, character_id: str) -> list[Item]:
        """Return all items for ``session_id`` + ``character_id``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT item_json FROM items WHERE session_id = ? AND character_id = ?",
                (session_id, character_id),
            ).fetchall()
        return [Item.from_dict(json.loads(r["item_json"])) for r in rows]

    def load_item(
        self, session_id: str, character_id: str, item_id: str
    ) -> Item | None:
        """Return single item by id, or ``None``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT item_json FROM items "
                "WHERE session_id = ? AND character_id = ? AND id = ?",
                (session_id, character_id, item_id),
            ).fetchone()
        if row is None:
            return None
        return Item.from_dict(json.loads(row["item_json"]))

    def delete_item(self, session_id: str, character_id: str, item_id: str) -> bool:
        """Delete item by id. Return ``True`` if a row was removed."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM items "
                "WHERE session_id = ? AND character_id = ? AND id = ?",
                (session_id, character_id, item_id),
            )
        return cur.rowcount > 0

    def update_item(self, session_id: str, character_id: str, item: Item) -> None:
        """Update ``item_json`` for existing item (matched by id)."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE items SET item_json = ? "
                "WHERE session_id = ? AND character_id = ? AND id = ?",
                (json.dumps(item.to_dict()), session_id, character_id, item.id),
            )

    def close(self) -> None:
        """Close the underlying connection. Safe to call more than once."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Storage:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def create_session(self, world_theme: str, title: str | None = None) -> str:
        """Persist a new session and return its unique id.

        ``title`` defaults to ``world_theme`` when omitted or empty.
        """
        session_id = uuid4().hex
        now = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions "
                "(id, created_at, world_theme, title, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, now, world_theme, title or world_theme, now),
            )
        return session_id

    def save_state(self, session_id: str, state: GameState) -> None:
        """Persist ``state`` for ``session_id`` and bump ``updated_at``.

        Only the persistable projection is stored (character is kept separately
        via :meth:`save_character`).
        """
        data_json = json.dumps(state_to_persistable(state))
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET state_json = ?, updated_at = ? WHERE id = ?",
                (data_json, _now_iso(), session_id),
            )

    def load_state(
        self, session_id: str, character: CharacterSheet
    ) -> GameState | None:
        """Rebuild the saved :class:`GameState`, or ``None`` if absent.

        ``character`` is the normalized sheet (see :meth:`load_character`);
        ``state_from_persistable`` never trusts stored numbers.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None or row["state_json"] is None:
                return None
            return state_from_persistable(character, json.loads(row["state_json"]))

    def list_sessions(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Return summary rows ordered by ``updated_at`` descending.

        Each row is ``{id, title, world_theme, created_at, updated_at,
        character_name}``; ``character_name`` is pulled from the joined
        character's ``character_name`` column (``None`` when no character saved).
        ``limit`` caps the result size (default 50) and ``offset`` pages
        through it, so the query stays bounded on large databases.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT s.id, s.title, s.world_theme, s.created_at, s.updated_at, "
                "c.character_name AS character_name "
                "FROM sessions AS s "
                "LEFT JOIN characters AS c ON c.session_id = s.id "
                "ORDER BY s.updated_at DESC "
                "LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            result: list[dict] = []
            for row in rows:
                result.append(
                    {
                        "id": row["id"],
                        "title": row["title"] or row["world_theme"],
                        "world_theme": row["world_theme"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"] or row["created_at"],
                        "character_name": row["character_name"],
                    }
                )
        return result

    def rename_session(self, session_id: str, title: str) -> bool:
        """Set ``title`` for ``session_id``; return ``True`` if a row changed."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now_iso(), session_id),
            )
        return cur.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        """Delete a session and its character, messages, and items.

        ``state_json`` lives on the ``sessions`` row so it is removed with it.
        Returns ``True`` if the session existed.
        """
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            existed = cur.rowcount > 0
            if existed:
                self._conn.execute(
                    "DELETE FROM characters WHERE session_id = ?", (session_id,)
                )
                self._conn.execute(
                    "DELETE FROM messages WHERE session_id = ?", (session_id,)
                )
                self._conn.execute(
                    "DELETE FROM items WHERE session_id = ?", (session_id,)
                )
        return existed

    def touch_session(self, session_id: str) -> None:
        """Set ``updated_at`` to now for ``session_id``."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (_now_iso(), session_id),
            )

    def save_character(self, session_id: str, character: CharacterSheet) -> None:
        """Serialize ``character`` to JSON and upsert it for ``session_id``."""
        data_json = json.dumps(asdict(character))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO characters (session_id, data_json, character_name) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "data_json = excluded.data_json, "
                "character_name = excluded.character_name",
                (session_id, data_json, character.name or None),
            )

    def load_character(self, session_id: str) -> CharacterSheet | None:
        """Reconstruct the character for ``session_id``, or ``None``.

        Rebuilds via :func:`open_tavern.character.normalize` so every derived
        value is recomputed from raw data rather than trusted from storage.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT data_json FROM characters WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return normalize(json.loads(row["data_json"]))

    def append_message(self, session_id: str, role: str, content: str) -> None:
        """Persist a single chat message for ``session_id``."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, content, _now_iso()),
            )

    def load_messages(self, session_id: str) -> list[dict]:
        """Return the most recent messages for ``session_id`` in insertion order.

        The story engine keeps at most 20 recent turns in its prompt history
        (``story.game._MAX_HISTORY_MESSAGES``), so only that window is fetched:
        rows are selected newest-first and reversed in Python, avoiding an
        unbounded read of the whole transcript.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT 20",
                (session_id,),
            ).fetchall()
        return [
            {"role": row["role"], "content": row["content"]} for row in reversed(rows)
        ]

    def session_exists(self, session_id: str) -> bool:
        """Return ``True`` if a session row with ``session_id`` exists.

        Existence check without loading the character JSON or transcript, so
        endpoint guards stay O(1) instead of issuing three queries.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def character_exists(self, session_id: str) -> bool:
        """Return ``True`` if a character row exists for ``session_id``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM characters WHERE session_id = ?", (session_id,)
            ).fetchone()
        return row is not None

    def load_session(self, session_id: str) -> dict | None:
        """Return full session state, or ``None`` if the session is unknown."""
        with self._lock:
            row = self._conn.execute(
                "SELECT world_theme FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "world_theme": row["world_theme"],
                "character": self.load_character(session_id),
                "messages": self.load_messages(session_id),
            }

    def session_summary(self, session_id: str) -> dict | None:
        """Return a single session summary row, or ``None`` if unknown."""
        with self._lock:
            row = self._conn.execute(
                "SELECT s.id, s.title, s.world_theme, s.created_at, s.updated_at, "
                "c.character_name AS character_name "
                "FROM sessions AS s "
                "LEFT JOIN characters AS c ON c.session_id = s.id "
                "WHERE s.id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"] or row["world_theme"],
            "world_theme": row["world_theme"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"] or row["created_at"],
            "character_name": row["character_name"],
        }
