"""OpenAI-compatible chat completions client.

A thin ``httpx`` wrapper over ``POST {base_url}/chat/completions``. Every
dependency (API key, base URL, model) is injectable via the constructor and
falls back to environment variables, so tests can substitute a fake client and
never touch the network.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

import httpx

DEFAULT_BASE_URL: str = "https://api.openai.com/v1"
DEFAULT_MODEL: str = "gpt-4o-mini"
DEFAULT_TEMPERATURE: float = 0.7

#: Networks never reachable by a legitimate LLM endpoint. Blocking these closes
#: the highest-value SSRF targets (cloud metadata, link-local, unspecified,
#: multicast) while leaving private/loopback hosts allowed for local models such
#: as Ollama.
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("169.254.0.0/16"),  # link-local incl. 169.254.169.254
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::/128"),  # unspecified
    ipaddress.ip_network("fe80::/10"),  # link-local
    ipaddress.ip_network("ff00::/8"),  # multicast
)


def _check_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return ``True`` if ``addr`` (or its IPv4-mapped form) is blocked.

    Handles IPv4-mapped IPv6 literals (e.g. ``::ffff:169.254.169.254``) by
    falling back to the embedded IPv4 address before matching.
    """
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    for network in _BLOCKED_NETWORKS:
        if addr.version == network.version and addr in network:
            return True
    return False


def _validate_base_url(url: str) -> None:
    """Reject base URLs that could be abused for SSRF.

    Requires an ``http``/``https`` scheme and blocks link-local/reserved IP
    literals (notably cloud metadata ``169.254.169.254``), including their
    IPv4-mapped IPv6 forms. Hostnames are resolved now and every resolved
    address is checked, closing static DNS-rebinding (a hostile DNS server
    could still rebind after this check — see the residual TOCTOU note).
    Private and loopback ranges are intentionally allowed so local models
    keep working. Raises ``ValueError`` for anything rejected.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ValueError(f"invalid base URL: {url!r}") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"base URL must be an absolute http(s) URL: {url!r}")
    try:
        addr = ipaddress.ip_address(parts.hostname)
    except ValueError:
        # Hostname, not an IP literal — resolve and validate every address now.
        try:
            infos = socket.getaddrinfo(parts.hostname, None)
        except OSError:
            return  # unresolvable — allow; revalidated at request time
        for info in infos:
            if _check_ip(ipaddress.ip_address(info[4][0])):
                raise ValueError(f"base URL host {parts.hostname!r} is not allowed") from None
        return
    if _check_ip(addr):
        raise ValueError(f"base URL host {parts.hostname!r} is not allowed")


class LLMClientError(RuntimeError):
    """Raised when an LLM request fails or returns a malformed response."""


class OpenAIClient:
    """Minimal OpenAI-compatible chat completions client."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        )
        self.base_url = (
            base_url
            if base_url is not None
            else os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        _validate_base_url(self.base_url)
        self.model = (
            model
            if model is not None
            else os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = DEFAULT_TEMPERATURE,
        json_mode: bool = False,
    ) -> str:
        """Send ``messages`` and return the assistant's message content string."""
        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMClientError(f"LLM request failed: {exc}") from exc
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError("LLM response missing content") from exc
