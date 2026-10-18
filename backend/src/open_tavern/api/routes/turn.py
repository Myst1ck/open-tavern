"""Player-action endpoint that advances a session's story."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse

from open_tavern.api import guards, turn_stream
from open_tavern.api.llm import ChatClient, get_per_request_client
from open_tavern.api.runtime import get_storage
from open_tavern.api.schemas import ActionRequest
from open_tavern.storage import Storage

router = APIRouter()


@router.post(
    "/sessions/{session_id}/actions",
    response_class=Response,
    responses={
        200: {
            "description": (
                "SSE stream: roll frames, then exactly one terminal "
                "message or error frame."
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def send_action(
    session_id: str,
    body: ActionRequest,
    request: Request,
    storage: Storage = Depends(get_storage),
    client: ChatClient = Depends(get_per_request_client),
) -> StreamingResponse:
    """Stream a player action turn as Server-Sent Events.

    Pre-stream validation (404/409/429) and executor-slot reservation (503)
    happen in :func:`turn_stream.prepare_action`, before the response exists,
    so those failures stay plain HTTP status codes. The rate limiter records
    its hit before the character check, so 409 responses still consume the
    window. Once the stream opens, the turn runs on the bounded executor and
    reports progress as ``roll`` frames followed by exactly one terminal
    ``message`` or ``error`` frame — see :mod:`open_tavern.api.turn_stream`.
    """
    prepared = await turn_stream.prepare_action(
        session_id=session_id,
        action=body.action,
        storage=storage,
        client=client,
        request=request,
        limiter=guards.action_limiter,
        kind=body.kind,
    )
    return StreamingResponse(
        turn_stream.stream_action(prepared),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
