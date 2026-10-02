"""Core implementation of the SDK's HttpHelper — the safe HTTP client handed to providers.

Enforces timeouts, a response-size cap (INTEGRATION_HTTP_MAX_BYTES), and an SSRF guard (refuses to call private/loopback/
link-local/reserved hosts, and re-checks on redirect). Providers get safe outbound HTTP for free.
"""

import ipaddress
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

from marvin_integration_sdk.http import Response

from marvin.core.config import get_app_settings

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
        req = urllib.request.Request(url, method="GET", headers=headers or {})
        return self._send(req, timeout)

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

    def delete(self, url: str, *, headers: dict[str, str] | None = None, timeout: float = 15) -> Response:
        req = urllib.request.Request(url, method="DELETE", headers=headers or {})
        return self._send(req, timeout)


def build_http() -> MarvinHttpHelper:
    """Factory for the per-call http helper handed to providers."""
    return MarvinHttpHelper()
