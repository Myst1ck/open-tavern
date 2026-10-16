"""OpenAIClient.chat error-path tests using httpx.MockTransport.

No real network: the module-level shared ``_HTTP_CLIENT`` is swapped for a
client backed by a MockTransport handler, so HTTP errors, timeouts, and
malformed responses are exercised deterministically.
"""

from __future__ import annotations

import json
import socket

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


def test_chat_revalidates_host_and_refuses_newly_blocked_address(monkeypatch):
    resolving = {"on": False}

    def fake_getaddrinfo(host, *args, **kwargs):
        if not resolving["on"]:
            raise OSError(f"no DNS for {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(client_module.socket, "getaddrinfo", fake_getaddrinfo)
    # Construction allows the unresolvable host...
    client = OpenAIClient(api_key="test-key", base_url="http://llm.example/v1")
    # ...but the send-time re-check must refuse it once it resolves to a
    # blocked address (late DNS resolution / rebinding).
    resolving["on"] = True

    with pytest.raises(LLMClientError, match="not allowed"):
        client.chat([{"role": "user", "content": "hi"}])
def test_base_url_bare_openrouter_host_maps_to_api_root():
    client = OpenAIClient(api_key="test-key", base_url="https://openrouter.ai")

    assert client.base_url == "https://openrouter.ai/api/v1"


def test_base_url_openrouter_trailing_slash_maps_to_api_root():
    client = OpenAIClient(api_key="test-key", base_url="https://openrouter.ai/")

    assert client.base_url == "https://openrouter.ai/api/v1"


def test_base_url_with_path_unchanged():
    client = OpenAIClient(api_key="test-key", base_url="https://openrouter.ai/api/v1")

    assert client.base_url == "https://openrouter.ai/api/v1"


def test_base_url_other_provider_unchanged():
    client = OpenAIClient(api_key="test-key", base_url="https://api.openai.com/v1")

    assert client.base_url == "https://api.openai.com/v1"


def test_chat_targets_openrouter_api_root(monkeypatch):
    captured: dict = {}

    def handler(request):
        captured["url"] = str(request.url)
        return _ok_response()

    monkeypatch.setattr(
        client_module,
        "_HTTP_CLIENT",
        httpx.Client(transport=httpx.MockTransport(handler), timeout=60.0),
    )
    client = OpenAIClient(api_key="test-key", base_url="https://openrouter.ai")

    client.chat([{"role": "user", "content": "hi"}])

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
