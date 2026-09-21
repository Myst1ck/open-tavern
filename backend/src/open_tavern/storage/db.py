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
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from open_tavern.character import CharacterSheet, normalize
from open_tavern.character.items import BaseType, Item
from open_tavern.state import GameState, state_from_persistable, state_to_persistable

#: Current schema version, tracked in the ``meta`` table.
#:
#: Version history:
#:   * 1 — original layout: ``sessions``/``characters``/``messages`` tables,
#:     unversioned (no ``meta`` table).
#:   * 2 — adds the ``meta`` table with a ``schema_version`` row.
#:   * 3 — adds the ``items`` table.
#:   * 4 — adds session metadata columns (``premise``, ``title``,
#:     ``updated_at``, ``state_json``).
#:
#: Older databases are migrated forward step by step (see ``_MIGRATIONS``);
#: databases from a newer build are refused, never dropped.
SCHEMA_VERSION: int = 4


class SchemaTooNewError(RuntimeError):
    """Raised when a database's schema version is newer than this build supports.

    Opening such a database could risk data loss, so :meth:`Storage.init`
    refuses instead of dropping or silently proceeding.
    """

#: ``meta`` row key holding the schema version written by :meth:`Storage.init`.
_SCHEMA_VERSION_KEY: str = "schema_version"

#: Maximum number of messages :meth:`Storage.load_messages` returns per call.
#:
#: Configurable: raise or lower this module constant to change the transcript
#: window without touching the ``load_messages`` signature or any callers.
MESSAGE_LOAD_LIMIT: int = 500

#: DDL for the version-tracking table. Must exist before version can be read.
_META_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

#: DDL for the items table (schema v3). Kept separate so the migration step
#: and the full schema share one definition.
_ITEMS_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    item_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_items_session ON items(session_id, character_id);
"""

#: DDL for all data tables. ``IF NOT EXISTS`` keeps ``init`` idempotent.
_SCHEMA: str = f"""
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    world_theme TEXT NOT NULL,
    premise TEXT,
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

{_ITEMS_SCHEMA}

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _add_session_columns(conn: sqlite3.Connection) -> None:
    """Add the schema-v4 session metadata columns (idempotent).

    ``ALTER TABLE ADD COLUMN`` fails if the column already exists, so each
    column is added only when missing. Column names come from a fixed tuple,
    never from user input.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    for name, ddl in (
        ("premise", "premise TEXT"),
        ("title", "title TEXT"),
        ("updated_at", "updated_at TEXT"),
        ("state_json", "state_json TEXT"),
    ):
        if name not in existing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {ddl}")


#: Ordered schema migrations. Each entry is ``(version, step)``: ``version``
#: is the schema version the step produces, ``step`` is either SQL (run via
#: ``executescript``) or a callable taking the connection. Steps run in list
#: order; a database at version N is brought to the current version by
#: applying every step whose version is greater than N.
_MIGRATIONS: list[tuple[int, str | Callable[[sqlite3.Connection], None]]] = [
    (2, _META_SCHEMA),  # 1 -> 2: version tracking
    (3, _ITEMS_SCHEMA),  # 2 -> 3: items table
    (4, _add_session_columns),  # 3 -> 4: session metadata columns
]


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _json_default(obj: object) -> object:
    """Serialize non-JSON-native values produced by :func:`dataclasses.asdict`.

    ``asdict`` keeps :class:`BaseType` enum members (and nested :class:`Item`
    dataclasses) intact, which ``json.dumps`` cannot encode. Enums become their
    string value; items become their ``to_dict`` projection. Both round-trip
    through :func:`open_tavern.character.normalize` on load.
    """
    if isinstance(obj, BaseType):
        return obj.value
    if isinstance(obj, Item):
        return obj.to_dict()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


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

        * no ``meta`` row + no tables — brand-new database: create the
          current schema directly and record ``SCHEMA_VERSION``.
        * no ``meta`` row + tables present — unversioned legacy (v1)
          database: migrate forward through every step in ``_MIGRATIONS``.
        * stored version == ``SCHEMA_VERSION`` — no-op (idempotent).
        * stored version < ``SCHEMA_VERSION`` — migrate forward: apply each
          ``_MIGRATIONS`` step with a version greater than the stored one,
          in order. No data is dropped.
        * stored version > ``SCHEMA_VERSION`` — database from a newer build:
          raise :class:`SchemaTooNewError` instead of opening it.
        """
        with self._lock, self._conn:
            # The meta table must exist before the version can be read.
            self._conn.executescript(_META_SCHEMA)
            version = self._read_schema_version()
            if version is None and not self._table_exists("sessions"):
                # Brand-new database: current schema directly, no replay.
                self._conn.executescript(_SCHEMA)
                self._write_schema_version()
                return
            if version is None:
                # Unversioned legacy (v1) database: migrate from v1.
                version = 1
            if version > SCHEMA_VERSION:
                raise SchemaTooNewError(
                    f"Database schema version {version} is newer than the "
                    f"supported version {SCHEMA_VERSION}; refusing to open."
                )
            if version == SCHEMA_VERSION:
                # Already current; run the idempotent DDL as a repair.
                self._conn.executescript(_SCHEMA)
                return
            # Migrate forward, oldest step first. Never drops data.
            for step_version, step in _MIGRATIONS:
                if step_version > version:
                    if callable(step):
                        step(self._conn)
                    else:
                        self._conn.executescript(step)
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

        An unparseable stored value is treated as ``0`` so it migrates from
        the earliest version rather than erroring.
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

    def create_session(
        self,
        world_theme: str,
        title: str | None = None,
        premise: str | None = None,
    ) -> str:
        """Persist a new session and return its unique id.

        ``title`` defaults to ``world_theme`` when omitted or empty.
        ``premise`` is an optional LLM-generated story premise for the
        campaign setting.
        """
        session_id = uuid4().hex
        now = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO sessions "
                "(id, created_at, world_theme, premise, title, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, now, world_theme, premise, title or world_theme, now),
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

    def save_turn(
        self,
        session_id: str,
        state: GameState,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Persist one completed turn atomically.

        Writes the updated game state and both transcript messages (player
        action + GM narration) in a single transaction, so a crash between
        writes can never leave the state and the transcript diverging (e.g.
        state advanced while the player's message was lost). Bumps
        ``updated_at`` like :meth:`save_state`.
        """
        data_json = json.dumps(state_to_persistable(state))
        now = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE sessions SET state_json = ?, updated_at = ? WHERE id = ?",
                (data_json, now, session_id),
            )
            self._conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, "user", user_message, now),
            )
            self._conn.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, "assistant", assistant_message, now),
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
        data_json = json.dumps(asdict(character), default=_json_default)
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

        Rows are selected newest-first and reversed in Python, avoiding an
        unbounded read of the whole transcript. The window size is bounded by
        :data:`MESSAGE_LOAD_LIMIT` (default 500); adjust that module constant
        to change the limit — the signature stays stable.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, MESSAGE_LOAD_LIMIT),
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
                "SELECT world_theme, premise FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "world_theme": row["world_theme"],
                "premise": row["premise"],
                "character": self.load_character(session_id),
                "messages": self.load_messages(session_id),
            }

    def session_premise(self, session_id: str) -> str | None:
        """Return the stored ``premise`` for ``session_id``, or ``None``.

        Single-column probe for the action path, which only needs the premise
        and must not pay for the full character JSON and transcript that
        :meth:`load_session` loads.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT premise FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if row is None:
            return None
        return row["premise"]

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
