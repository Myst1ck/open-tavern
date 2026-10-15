"""LLM client providers and the client-safe failure translation.

The providers are FastAPI dependencies: :func:`get_client` supplies the
environment-configured client and :func:`get_per_request_client` lets callers
override it per request through ``X-API-Key`` / ``X-Model`` / ``X-Base-Url``.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Protocol

from fastapi import Depends, Header, HTTPException

from open_tavern.story import OpenAIClient

logger = logging.getLogger(__name__)


class ChatClient(Protocol):
    """Structural interface for the LLM chat client used by the story engine."""

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str: ...


@lru_cache
def get_client() -> OpenAIClient:
    """Provide the LLM client, configured from environment variables."""
    return OpenAIClient()


def build_client_from_headers(
    api_key: str | None,
    model: str | None,
    base_url: str | None = None,
) -> OpenAIClient:
    """Build an LLM client from non-empty header values.

    Each non-empty value overrides the corresponding environment fallback inside
    :class:`OpenAIClient`; empty/absent values are dropped so the constructor's
    env-based defaults apply. A base URL CAN come from headers (``X-Base-Url``),
    but only together with a matching ``X-API-Key``: pairing a caller-chosen host
    with the environment's key would send this server's key to that host. When
    the base URL is absent/empty it falls back to ``OPENAI_BASE_URL`` (or the
    constructor default). Always returns a fresh, network-free client.
    """
    if base_url and not api_key:
        raise HTTPException(
            status_code=400,
            detail="X-Base-Url requires X-API-Key",
        )
    kwargs: dict[str, str] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if model:
        kwargs["model"] = model
    if base_url:
        kwargs["base_url"] = base_url
    try:
        return OpenAIClient(**kwargs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_per_request_client(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_model: str | None = Header(default=None, alias="X-Model"),
    x_base_url: str | None = Header(default=None, alias="X-Base-Url"),
    env_client: ChatClient = Depends(get_client),
) -> ChatClient:
    """Resolve the LLM client from per-request headers, else the env client.

    Non-empty ``X-API-Key``/``X-Model``/``X-Base-Url`` headers override the
    environment-configured :class:`OpenAIClient`; an absent/empty base URL falls
    back to ``OPENAI_BASE_URL``. Without any recognized header the shared
    environment client (or its dependency-override test fake) is used unchanged.

    Raises ``HTTPException`` 503 when the resolved client is a real
    :class:`OpenAIClient` with no API key — the app starts without a key, so
    only OpenAI-dependent requests fail until one is configured.
    """
    if not (x_api_key or x_model or x_base_url):
        client: ChatClient = env_client
    else:
        client = build_client_from_headers(x_api_key, x_model, x_base_url)
    if isinstance(client, OpenAIClient) and not client.api_key.strip():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY not configured",
        )
    return client


def llm_failure(exc: Exception) -> HTTPException:
    """Build the client-safe 502 returned when the upstream LLM call fails.

    The exception text is logged instead of echoed: httpx errors embed the
    request URL and the upstream response body, which would disclose the
    configured endpoint and provider details to any API caller.
    """
    logger.warning("LLM request failed: %s", exc)
    return HTTPException(status_code=502, detail="LLM request failed")
