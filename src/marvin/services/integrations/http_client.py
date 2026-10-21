"""Core implementation of the SDK's HttpHelper — the safe HTTP client handed to providers.

Also core's own guarded client for outbound fetches that aren't integrations (media-embed oEmbed
lookups), so it must import without the optional ``marvin_integration_sdk``.

Enforces timeouts, a response-size cap (INTEGRATION_HTTP_MAX_BYTES), and an SSRF guard: every connection — the first and
each redirect's — resolves its host once, refuses it unless every address is public (not private, loopback, link-local,
reserved…), and connects to exactly the address it checked. Checking one lookup and connecting by a second would let a
hostile DNS server answer "public" then "127.0.0.1" (DNS rebinding). TLS still verifies the host's own name. The client
uses no proxy: the guard must see the real host. Providers get safe outbound HTTP for free.
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


def _is_public_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])  # an IPv6 scope (fe80::1%eth0) isn't part of the address
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _host_is_public(host: str) -> bool:
    """True only if every address the host resolves to is a global/public IP (a check before a request made elsewhere,
    e.g. web push; requests through this client are pinned by ``_public_address`` instead)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return all(_is_public_ip(info[4][0]) for info in infos)


def _public_address(host: str, port: int) -> str:
    """The one address to connect to: ``host`` resolved once, refused unless every address it has is public."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)  # gaierror → urllib's URLError, as before
    addresses = [info[4][0] for info in infos]
    if not addresses or not all(_is_public_ip(a) for a in addresses):
        raise SsrfError(f"Refusing to call non-public host {host!r}.")
    return addresses[0]


def _pinned_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **kwargs):
    """http.client's socket factory, pinned: connect to the address that was checked, not to a fresh lookup."""
    host, port = address
    return socket.create_connection((_public_address(host, port), port), timeout, source_address, **kwargs)


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _pinned_connection


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """The socket is pinned; TLS still wraps it with server_hostname = the host's name, so its certificate is checked."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _pinned_connection


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req, context=self._context)


def _guard(url: str, allowed_hosts: frozenset[str] | None = None) -> None:
    """The URL's shape: http(s) with a host (and, for a client built with ``allowed_hosts``, one of those hosts). Whether the
    host is public is checked as it connects (``_public_address``)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfError(f"Only http(s) URLs are allowed (got {parsed.scheme!r}).")
    if not parsed.hostname:
        raise SsrfError("URL has no host.")
    if allowed_hosts is not None and parsed.hostname.lower() not in allowed_hosts:
        raise SsrfError(f"Refusing to call {parsed.hostname!r}: only {', '.join(sorted(allowed_hosts))} are allowed here.")


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect must stay http(s) (and inside ``allowed_hosts`` when the client has them); its host is checked when it
    connects, like the first one."""

    def __init__(self, allowed_hosts: frozenset[str] | None = None):
        self._allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _guard(newurl, self._allowed_hosts)
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

    def __init__(self, max_bytes: int | None = None, allowed_hosts: frozenset[str] | set[str] | None = None) -> None:
        """``allowed_hosts`` narrows the client to those host names, for the first request and every redirect (a fetch from
        one named service, such as the GitHub import)."""
        self._allowed_hosts = frozenset(h.lower() for h in allowed_hosts) if allowed_hosts is not None else None
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _GuardedRedirectHandler(self._allowed_hosts), _PinnedHTTPHandler(), _PinnedHTTPSHandler()
        )
        self._max_bytes = get_app_settings().INTEGRATION_HTTP_MAX_BYTES if max_bytes is None else max_bytes

    def _send(self, req: urllib.request.Request, timeout: float) -> Response:
        _guard(req.full_url, self._allowed_hosts)
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

    def head(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 15) -> Response:
        """Status and headers only — a workflow's link check (services/automation/actions/fetch.py)."""
        return self._send(urllib.request.Request(url, method="HEAD", headers=headers or {}), timeout)

    def delete(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 15) -> Response:
        req = urllib.request.Request(url, method="DELETE", headers=headers or {})
        return self._send(req, timeout)

    def request(self, method: str, url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: float = 15) -> Response:
        """Any method with a ready body — a workflow's request step (services/automation/actions/request.py), which does
        its own retrying. A GET or HEAD sends no body."""
        method = method.upper()
        body = None if method in ("GET", "HEAD") else (data or b"")
        return self._send(urllib.request.Request(url, data=body, method=method, headers=headers or {}), timeout)


def build_http() -> MarvinHttpHelper:
    """Factory for the per-call http helper handed to providers."""
    return MarvinHttpHelper()
