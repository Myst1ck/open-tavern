"""OpenAIClient.chat error-path tests using httpx.MockTransport.

No real network: the module-level shared ``_HTTP_CLIENT`` is swapped for a
client backed by a MockTransport handler, so HTTP errors, timeouts, and
malformed responses are exercised deterministically.
"""

from __future__ import annotations

import json

import httpx
import pytest

import open_tavern.story.client as client_module
from open_tavern.story import OpenAIClient
from open_tavern.story.client import LLMClientError


def _client_with_transport(handler, monkeypatch) -> OpenAIClient:
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        client_module,
        "_HTTP_CLIENT",
        httpx.Client(transport=transport, timeout=60.0),
    )
    return OpenAIClient(api_key="test-key", base_url="http://127.0.0.1:8000/v1")


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": "Hello there."}}]}
    )


def test_chat_returns_content(monkeypatch):
    client = _client_with_transport(lambda request: _ok_response(), monkeypatch)

    content = client.chat([{"role": "user", "content": "hi"}])

    assert content == "Hello there."


def test_chat_json_mode_sends_response_format(monkeypatch):
    captured: dict = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return _ok_response()

    client = _client_with_transport(handler, monkeypatch)

    client.chat([{"role": "user", "content": "hi"}], json_mode=True)

    assert captured["body"]["response_format"] == {"type": "json_object"}


def test_chat_http_error_raises_llm_client_error(monkeypatch):
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    client = _client_with_transport(handler, monkeypatch)

    with pytest.raises(LLMClientError, match="LLM request failed"):
        client.chat([{"role": "user", "content": "hi"}])


def test_chat_timeout_raises_llm_client_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("timed out")

    client = _client_with_transport(handler, monkeypatch)

    with pytest.raises(LLMClientError, match="LLM request failed"):
        client.chat([{"role": "user", "content": "hi"}])


def test_chat_transport_error_raises_llm_client_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    client = _client_with_transport(handler, monkeypatch)

    with pytest.raises(LLMClientError, match="LLM request failed"):
        client.chat([{"role": "user", "content": "hi"}])


def test_chat_invalid_json_body_raises_llm_client_error(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="not json")

    client = _client_with_transport(handler, monkeypatch)

    with pytest.raises(LLMClientError, match="LLM request failed"):
        client.chat([{"role": "user", "content": "hi"}])


def test_chat_missing_content_raises_llm_client_error(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    client = _client_with_transport(handler, monkeypatch)

    with pytest.raises(LLMClientError, match="LLM response missing content"):
        client.chat([{"role": "user", "content": "hi"}])