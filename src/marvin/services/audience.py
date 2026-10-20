"""Audience › Submissions: the forms whose submissions go to the Audience, and the submissions themselves.

A form is a submittable entry type (``capabilities.submittable``). Its ``submission.destination`` says where what people send
goes: ``audience`` (the default) makes the type internal (services/entry_listing.py), so the entries stay out of All entries, the
status lists, counts, search and the AI index and are read here; ``entries`` keeps them as ordinary entries to review and publish.
Its ``submission.kind`` says what a submission is: ``message`` (someone writing to you, listed here) or ``signup`` (a newsletter
signup, Audience › Subscribers).

A submission is an entry of the form's type: ``inbox`` when clean, ``needs_review`` when the submission protection held it, and
``archived`` once handled. What the protection made of it (the reasons) and where it came from (IP, user agent, referrer) are on
the entry's ``metadata_json.submission`` (the public route records them; there is no separate record and no score). The page shows
three states: new (inbox), suspicious (needs review) and handled (any other status — archived, or whatever a workflow moved it to);
a trashed one is in the Trash.
"""

from __future__ import annotations

import ipaddress
from datetime import UTC, datetime

from sqlalchemy import func, or_

from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.services.entries.entry_service import TRASHED
from marvin.services.entry_listing import submission_destination, submission_kind

NEW_STATUSES = ("inbox", "needs_review")
"""The statuses that count as waiting."""
STATES = ("new", "suspicious", "handled")
SEARCH_SCAN_LIMIT = 5000
"""A text search reads at most this many of the newest submissions (the text is in JSON, searched after the fact)."""

SUBMISSIONS_PATH = "/workspace/audience/submissions"


def state_of(status: str) -> str:
    """The page's word for an entry status: inbox is new, needs_review is suspicious, anything else is handled."""
    return {"inbox": "new", "needs_review": "suspicious"}.get(status, "handled")


def forms(session, group_id, kind: str = "message") -> list[EntryTypes]:
    """The workspace's forms that send their submissions to the Audience, of one kind, in the entry types' order."""
    rows = session.query(EntryTypes).filter(EntryTypes.group_id == group_id).order_by(EntryTypes.sort_order, EntryTypes.name).all()
    return [t for t in rows if submission_destination(t) == "audience" and submission_kind(t) == kind]


def new_counts(session, group_id, type_ids: list) -> dict:
    """``{type id: submissions waiting}`` (inbox plus needs review) for the given forms."""
    if not type_ids:
        return {}
    rows = (
        session.query(Entries.entry_type_id, func.count(Entries.id))
        .filter(Entries.group_id == group_id, Entries.entry_type_id.in_(type_ids), Entries.status.in_(NEW_STATUSES))
        .group_by(Entries.entry_type_id)
        .all()
    )
    return {type_id: int(n) for type_id, n in rows}


def form_read(entry_type: EntryTypes, new: int = 0) -> dict:
    return {"slug": entry_type.slug, "name": entry_type.name, "icon": entry_type.icon, "new": new}


def summary(session, group_id) -> dict:
    """What the sidebar needs: each message form with its waiting count, and whether a signup form exists."""
    messages = forms(session, group_id, "message")
    counts = new_counts(session, group_id, [t.id for t in messages])
    reads = [form_read(t, counts.get(t.id, 0)) for t in messages]
    signups = forms(session, group_id, "signup")
    return {
        "submissions": {"show": bool(reads), "new": sum(f["new"] for f in reads), "forms": reads},
        "signups": {"show": bool(signups), "forms": [form_read(t) for t in signups]},
    }


def mask_ip(ip: str | None) -> str | None:
    """An IP with its host part hidden: 203.0.113.x for IPv4, the first three groups for IPv6. Anything unparseable is hidden whole."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip.strip())
    except ValueError:
        return "hidden"
    if address.version == 4:
        return ".".join(str(address).split(".")[:3] + ["x"])
    return ":".join(address.exploded.split(":")[:3]) + "::x"


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is None else parsed.astimezone(UTC).replace(tzinfo=None)
    return None


def _strings(value) -> list[str]:
    return [str(v) for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _blank(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def fields_of(entry_type: EntryTypes, data: dict) -> list[dict]:
    """The submitted values with the form's labels, in the schema's order, then any value the schema doesn't name. Blanks are left out."""
    schema = [f for f in ((entry_type.schema_json or {}).get("fields") or []) if isinstance(f, dict) and f.get("key")]
    out, seen = [], set()
    for f in schema:
        key = f["key"]
        seen.add(key)
        if not _blank(data.get(key)):
            out.append({"key": key, "label": f.get("label") or key, "type": f.get("type"), "value": data.get(key)})
    out.extend({"key": k, "label": k, "type": None, "value": v} for k, v in data.items() if k not in seen and not _blank(v))
    return out


def read(entry: Entries, entry_type: EntryTypes, *, full_ip: bool, new: int = 0) -> dict:
    """One submission as the API returns it."""
    meta = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    sub = meta.get("submission") if isinstance(meta.get("submission"), dict) else {}
    reasons = [*dict.fromkeys(_strings(sub.get("review_reasons")) + _strings(meta.get("review_reasons")))]
    ip = sub.get("ip_address") if isinstance(sub.get("ip_address"), str) else None
    return {
        "id": entry.id,
        "form": form_read(entry_type, new),
        "title": entry.title,
        "state": state_of(entry.status),
        "status": entry.status,
        "fields": fields_of(entry_type, entry.data_json if isinstance(entry.data_json, dict) else {}),
        "verdict": {"flagged": bool(reasons), "reasons": reasons},
        "source": {
            "ip": ip if full_ip else mask_ip(ip),
            "ip_masked": bool(ip) and not full_ip,
            "user_agent": sub.get("user_agent") if isinstance(sub.get("user_agent"), str) else None,
            "referrer": sub.get("referer") if isinstance(sub.get("referer"), str) else None,
            "received_at": _when(sub.get("received_at")),
            "last_received_at": _when(sub.get("last_received_at")),
            "count": int(sub.get("submission_count") or 1),
        },
        "created_at": entry.created_at,
        "path": f"/workspace/entries/{entry.id}",
    }


def _flat_text(entry: Entries) -> str:
    parts = [entry.title or ""]
    for value in (entry.data_json or {}).values():
        parts.append(" ".join(str(v) for v in value) if isinstance(value, list) else str(value))
    return " ".join(parts).lower()


def query(
    session,
    group_id,
    *,
    form: str | None = None,
    states: list[str] | None = None,
    text: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Entries, EntryTypes]], int]:
    """The message forms' submissions (newest first) with ``(entries, total)``: one form by slug, one or more states, a text found
    in the title or any value, a day range on when it arrived. Trashed ones are left out (the Trash lists them)."""
    messages = {t.id: t for t in forms(session, group_id, "message")}
    if form is not None:
        messages = {i: t for i, t in messages.items() if t.slug == form}
    if not messages:
        return [], 0
    q = session.query(Entries).filter(Entries.group_id == group_id, Entries.entry_type_id.in_(list(messages)), Entries.status != TRASHED)
    wanted = [s for s in (states or []) if s in STATES]
    if wanted and len(wanted) < len(STATES):
        clauses = []
        if "new" in wanted:
            clauses.append(Entries.status == "inbox")
        if "suspicious" in wanted:
            clauses.append(Entries.status == "needs_review")
        if "handled" in wanted:
            clauses.append(Entries.status.notin_(NEW_STATUSES))
        q = q.filter(or_(*clauses))
    if since is not None:
        q = q.filter(Entries.created_at >= since)
    if until is not None:
        q = q.filter(Entries.created_at <= until)
    q = q.order_by(Entries.created_at.desc(), Entries.id)
    needle = (text or "").strip().lower()
    if needle:
        found = [e for e in q.limit(SEARCH_SCAN_LIMIT) if needle in _flat_text(e)]
        return [(e, messages[e.entry_type_id]) for e in found[offset : offset + limit]], len(found)
    total = q.count()
    return [(e, messages[e.entry_type_id]) for e in q.offset(offset).limit(limit)], total


def get(session, group_id, entry_id) -> tuple[Entries, EntryTypes] | None:
    """A submission of one of the message forms (any status but trashed), or None."""
    entry = session.get(Entries, entry_id)
    if entry is None or entry.group_id != group_id or entry.status == TRASHED:
        return None
    entry_type = session.get(EntryTypes, entry.entry_type_id)
    if entry_type is None or submission_destination(entry_type) != "audience" or submission_kind(entry_type) != "message":
        return None
    return entry, entry_type
