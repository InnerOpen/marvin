"""Core implementation of the SDK's HttpHelper — the safe HTTP client handed to providers.

Also core's own guarded client for outbound fetches that aren't integrations (media-embed oEmbed
lookups), so it must import without the optional ``marvin_integration_sdk``.

Enforces timeouts, a response-size cap (INTEGRATION_HTTP_MAX_BYTES), and an SSRF guard (refuses to call private/loopback/
link-local/reserved hosts, and re-checks on redirect). Providers get safe outbound HTTP for free.
"""

import http.client
import ipaddress
import socket
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from marvin.core.config import get_app_settings

try:  # the SDK's Response when integrations are installed, so providers get exactly the type they import
    from marvin_integration_sdk.http import Response
except ImportError:  # core features (media embeds) use this client without the optional SDK
    import json as _json
    from dataclasses import dataclass, field
    from typing import Any

    @dataclass
    class Response:  # type: ignore[no-redef]
        """Same shape as ``marvin_integration_sdk.http.Response``: status, headers, raw bytes."""

        status_code: int
        headers: dict[str, str] = field(default_factory=dict)
        content: bytes = b""

        @property
        def ok(self) -> bool:
            return 200 <= self.status_code < 300

        @property
        def text(self) -> str:
            return self.content.decode("utf-8", "replace")

        def json(self) -> Any:
            return _json.loads(self.content)


# urllib's default "Python-urllib/x.y" is refused outright by Cloudflare's bot rules (error 1010), so
# a provider fetching anything behind Cloudflare — including this install's own public asset URLs —
# would get a 403. A named agent also tells the far side who is calling.
USER_AGENT = "marvin-cms/integrations"


class SsrfError(ValueError):
    """Raised when a request target is not a permitted public host."""


def _host_is_public(host: str) -> bool:
    """True only if every address the host resolves to is a global/public IP."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


def _guard(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"Only http(s) URLs are allowed (got {parsed.scheme!r}).")
    if not parsed.hostname:
        raise SsrfError("URL has no host.")
    if not _host_is_public(parsed.hostname):
        raise SsrfError(f"Refusing to call non-public host {parsed.hostname!r}.")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-run the SSRF guard on every redirect target — a redirect must not smuggle in a private host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _guard(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


RETRY_PAUSE_SECONDS = 2.0
"""How long a GET waits before its one retry after a network blip."""

_TRANSIENT = (TimeoutError, ConnectionResetError, ConnectionAbortedError, http.client.RemoteDisconnected, http.client.IncompleteRead)


def is_transient_network_error(exc: BaseException | None) -> bool:
    """A network blip rather than a real failure: the remote didn't answer in time or dropped the connection —
    directly, wrapped in urllib's URLError, or as the cause of what a provider raised. Not an HTTP error status, a
    refused connection, a DNS failure or an SSRF refusal: those say something is actually wrong."""
    seen = 0
    while exc is not None and seen < 5:
        if isinstance(exc, _TRANSIENT):
            return True
        if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, _TRANSIENT):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


class MarvinHttpHelper:
    """Implements ``marvin_integration_sdk.http.HttpHelper``."""

    def __init__(self, max_bytes: int | None = None) -> None:
        self._opener = urllib.request.build_opener(_GuardedRedirectHandler())
        self._max_bytes = get_app_settings().INTEGRATION_HTTP_MAX_BYTES if max_bytes is None else max_bytes

    def _send(self, req: urllib.request.Request, timeout: float) -> Response:
        _guard(req.full_url)
        if not req.has_header("User-agent"):  # urllib stores header names capitalize()d
            req.add_header("User-Agent", USER_AGENT)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                content = resp.read(self._max_bytes + 1)
                if len(content) > self._max_bytes:
                    raise ValueError("Response exceeds the size cap.")
                return Response(status_code=resp.status, headers=dict(resp.headers), content=content)
        except urllib.error.HTTPError as e:
            # A 4xx/5xx is a real response — hand it back so the caller can inspect the status.
            body = e.read(self._max_bytes) if hasattr(e, "read") else b""
            return Response(status_code=e.code, headers=dict(e.headers or {}), content=body)

    def get(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 15) -> Response:
        """A GET, retried once after a short pause when the network blips (a timeout, a dropped connection): GETs
        are safe to repeat, and an API that is slow for one request is usually fine the next second."""
        try:
            return self._send(urllib.request.Request(url, method="GET", headers=headers or {}), timeout)
        except Exception as e:
            if not is_transient_network_error(e):
                raise
            time.sleep(RETRY_PAUSE_SECONDS)
            return self._send(urllib.request.Request(url, method="GET", headers=headers or {}), timeout)

    def _with_body(self, method: str, url: str, json, data: bytes | None, headers: dict[str, str] | None, timeout: float) -> Response:
        hdrs = dict(headers or {})
        body = data
        if json is not None:
            import json as _json

            body = _json.dumps(json).encode()
            hdrs.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=body or b"", method=method, headers=hdrs)
        return self._send(req, timeout)

    def post(
        self,
        url: str,
        *,
        json=None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 15,
    ) -> Response:
        return self._with_body("POST", url, json, data, headers, timeout)

    def put(
        self,
        url: str,
        *,
        json=None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 15,
    ) -> Response:
        return self._with_body("PUT", url, json, data, headers, timeout)

    def patch(
        self,
        url: str,
        *,
        json=None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 15,
    ) -> Response:
        # Some APIs (Buttondown's webhooks) update only by PATCH; providers feature-detect it on ctx.http.
        return self._with_body("PATCH", url, json, data, headers, timeout)

    def delete(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 15) -> Response:
        req = urllib.request.Request(url, method="DELETE", headers=headers or {})
        return self._send(req, timeout)


def build_http() -> MarvinHttpHelper:
    """Factory for the per-call http helper handed to providers."""
    return MarvinHttpHelper()
