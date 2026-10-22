"""The "Site links" setup check: is the workspace set up so an entry's ``url`` is a real link?

An entry's URL is the workspace's site address (Canonical URL) joined to its type's page URL pattern
(services/entry_urls.py). Either missing and ``entry.url`` is empty (or a bare path) — in a newsletter workflow, a dead
link nothing warned about. Two readers share the facts here:

- ``site_links_problems`` — the workspace-wide list (Settings › General, the ``check_site_links`` tool); no network.
- ``workflow_url_issues`` — the warning on a workflow that uses ``${entry.url}`` for entry types that can't give one.

``probe_site_links`` is the optional live half: one published entry per type, fetched with the guarded HTTP client.
It only runs when asked (a button), never on a page load.
"""

from __future__ import annotations

import json
import re
from typing import Any

from marvin.services.entry_urls import best_entry_url, site_base_url

# Where each problem is fixed, for a link next to it: the site address, or an entry type's editor.
SITE_ADDRESS_FIX = {"label": "Set the Canonical URL", "path": "/publishing/site#site-canonical-url"}
PROBE_TIMEOUT_SECONDS = 5
PROBE_MAX_BYTES = 2_000_000  # a page is read only to be counted as answered, so the cap is generous
_ENTRY_URL = re.compile(r"(?<![\w.])entry\.url\b")
_MENTION_LIMIT = 5


def publishable_types(session, group_id) -> list:
    """The workspace's entry types whose entries are shown on a site: not internal (``listed``), not unpublishable, not
    marked not routable. Built-in types shared by every workspace are left out: they can't hold a pattern (the copies a
    workspace starts with can), so there would be nothing here to fix."""
    from marvin.db.models.platform.entry_types import EntryTypes

    def shown(t) -> bool:
        caps = t.capabilities_json if isinstance(t.capabilities_json, dict) else {}
        return all(caps.get(key) is not False for key in ("listed", "publishable", "routable"))

    rows = session.query(EntryTypes).filter(EntryTypes.group_id == group_id).all()
    return sorted((t for t in rows if shown(t)), key=lambda t: (t.name or "").lower())


def _type_fix(t) -> dict:
    return {"label": f"Set a page URL pattern for {t.name}", "path": f"/workspace/entry-types/{t.id}"}


def site_links_problems(session, group_id) -> list[dict]:
    """What keeps entry links from working here, each ``{kind, message, fix: {label, path}, entryType?}``; empty when set up."""
    types = publishable_types(session, group_id)
    problems: list[dict] = []
    if not site_base_url(session, group_id):
        problems.append(
            {
                "kind": "no_site_address",
                "message": "No site address: entry links are bare paths until the workspace's Canonical URL is set.",
                "fix": SITE_ADDRESS_FIX,
            }
        )
    for t in types:
        if not t.page_url_pattern:
            problems.append(
                {
                    "kind": "no_page_pattern",
                    "entryType": t.slug,
                    "message": f"{t.name} has no page URL pattern, so its entries have no link.",
                    "fix": _type_fix(t),
                }
            )
    return problems


def _absolute(pattern: str) -> bool:
    return pattern.startswith(("http://", "https://"))


def _probe_candidates(session, group_id, types) -> list[tuple[Any, str]]:
    """(type, absolute URL of its newest published entry) for each type that has both a pattern and a published entry."""
    from marvin.db.models.platform.entries import Entries

    base = site_base_url(session, group_id)
    out = []
    for t in types:
        if not t.page_url_pattern:
            continue
        entry = (
            session.query(Entries)
            .filter(Entries.group_id == group_id, Entries.entry_type_id == t.id, Entries.status == "published")
            .order_by(Entries.published_at.desc())
            .first()
        )
        url = best_entry_url(entry, base, entry_type=t) if entry is not None else None
        if url and url.startswith(("http://", "https://")):  # a bare path can't be fetched: the missing address says so
            out.append((t, url))
    return out


def probe_site_links(session, group_id, http=None) -> list[dict]:
    """Fetch one published entry's link per type; a problem for each that doesn't answer 200. ``http`` is the guarded
    client (``MarvinHttpHelper``); a fake stands in for it in tests. Slow and networked: run it on request only."""
    from marvin.services.integrations.http_client import MarvinHttpHelper, SsrfError

    client = http or MarvinHttpHelper(max_bytes=PROBE_MAX_BYTES)
    problems: list[dict] = []
    for t, url in _probe_candidates(session, group_id, publishable_types(session, group_id)):
        reason = None
        try:
            status = client.get(url, timeout=PROBE_TIMEOUT_SECONDS).status_code
            if status != 200:
                reason = f"answered {status}"
        except SsrfError:
            reason = "is not a public address"
        except ValueError:  # over the size cap: it answered with a page, which is all this checks
            pass
        except Exception as e:  # noqa: BLE001 — DNS, refused, timeout, TLS: the link is the problem, not the check
            reason = f"did not answer ({type(getattr(e, 'reason', None) or e).__name__})"
        if reason:
            problems.append(
                {
                    "kind": "probe_failed",
                    "entryType": t.slug,
                    "url": url,
                    "message": f"{t.name}: {url} {reason}. Check the page URL pattern against the site's routes.",
                    "fix": _type_fix(t),
                }
            )
    return problems


# ── The workflow warning ─────────────────────────────────────────────────────
def uses_entry_url(definition: dict | None) -> bool:
    """Whether a step or condition reads ``entry.url`` (``${entry.url}`` in any step field, or a condition's field)."""
    definition = definition or {}
    parts = [definition.get(key) for key in ("actions", "on_failure", "conditions")]
    return bool(_ENTRY_URL.search(json.dumps(parts, default=str)))


def _named_type_slugs(definition: dict) -> set[str]:
    """The entry types a workflow is pinned to: a top-level condition ``entry.entry_type`` eq/in some plain slugs, and the
    target's ``query.entry_type``. Templated values say nothing. Empty: not pinned, any type may arrive."""
    named: set[str] = set()

    def take(value) -> None:
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, str) and v.strip() and "${" not in v:
                named.add(v.strip())

    for cond in definition.get("conditions") or []:
        if isinstance(cond, dict) and cond.get("field") == "entry.entry_type" and cond.get("op", "eq") in ("eq", "in"):
            take(cond.get("value"))
    target = definition.get("target")
    if isinstance(target, dict) and target.get("entity", "entry") == "entry" and isinstance(target.get("query"), dict):
        take(target["query"].get("entry_type"))
    return named


def _names(types: list) -> str:
    names = [t.name for t in types[:_MENTION_LIMIT]]
    if len(types) > _MENTION_LIMIT:
        names.append(f"{len(types) - _MENTION_LIMIT} more")
    return ", ".join(names)


def workflow_url_issues(session, group_id, definition: dict | None) -> list[dict]:
    """Warnings for a workflow that uses ``${entry.url}`` where it can't be a full link: the entry types it acts on (see
    ``_named_type_slugs``; all publishable ones when it isn't pinned) lack a page URL pattern, or the workspace has no site
    address to join the pattern to. Advisory — the workflow saves."""
    definition = definition or {}
    if not uses_entry_url(definition):
        return []
    types = publishable_types(session, group_id)
    named = _named_type_slugs(definition)
    if named:
        types = [t for t in types if t.slug in named]
    some = "" if named else " for some entries"
    where = "Site links, in Settings › General"
    issues = []
    missing = [t for t in types if not t.page_url_pattern]
    if missing:
        verb = "has" if len(missing) == 1 else "have"
        issues.append(f"`${{entry.url}}` will be empty{some}: {_names(missing)} {verb} no page URL pattern ({where}).")
    elif any(not _absolute(t.page_url_pattern) for t in types) and not site_base_url(session, group_id):
        issues.append(f"`${{entry.url}}` will be a bare path, not a link{some}: the workspace has no site address ({where}).")
    return [{"level": "warning", "message": m, "where": "action"} for m in issues]
