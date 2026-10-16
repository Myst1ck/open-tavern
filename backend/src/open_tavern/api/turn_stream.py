"""Turn persistence and SSE transport seams for the actions endpoint.

``persist_turn`` is the single storage call site for a completed turn: it
keeps the narration and the engine-resolved check rolls in one transaction so
a reloaded transcript can replay the results.

The streaming actions endpoint is implemented here in two seams:

* :func:`prepare_action` runs every pre-stream check (404/409/429/503) and
  reserves a slot on the bounded LLM executor. It raises ``HTTPException``
  *before* the response exists — once a streaming response has started its
  status can no longer change.
* :func:`stream_action` runs the turn on the dedicated executor and translates
  its progress into SSE frames. The executor task owns stream termination: it
  always emits exactly one terminal ``message``/``error`` frame, even when the
  client disconnects mid-stream — the turn still completes and persists.

Both seams use the shared validation helpers in :mod:`open_tavern.api.guards`,
the per-session locks and bounded executor in :mod:`open_tavern.api.runtime`,
and the per-request client protocol in :mod:`open_tavern.api.llm`. Unlike the
old ``routes`` module these have no import cycle with this module, so they are
imported at module level.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass

from fastapi import HTTPException, Request

from open_tavern.api import guards, runtime
from open_tavern.api.llm import ChatClient
from open_tavern.api.ratelimit import RateLimiter
from open_tavern.api.schemas import ActionResponse, roll_to_dict, state_to_dict
from open_tavern.storage import Storage
from open_tavern.story import RollOutcome, TurnResult, turn
from open_tavern.story.client import LLMClientError

#: Detail sent for an unexpected failure in the turn task. Deliberately
#: generic: the exception text can carry internal paths or payload fragments.
_INTERNAL_ERROR_DETAIL: str = "internal server error"

#: Seconds of idle wire time before a ``: keepalive`` comment frame is sent.
#: Phase 2 can be silent for minutes; comment frames keep read-timeout-happy
#: reverse proxies from severing the stream mid-turn. SSE clients ignore
#: comment-only frames.
_KEEPALIVE_S: float = 15.0


@dataclass(frozen=True)
class PreparedAction:
    """A validated action turn holding one executor slot until it completes.

    Built by :func:`prepare_action`; the slot it implies is released by the
    executor task's own ``finally``, never by the handler or the generator.
    """

    session_id: str
    action: str
    storage: Storage
    client: ChatClient
    kind: str = "act"


def persist_turn(
    storage: Storage,
    session_id: str,
    action: str,
    result: TurnResult,
) -> None:
    """Persist a completed turn, including its resolved check rolls."""
    storage.save_turn(
        session_id,
        result.state,
        action,
        result.narration,
        rolls=result.rolls,
    )


def _frame(event: str, payload: dict) -> bytes:
    """Encode one SSE frame with single-line JSON data."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode()


def _message_payload(result: TurnResult) -> dict:
    """Build the terminal ``message`` payload — the JSON ``ActionResponse`` body."""
    return ActionResponse(
        narration=result.narration,
        state=state_to_dict(result.state),
        rolls=[roll_to_dict(roll) for roll in result.rolls],
    ).model_dump()


async def prepare_action(
    *,
    session_id: str,
    action: str,
    storage: Storage,
    client: ChatClient,
    request: Request,
    limiter: RateLimiter,
    kind: str = "act",
) -> PreparedAction:
    """Validate a turn request and reserve an executor slot for it.

    Runs in the handler before the streaming response is constructed, so
    unknown sessions (404), sessions without a character (409), rate-limit
    violations (429), and executor saturation (503) all surface as plain HTTP
    status codes instead of a stream that starts and then dies.
    """
    await asyncio.to_thread(guards.ensure_session, storage, session_id)
    # The limiter records every hit, so it runs before the character check:
    # requests rejected with 409 must still consume the window, or a flood
    # of them is unthrottled.
    guards.enforce_rate_limit(request, limiter, "action")
    await asyncio.to_thread(guards.require_character, storage, session_id)
    if not runtime._LLM_EXECUTOR_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="server busy, try again shortly")
    return PreparedAction(
        session_id=session_id,
        action=action,
        storage=storage,
        client=client,
        kind=kind,
    )


def _run_locked(
    prepared: PreparedAction,
    on_rolls: Callable[[tuple[RollOutcome, ...]], None],
) -> TurnResult:
    """Run the turn and its persistence under the per-session lock.

    Runs on an executor worker. The lock-held section is identical to the
    pre-streaming implementation: state load, LLM turn, and atomic persistence
    so a crash cannot leave the state and the transcript diverging.
    """
    with runtime.session_lock_ctx(prepared.session_id):
        # Re-check under the lock: a delete queued ahead of this action would
        # otherwise surface as 409 (missing character) instead of 404.
        guards.ensure_session(prepared.storage, prepared.session_id)
        character = guards.require_character(prepared.storage, prepared.session_id)
        state = runtime.current_state(prepared.storage, prepared.session_id, character)
        history = prepared.storage.load_messages(prepared.session_id)
        premise = prepared.storage.session_premise(prepared.session_id)
        style = prepared.storage.session_dm_style(prepared.session_id)

        result = turn(
            prepared.action,
            state,
            history,
            prepared.client,
            premise=premise,
            style=style,
            kind=prepared.kind,
            on_rolls=on_rolls,
        )
        # State + both transcript messages commit as a single storage
        # transaction so a crash cannot leave state and transcript diverging.
        persist_turn(prepared.storage, prepared.session_id, prepared.action, result)
        runtime.cache_state(prepared.session_id, result.state)
    return result


def stream_action(prepared: PreparedAction) -> AsyncIterator[bytes]:
    """Stream the SSE frames for ``prepared`` up to its terminal frame.

    The blocking turn runs on the dedicated LLM executor. The executor task is
    submitted eagerly, before the response exists, so its ``finally`` releases
    the slot even if the stream is never read. Frames cross back to the event
    loop through a per-request ``asyncio.Queue`` so a stream never occupies a
    threadpool worker while phase 2 is pending. The executor task owns
    termination — exactly one ``message`` or ``error`` frame, followed by a
    ``None`` sentinel that ends the stream. Closing the stream (client
    disconnect) does not cancel the task: the turn always completes and
    persists, and a late frame put after the close is harmless.
    """
    loop = asyncio.get_running_loop()
    azq: asyncio.Queue[bytes | None] = asyncio.Queue()

    def _push(frame: bytes | None) -> None:
        with suppress(RuntimeError):  # event loop already closed at shutdown
            loop.call_soon_threadsafe(azq.put_nowait, frame)

    def _emit(event: str, payload: dict) -> None:
        _push(_frame(event, payload))

    def _on_rolls(rolls: tuple[RollOutcome, ...]) -> None:
        # Empty tuples are fired on no-check turns; the contract emits no
        # frame for them (the frontend never inserts an empty roll set).
        if rolls:
            _emit("roll", {"rolls": [roll_to_dict(roll) for roll in rolls]})

    def _run() -> None:
        # Single owner of stream termination: one terminal frame on every
        # path. The executor slot is released here — not in the handler or the
        # generator — so the worker stays accounted for while the turn runs
        # even if the client disconnects mid-stream.
        try:
            result = _run_locked(prepared, _on_rolls)
        except LLMClientError as exc:
            _emit("error", {"detail": str(exc), "status": 502})
        except HTTPException as exc:
            # Validation re-check under the lock (accepted TOCTOU race).
            _emit("error", {"detail": exc.detail, "status": exc.status_code})
        except Exception:
            _emit("error", {"detail": _INTERNAL_ERROR_DETAIL, "status": 500})
        else:
            _emit("message", _message_payload(result))
        finally:
            runtime._LLM_EXECUTOR_SLOTS.release()
            _push(None)

    async def _frames() -> AsyncIterator[bytes]:
        while True:
            try:
                frame = await asyncio.wait_for(azq.get(), timeout=_KEEPALIVE_S)
            except TimeoutError:
                yield b": keepalive\n\n"
                continue
            if frame is None:
                return
            yield frame

    try:
        runtime.LLM_EXECUTOR.submit(_run)
    except RuntimeError:  # executor already shut down
        runtime._LLM_EXECUTOR_SLOTS.release()
        _push(_frame("error", {"detail": "server shutting down", "status": 503}))
        _push(None)

    return _frames()
