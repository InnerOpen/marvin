"""`request` step — call a web API: any method, headers, query, a body, and the answer for later steps.

`url` and `method` (GET, POST, PUT, PATCH, DELETE or HEAD; default GET), `query` (added to the address, URL-encoded),
`headers` (a `{{SLUG}}` in a value resolves to the workspace's secret or variable, as a webhook's headers do) and `body`:
sent as JSON by default, as a form with `body_type: form`, or as it is with `body_type: text`. `secret_ref` sends
`Authorization: <auth_scheme> <secret>` (Bearer by default; `Basic` base64-encodes a "user:password" secret).

It goes through core's guarded HTTP client (services/integrations/http_client.py): public hosts only, every redirect
re-checked, a response-size cap. `retries` (0–3) repeats a call that met a network blip, a 429 or a 5xx, after a growing
pause. A non-2xx answer fails the step with what the server said, unless `fail_on_error: false`: then it is output, for
a `when` to act on. `idempotency_key` makes the call once within its window, as on a webhook step.

Output: `status`, `ok`, `content_type`, `headers` (names lower-cased), `json` (when the answer is JSON), `text` (trimmed)
and `url`. A dry run shows the request, credentials masked, and sends nothing.

It sends workspace data to an outside address, so it needs the role a webhook step needs (an admin's).
"""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import urlencode, urlparse, urlsplit, urlunsplit

from ..matcher import interpolate
from .base import AutomationActionError, register_action
from .webhook import DEFAULT_AUTH_SCHEME, _preview_headers, _secret_slug

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")
BODY_TYPES = ("json", "form", "text")
DEFAULT_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # an API's answer, not a download
MAX_TEXT_CHARS = 20_000  # what the step's output keeps (the run snapshot has a size cap)
MAX_HEADERS = 50
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRY_BASE_SECONDS = 1.0  # 1s, 2s, 4s


@register_action("request")
def run_request(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from .. import idempotency
    from ..authz import ROLE_OWNER, WEBHOOK_MIN_ROLE, require_role

    require_role(ROLE_OWNER if authorizer_role is None else authorizer_role, WEBHOOK_MIN_ROLE, "request step")

    method = str(action.get("method") or "GET").upper()
    if method not in METHODS:
        raise AutomationActionError(f"a request step's method is one of {', '.join(METHODS)}, not {method}")
    url = _with_query(str(interpolate(action.get("url"), context) or "").strip(), interpolate(action.get("query"), context))
    if urlparse(url).scheme not in ("http", "https"):
        raise AutomationActionError(f"not a web address: {url!r} (it needs http:// or https://)")

    configured = {str(k): "" if v is None else str(v) for k, v in (interpolate(action.get("headers") or {}, context) or {}).items()}
    body_type = str(action.get("body_type") or "json")
    if body_type not in BODY_TYPES:
        raise AutomationActionError(f"body_type is one of {', '.join(BODY_TYPES)}, not {body_type}")
    body = interpolate(action.get("body"), context) if "body" in action else None
    data, content_type = _encode_body(body, body_type) if method not in ("GET", "HEAD") else (None, None)

    gate = idempotency.open_gate(session, group_id, action, context, destination=f"request:{method} {_origin(url)}", dry_run=dry_run)
    if gate is not None and gate.duplicate and not dry_run:
        return gate.skipped()
    if dry_run:
        preview = {
            "dry_run": True,
            "kind": "request",
            "method": method,
            "url": url,
            "headers": _preview_headers(
                {**({"Content-Type": content_type} if content_type else {}), **configured}, action.get("secret_ref"), action.get("auth_scheme")
            ),
            "body": body if method not in ("GET", "HEAD") else None,
        }
        if gate is None:
            return preview
        return gate.skipped(preview) if gate.duplicate else {**preview, **gate.preview()}

    from marvin.services.secrets.resolver import resolve_dict

    headers = {**({"Content-Type": content_type} if content_type else {}), **resolve_dict(configured, group_id)}
    headers.update(_auth_header(action.get("secret_ref"), group_id, action.get("auth_scheme")))
    try:
        out = _call(method, url, data, headers, action)
    except BaseException:
        if gate is not None:
            gate.release()  # a call that failed is made again by the retry, not skipped as a duplicate
        raise
    if gate is not None:
        gate.complete(out)
    return out


def _with_query(url: str, query) -> str:
    if not isinstance(query, dict) or not query:
        return url
    pairs = [(str(k), "" if v is None else (json.dumps(v) if isinstance(v, dict | list) else str(v))) for k, v in query.items()]
    parts = urlsplit(url)
    joined = "&".join(p for p in (parts.query, urlencode(pairs)) if p)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, joined, parts.fragment))


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def _encode_body(body, body_type: str) -> tuple[bytes | None, str | None]:
    if body is None:
        return None, None
    if body_type == "form":
        if not isinstance(body, dict):
            raise AutomationActionError("a form body is an object of field → value")
        return urlencode({str(k): "" if v is None else str(v) for k, v in body.items()}).encode(), "application/x-www-form-urlencoded"
    if body_type == "text":
        return ("" if body is None else str(body)).encode(), "text/plain; charset=utf-8"
    return json.dumps(body, default=str).encode(), "application/json"


def _auth_header(secret_ref, group_id, scheme) -> dict:
    ref = _secret_slug(secret_ref)
    if not ref:
        return {}
    from marvin.services.secrets.resolver import resolve_secret

    token = resolve_secret(ref, group_id)
    if not token:
        raise AutomationActionError(f"secret {ref} has no value in this workspace")
    scheme = (scheme or DEFAULT_AUTH_SCHEME).strip()
    if scheme.lower() == "basic" and ":" in token:  # "user:password" → the encoded form Basic auth expects
        token = base64.b64encode(token.encode()).decode()
    return {"Authorization": f"{scheme} {token}"}


def _call(method: str, url: str, data, headers: dict, action: dict) -> dict:
    from marvin.services.integrations.http_client import MarvinHttpHelper, SsrfError, is_transient_network_error

    retries = max(0, min(int(action.get("retries") or 0), 3))
    timeout = max(1, min(int(action.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS), 60))
    http = MarvinHttpHelper(max_bytes=MAX_RESPONSE_BYTES)
    attempt = 0
    while True:
        try:
            response = http.request(method, url, data=data, headers=headers, timeout=timeout)
        except SsrfError as e:
            raise AutomationActionError(f"request refused: {e}") from e
        except ValueError as e:  # the size cap
            raise AutomationActionError(f"request {method} {url}: {e}") from e
        except Exception as e:  # noqa: BLE001 — DNS, refused, timeout, TLS
            if attempt < retries and is_transient_network_error(e):
                attempt += 1
                time.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
                continue
            reason = getattr(e, "reason", None) or e
            raise AutomationActionError(f"request {method} {url} got no answer ({type(reason).__name__}: {str(reason)[:200]})") from e
        if response.status_code in RETRY_STATUSES and attempt < retries:
            attempt += 1
            time.sleep(RETRY_BASE_SECONDS * 2 ** (attempt - 1))
            continue
        break
    out = _output(url, method, response)
    if not out["ok"] and action.get("fail_on_error", True) is not False:
        raise AutomationActionError(f"request {method} {url} -> {out['status']}: {str(out.get('text') or '')[:500]}")
    return out


def _output(url: str, method: str, response) -> dict:
    headers = {str(k).lower(): str(v)[:500] for k, v in list((response.headers or {}).items())[:MAX_HEADERS]}
    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    out = {"url": url, "status": response.status_code, "ok": 200 <= response.status_code < 300, "content_type": content_type, "headers": headers}
    if method == "HEAD":
        return out
    text = (response.content or b"").decode("utf-8", "replace")
    if "json" in content_type:
        try:
            out["json"] = json.loads(text) if text.strip() else None
        except ValueError:
            out["json"] = None
    out["text"] = text[:MAX_TEXT_CHARS] + ("…" if len(text) > MAX_TEXT_CHARS else "")
    return out
