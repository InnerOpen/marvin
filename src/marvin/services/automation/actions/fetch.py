"""`fetch` step — read a web address, or check the links in a piece of text.

`url`: one GET (or HEAD) through core's guarded HTTP client (services/integrations/http_client.py: public hosts only,
re-checked on every redirect, a response-size cap). Output: `status`, `ok`, `content_type`, `title` (an HTML page's),
`text` (trimmed) and `json` (when the answer is JSON), plus `error` when there was no answer at all. `find` (a phrase or
a list) looks for words on the page, ignoring case: `found` lists the ones there ("sold out" on a shop page).

`links`: the http(s) links in a text (markdown, HTML or bare; relative ones resolved against `base`, default the
workspace's site URL), each checked (HEAD, then GET when a server refuses HEAD), a few at a time. Output: `checked`,
`broken` ([{url, status, error}]), `broken_count` and `text` (one line per broken link). Broken means no answer, 404,
410 or a 5xx — not 401/403/429, which say a server won't talk to a robot, not that the page is gone.

A missing page or a dead server never fails the step: it is the output, for a `when` to act on. A dry run doesn't
fetch (as a webhook step doesn't send).
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from ..matcher import interpolate
from .base import AutomationActionError, register_action

FETCH_TIMEOUT_SECONDS = 10
MAX_FETCH_BYTES = 2 * 1024 * 1024  # a page or an API answer, not a download
MAX_TEXT_CHARS = 20_000  # what a step's output keeps of a page (the run snapshot has a size cap)
MAX_LINKS = 50
LINK_WORKERS = 5
BROKEN_STATUSES = frozenset({404, 410})
HEAD_REFUSED = frozenset({403, 405, 501})  # servers that answer HEAD with these often serve GET fine
# A markdown/HTML link (absolute or site-relative), or a bare absolute one in prose.
_LINK = re.compile(r"""(?:\]\(|href=["']|src=["'])((?:https?://|/)[^\s"'<>()]+)|(?<![\w/])(https?://[^\s"'<>()\]]+)""", re.IGNORECASE)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@register_action("fetch")
def run_fetch_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    if bool(action.get("url")) == ("links" in action):
        raise AutomationActionError("a fetch step takes `url` (one address) or `links` (a text whose links to check)")
    if "links" in action:
        base = interpolate(action.get("base"), context) or (context.get("site") or {}).get("url")
        links = extract_links(str(interpolate(action.get("links"), context) or ""), base)
        if dry_run:
            return {"would_check": links, "checked": 0, "broken": [], "broken_count": 0, "text": ""}
        return check_links(links)
    method = str(action.get("method") or "GET").upper()
    if method not in ("GET", "HEAD"):
        raise AutomationActionError("a fetch step reads only: method is GET or HEAD")
    url = str(interpolate(action.get("url"), context) or "").strip()
    if not urlparse(url).scheme:
        raise AutomationActionError(f"not a web address: {url!r} (it needs http:// or https://)")
    if dry_run:
        return {"would_fetch": url, "method": method}
    out = fetch(url, method)
    if action.get("find"):
        phrases = interpolate(action["find"], context)
        page = str(out.get("text") or "").lower()
        out["found"] = [p for p in (phrases if isinstance(phrases, list) else [phrases]) if str(p).strip() and str(p).lower() in page]
    return out


def fetch(url: str, method: str = "GET") -> dict:
    """One request; never raises for what the far side does — no answer is `status: 0` with an `error`."""
    response, error = _request(url, method)
    if response is None:
        return {"url": url, "status": 0, "ok": False, "error": error}
    content_type = _header(response.headers, "content-type").split(";")[0].strip().lower()
    out = {"url": url, "status": response.status_code, "ok": 200 <= response.status_code < 400, "content_type": content_type}
    body = response.content.decode("utf-8", "replace") if method == "GET" else ""
    if "json" in content_type:
        try:
            out["json"] = json.loads(body) if len(body) <= MAX_TEXT_CHARS else None
        except ValueError:
            out["json"] = None
    if "html" in content_type and (title := _TITLE.search(body)):
        out["title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:300]
    if content_type.startswith("text/") or "json" in content_type or "xml" in content_type:
        out["text"] = body[:MAX_TEXT_CHARS] + ("…" if len(body) > MAX_TEXT_CHARS else "")
    return out


def extract_links(text: str, base: str | None = None) -> list[str]:
    """The distinct http(s) links in a text, in order of first appearance; relative ones only when there's a base."""
    seen: dict[str, None] = {}
    for linked, bare in _LINK.findall(text or ""):
        link = (linked or bare).rstrip(".,;:!?'\"")
        if link.startswith("/"):
            if link.startswith("//") or not base:
                continue
            link = urljoin(base.rstrip("/") + "/", link.lstrip("/"))
        seen.setdefault(link.split("#")[0] or link, None)
    return list(seen)[:MAX_LINKS]


def check_links(links: list[str]) -> dict:
    with ThreadPoolExecutor(max_workers=LINK_WORKERS) as pool:
        results = list(pool.map(_check, links))
    broken = [r for r in results if r is not None]
    lines = [f"- {b['url']} — {b['error'] or b['status']}" for b in broken]
    return {"checked": len(links), "broken": broken, "broken_count": len(broken), "text": "\n".join(lines)}


def _check(url: str) -> dict | None:
    """None when the link works (or can't be judged by a robot); else {url, status, error}."""
    response, error = _request(url, "HEAD")
    if response is not None and response.status_code in HEAD_REFUSED:
        response, error = _request(url, "GET")
    if response is None:
        return {"url": url, "status": 0, "error": error}
    status = response.status_code
    return {"url": url, "status": status, "error": None} if status in BROKEN_STATUSES or status >= 500 else None


def _request(url: str, method: str):
    """(response, None) or (None, why there was no answer)."""
    from marvin.services.integrations.http_client import MarvinHttpHelper, SsrfError

    http = MarvinHttpHelper(max_bytes=MAX_FETCH_BYTES)
    try:
        send = http.head if method == "HEAD" else http.get
        return send(url, timeout=FETCH_TIMEOUT_SECONDS), None
    except SsrfError as e:
        return None, f"refused: {e}"
    except ValueError as e:  # the size cap
        return None, str(e)
    except Exception as e:  # noqa: BLE001 — DNS, refused, timeout, TLS: the link is the problem, not the run
        reason = getattr(e, "reason", None) or e
        return None, f"no answer ({type(reason).__name__}: {str(reason)[:200]})"


def _header(headers: dict, name: str) -> str:
    return next((str(v) for k, v in (headers or {}).items() if k.lower() == name), "")
