"""Process-lifetime runtime state for the API.

Owns the storage provider, the bounded LLM executor, the in-memory cache of live
game state, the per-session locks, and the shutdown hook the app lifespan calls
to release them. No FastAPI routes live here.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache

from fastapi import HTTPException

from open_tavern.character import CharacterSheet
from open_tavern.state import GameState, new_state
from open_tavern.storage import Storage

#: The storage instance last handed out by :func:`get_storage`, if any.
#: Tracked so :func:`shutdown_runtime` can close exactly that connection:
#: ``lru_cache`` offers no way to read its cached value back, and calling the
#: provider at shutdown would open a second database instead.
open_storage: Storage | None = None


@lru_cache
def get_storage() -> Storage:
    """Provide the storage layer, opening the SQLite database from env."""
    global open_storage
    store = Storage(os.environ.get("OPEN_TAVERN_DB", "open_tavern.db"))
    store.init()
    open_storage = store
    return store


#: In-memory LRU cache of live :class:`GameState` keyed by session id.
#:
#: Storage persists the running state via ``save_state``/``load_state``, so the
#: cache only avoids re-reading it on every request. Written through by the
#: mutation paths under the per-session lock, never filled by reads (see
#: :func:`current_state`), so a read racing a write cannot poison it with a
#: stale snapshot. Capped at ``STATE_CACHE_MAXLEN`` entries (oldest evicted)
#: so long-running servers cannot grow it unbounded. Guarded by ``STATE_LOCK``
#: so concurrent requests cannot race; all access must go through that lock.
STATE_CACHE_MAXLEN: int = 100
STATE_CACHE: OrderedDict[str, GameState] = OrderedDict()
STATE_LOCK = threading.Lock()


def cache_state(session_id: str, state: GameState) -> None:
    """Store ``state`` for ``session_id``, evicting the oldest entry when full."""
    with STATE_LOCK:
        STATE_CACHE[session_id] = state
        STATE_CACHE.move_to_end(session_id)
        if len(STATE_CACHE) > STATE_CACHE_MAXLEN:
            STATE_CACHE.popitem(last=False)


def invalidate_state(session_id: str) -> None:
    """Drop ``session_id`` from the state cache if present."""
    with STATE_LOCK:
        STATE_CACHE.pop(session_id, None)


def current_state(
    storage: Storage, session_id: str, character: CharacterSheet
) -> GameState:
    """Return the live state for a session.

    Prefer the in-memory cache; on a cache miss load the persisted state from
    storage, falling back to a fresh :func:`new_state` when nothing was saved.
    The cache is written through only by the mutation paths (which hold the
    per-session lock); reads never fill it, so a read racing a write cannot
    poison the cache with a stale snapshot.
    """
    with STATE_LOCK:
        cached = STATE_CACHE.get(session_id)
        if cached is not None:
            STATE_CACHE.move_to_end(session_id)
    if cached is not None:
        return cached
    persisted = storage.load_state(session_id, character)
    if persisted is not None:
        return persisted
    return new_state(character)


#: Per-session locks serialize read-modify-write of a single session's state so
#: concurrent actions cannot lose updates. Keyed by session id.
#: Entries use ``(lock, refcount)`` tuples — the lock is only deleted when no
#: thread is waiting or holding it (refcount == 0), preventing the
#: replacement-race where a new lock is created while a waiter still holds
#: the old one.
SESSION_LOCKS: dict[str, tuple[threading.Lock, int]] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def session_lock(session_id: str) -> threading.Lock:
    """Return the per-session lock for ``session_id``, incrementing the refcount."""
    with _SESSION_LOCKS_GUARD:
        entry = SESSION_LOCKS.get(session_id)
        if entry is None:
            lock = threading.Lock()
            SESSION_LOCKS[session_id] = (lock, 1)
            return lock
        lock, refcount = entry
        SESSION_LOCKS[session_id] = (lock, refcount + 1)
        return lock


@contextmanager
def session_lock_ctx(session_id: str):
    """Acquire the per-session lock and decrement the refcount on exit.

    The lock mapping is only removed when the refcount drops to zero, so
    a thread still queued on the lock will not see its lock replaced.
    """
    lock = session_lock(session_id)
    try:
        with lock:
            yield
    finally:
        with _SESSION_LOCKS_GUARD:
            entry = SESSION_LOCKS.get(session_id)
            if entry is not None:
                lock_obj, refcount = entry
                if lock_obj is lock:
                    if refcount <= 1:
                        SESSION_LOCKS.pop(session_id, None)
                    else:
                        SESSION_LOCKS[session_id] = (lock, refcount - 1)


#: Dedicated bounded executor for blocking LLM + storage work.
#:
#: LLM calls can block for up to the client timeout (60 s — see
#: ``story.client.DEFAULT_TIMEOUT``). Running them on
#: FastAPI's shared threadpool would let ~40 concurrent generations exhaust
#: every worker and stall even cheap GETs (healthcheck). The async LLM
#: handlers dispatch that work here instead; the semaphore below rejects
#: with 503 as soon as all workers are busy, so the queue never grows
#: unbounded. Slot count matches worker count exactly.
LLM_EXECUTOR_MAX_WORKERS: int = 16
LLM_EXECUTOR = ThreadPoolExecutor(
    max_workers=LLM_EXECUTOR_MAX_WORKERS,
    thread_name_prefix="open-tavern-llm",
)
_LLM_EXECUTOR_SLOTS = threading.BoundedSemaphore(LLM_EXECUTOR_MAX_WORKERS)


async def run_llm_task[T](fn: Callable[[], T]) -> T:
    """Run blocking LLM/storage work on the dedicated bounded executor.

    Raises 503 immediately when every worker is busy instead of queueing the
    request behind an unbounded wait. The submitted function always runs to
    completion (even if the awaiting coroutine is cancelled); the slot is
    released in ``finally`` either way.
    """
    if not _LLM_EXECUTOR_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="server busy, try again shortly")
    try:
        return await asyncio.get_running_loop().run_in_executor(LLM_EXECUTOR, fn)
    finally:
        _LLM_EXECUTOR_SLOTS.release()


def shutdown_runtime() -> None:
    """Release this module's process-lifetime resources.

    Called from the app lifespan on shutdown. Without it a ``SIGTERM`` waits
    for in-flight executor work (up to the 60 s LLM timeout) before the
    interpreter exits, and the SQLite connection is only reclaimed by process
    exit rather than closed.
    """
    LLM_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    storage = open_storage
    if storage is not None:
        storage.close()
    with STATE_LOCK:
        STATE_CACHE.clear()
