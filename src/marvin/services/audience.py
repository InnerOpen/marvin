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

Audience › Subscribers reads the forms whose ``submission.kind`` is ``signup`` (whatever their destination). A signup is an entry
whose status mirrors the mailing list (the Buttondown plugin's loop): ``inbox`` is pending (asked to join, not confirmed yet),
``published`` confirmed, ``archived`` unsubscribed and ``needs_review`` a problem (the list refused it, or the spam protection held
it), with the review reason. Subscribing and unsubscribing stay the mailing-list integration's (its workflows and webhook); this
only reads the entries and moves one to the Trash.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, or_

from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.event_log import EventLogModel
from marvin.services.entries.entry_service import TRASHED
from marvin.services.entry_listing import submission_destination, submission_kind
from marvin.services.entry_privacy import mask_ip

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
    """What the sidebar needs: each message form with its waiting count, and the signup forms with the subscribers' counts."""
    messages = forms(session, group_id, "message")
    counts = new_counts(session, group_id, [t.id for t in messages])
    reads = [form_read(t, counts.get(t.id, 0)) for t in messages]
    return {"submissions": {"show": bool(reads), "new": sum(f["new"] for f in reads), "forms": reads}, "signups": signups_summary(session, group_id)}


# ── Subscribers ───────────────────────────────────────────────────────────────────────────────────────────────────

SUBSCRIBER_STATUSES = ("pending", "confirmed", "unsubscribed", "problem")
SIGNUP_STATUS = {"inbox": "pending", "published": "confirmed", "archived": "unsubscribed", "needs_review": "problem"}
"""A signup entry's status as the mailing list's word. Any other status (a draft, approved…) is not confirmed yet: pending."""


def subscriber_status(entry_status: str) -> str:
    return SIGNUP_STATUS.get(entry_status, "pending")


def signup_forms(session, group_id) -> list[EntryTypes]:
    """The workspace's signup forms (``submission.kind: signup``), in the entry types' order. Whatever their destination."""
    rows = session.query(EntryTypes).filter(EntryTypes.group_id == group_id).order_by(EntryTypes.sort_order, EntryTypes.name).all()
    return [t for t in rows if submission_kind(t) == "signup"]


def subscriber_counts(session, group_id, type_ids: list) -> tuple[dict, dict]:
    """``({status: n}, {type id: pending + problems})`` over the signup forms; the Trash is not counted."""
    totals = dict.fromkeys(SUBSCRIBER_STATUSES, 0)
    waiting: dict = {}
    if not type_ids:
        return totals, waiting
    rows = (
        session.query(Entries.entry_type_id, Entries.status, func.count(Entries.id))
        .filter(Entries.group_id == group_id, Entries.entry_type_id.in_(type_ids), Entries.status != TRASHED)
        .group_by(Entries.entry_type_id, Entries.status)
        .all()
    )
    for type_id, entry_status, n in rows:
        state = subscriber_status(entry_status)
        totals[state] += int(n)
        if state in ("pending", "problem"):
            waiting[type_id] = waiting.get(type_id, 0) + int(n)
    return totals, waiting


def _names_type(node, slugs: set) -> bool:
    """Whether a workflow definition names one of these entry types: a condition ``entry.entry_type`` equal to it (or in a list of
    them), or an entry step's ``entity_query.entry_type``."""
    if isinstance(node, dict):
        if node.get("field") == "entry.entry_type" and node.get("op") in ("eq", "in"):
            value = node.get("value")
            if value in slugs or (isinstance(value, list) and slugs.intersection(v for v in value if isinstance(v, str))):
                return True
        query = node.get("entity_query")
        if isinstance(query, dict) and query.get("entry_type") in slugs:
            return True
        return any(_names_type(v, slugs) for v in node.values())
    if isinstance(node, list):
        return any(_names_type(v, slugs) for v in node)
    return False


def signup_integrations(session, group_id, slugs: set) -> list[dict]:
    """The enabled integrations that act on these signup forms, ``[{slug, name, provider}]``: those with a workflow they installed
    that names the form (``entry.entry_type`` in a condition, or an entry step's query), and those whose provider declares a
    blueprint with an entry-type parameter whose default is the form (Buttondown's ``signup_type``). Nothing is guessed by name."""
    if not slugs:
        return []
    from marvin.services.blueprints.catalog import list_blueprints

    found: dict = {}
    integrations = {
        i.id: i for i in session.query(IntegrationModel).filter(IntegrationModel.group_id == group_id, IntegrationModel.enabled.is_(True))
    }
    workflows = (
        session.query(WorkspaceAutomationModel)
        .filter(WorkspaceAutomationModel.group_id == group_id, WorkspaceAutomationModel.source_integration_id.isnot(None))
        .all()
    )
    for workflow in workflows:
        integration = integrations.get(workflow.source_integration_id)
        if integration is not None and _names_type(workflow.definition, slugs):
            found[integration.id] = integration
    for integration in integrations.values():
        if integration.id in found:
            continue
        for blueprint in list_blueprints(source=integration.provider):
            if any(p.kind == "entry_type" and p.default in slugs for p in blueprint.parameters):
                found[integration.id] = integration
                break
    return [{"slug": i.slug, "name": i.name, "provider": i.provider} for i in sorted(found.values(), key=lambda i: (i.name, i.slug))]


def signups_summary(session, group_id, *, with_integrations: bool = False) -> dict:
    """The sidebar's and Subscribers page's view of the signup forms: a count per status, what is waiting (pending plus problems),
    and, when asked (the page, not every sidebar render), the integrations that act on them. ``show`` is false until a form has
    ``submission.kind: signup``."""
    signups = signup_forms(session, group_id)
    totals, waiting = subscriber_counts(session, group_id, [t.id for t in signups])
    return {
        "show": bool(signups),
        "forms": [form_read(t, waiting.get(t.id, 0)) for t in signups],
        **totals,
        "waiting": totals["pending"] + totals["problem"],
        "integrations": signup_integrations(session, group_id, {t.slug for t in signups}) if with_integrations else [],
    }


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


def _source(sub: dict, full_ip: bool) -> dict:
    """Where a submission came from, from the entry's ``metadata.submission``: the IP whole for ADMIN and above, masked below."""
    ip = sub.get("ip_address") if isinstance(sub.get("ip_address"), str) else None
    return {
        "ip": ip if full_ip else mask_ip(ip),
        "ip_masked": bool(ip) and not full_ip,
        "user_agent": sub.get("user_agent") if isinstance(sub.get("user_agent"), str) else None,
        "referrer": sub.get("referer") if isinstance(sub.get("referer"), str) else None,
        "received_at": _when(sub.get("received_at")),
        "last_received_at": _when(sub.get("last_received_at")),
        "count": int(sub.get("submission_count") or 1),
    }


def read(entry: Entries, entry_type: EntryTypes, *, full_ip: bool, new: int = 0) -> dict:
    """One submission as the API returns it."""
    meta = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    sub = meta.get("submission") if isinstance(meta.get("submission"), dict) else {}
    reasons = [*dict.fromkeys(_strings(sub.get("review_reasons")) + _strings(meta.get("review_reasons")))]
    return {
        "id": entry.id,
        "form": form_read(entry_type, new),
        "title": entry.title,
        "state": state_of(entry.status),
        "status": entry.status,
        "fields": fields_of(entry_type, entry.data_json if isinstance(entry.data_json, dict) else {}),
        "verdict": {"flagged": bool(reasons), "reasons": reasons},
        "source": _source(sub, full_ip),
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


# ── Subscribers: a reader's row, the list and one reader ──────────────────────────────────────────────────────────────

_NAME_KEY = re.compile(r"^(full[_ -]?name|your[_ -]?name|name|first[_ -]?name|contact[_ -]?name)$", re.I)
_EMAIL_KEY = re.compile(r"e-?mail", re.I)


def identity(entry_type: EntryTypes, entry: Entries) -> tuple[str | None, str | None]:
    """``(email, name)`` of a signup: the first email-like field with a value (a field of type ``email``, or one whose key says so),
    and the first name-like one (``name``, ``full_name``, ``first_name``…). Either may be None: a signup form needs neither."""
    email = name = None
    for f in fields_of(entry_type, entry.data_json if isinstance(entry.data_json, dict) else {}):
        value = f["value"]
        text = " ".join(str(v) for v in value) if isinstance(value, list) else str(value).strip()
        if not text:
            continue
        if email is None and (f.get("type") == "email" or _EMAIL_KEY.search(f["key"])):
            email = text
        elif name is None and (_NAME_KEY.match(f["key"]) or _NAME_KEY.match(f.get("label") or "")):
            name = text
    return email, name


def _review_reasons(entry: Entries) -> list[str]:
    meta = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    sub = meta.get("submission") if isinstance(meta.get("submission"), dict) else {}
    return [*dict.fromkeys(_strings(sub.get("review_reasons")) + _strings(meta.get("review_reasons")))]


def subscriber_row(entry: Entries, entry_type: EntryTypes, new: int = 0) -> dict:
    """One subscriber as the list returns it: who, when, where it stands, and why when it is a problem (the latest reason)."""
    email, name = identity(entry_type, entry)
    state = subscriber_status(entry.status)
    reasons = _review_reasons(entry) if state == "problem" else []
    return {
        "id": entry.id,
        "form": form_read(entry_type, new),
        "email": email,
        "name": name,
        "title": entry.title,
        "status": state,
        "entry_status": entry.status,
        "review_reasons": reasons,
        "reason": reasons[-1] if reasons else None,
        "signed_up_at": entry.created_at,
        "path": f"/workspace/entries/{entry.id}",
    }


def _status_clause(wanted: list[str]):
    """A SQL condition on the entry status for one or more subscriber statuses (pending is everything not settled)."""
    clauses = []
    if "pending" in wanted:
        clauses.append(Entries.status.notin_(["published", "archived", "needs_review", TRASHED]))
    if "confirmed" in wanted:
        clauses.append(Entries.status == "published")
    if "unsubscribed" in wanted:
        clauses.append(Entries.status == "archived")
    if "problem" in wanted:
        clauses.append(Entries.status == "needs_review")
    return or_(*clauses)


def query_subscribers(
    session,
    group_id,
    *,
    form: str | None = None,
    statuses: list[str] | None = None,
    text: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Entries, EntryTypes]], int]:
    """The signup forms' entries, newest first, with ``(rows, total)``: one form by slug, one or more statuses, a text found in the
    email, name or title, a day range on when it arrived. The Trash is left out."""
    types = {t.id: t for t in signup_forms(session, group_id)}
    if form is not None:
        types = {i: t for i, t in types.items() if t.slug == form}
    if not types:
        return [], 0
    q = session.query(Entries).filter(Entries.group_id == group_id, Entries.entry_type_id.in_(list(types)), Entries.status != TRASHED)
    wanted = [s for s in (statuses or []) if s in SUBSCRIBER_STATUSES]
    if wanted and len(wanted) < len(SUBSCRIBER_STATUSES):
        q = q.filter(_status_clause(wanted))
    if since is not None:
        q = q.filter(Entries.created_at >= since)
    if until is not None:
        q = q.filter(Entries.created_at <= until)
    q = q.order_by(Entries.created_at.desc(), Entries.id)
    needle = (text or "").strip().lower()
    if needle:
        found = []
        for e in q.limit(SEARCH_SCAN_LIMIT):
            email, name = identity(types[e.entry_type_id], e)
            if needle in " ".join(filter(None, [email, name, e.title])).lower():
                found.append(e)
        return [(e, types[e.entry_type_id]) for e in found[offset : offset + limit]], len(found)
    total = q.count()
    return [(e, types[e.entry_type_id]) for e in q.offset(offset).limit(limit)], total


def get_subscriber(session, group_id, entry_id) -> tuple[Entries, EntryTypes] | None:
    """A signup entry of one of the signup forms (any status but trashed), or None."""
    entry = session.get(Entries, entry_id)
    if entry is None or entry.group_id != group_id or entry.status == TRASHED:
        return None
    entry_type = session.get(EntryTypes, entry.entry_type_id)
    if entry_type is None or submission_kind(entry_type) != "signup":
        return None
    return entry, entry_type


HISTORY_LABEL = {
    "entry_created": "Signed up",
    "entry_published": "Confirmed",
    "entry_unpublished": "No longer confirmed",
    "entry_archived": "Unsubscribed",
    "entry_restored": "Reopened",
}
HISTORY_AFTER = {"inbox": "Back to pending", "needs_review": "Needs a look"}
HISTORY_LIMIT = 12


def history(session, group_id, entry_id) -> list[dict]:
    """The signup's status changes, newest first, from the event log: ``[{label, at}]`` (signed up, confirmed, unsubscribed, reopened,
    back to pending, needs a look). Whatever the log holds; an entry whose events were pruned has a shorter story."""
    rows = (
        session.query(EventLogModel)
        .filter(
            EventLogModel.workspace_id == group_id,
            EventLogModel.entity_id == entry_id,
            EventLogModel.event_type.in_([*HISTORY_LABEL, "entry_updated"]),
        )
        .order_by(EventLogModel.occurred_at.desc())
        .limit(HISTORY_LIMIT * 4)
        .all()
    )
    out = []
    for row in rows:
        label = HISTORY_LABEL.get(row.event_type)
        if label is None:  # an update: only a status change says anything
            data = row.event_data if isinstance(row.event_data, dict) else {}
            doc = data.get("documentData") or data.get("document_data") or {}
            after = doc.get("after") if isinstance(doc, dict) else None
            label = HISTORY_AFTER.get(after.get("status")) if isinstance(after, dict) else None
        if label:
            out.append({"label": label, "at": row.occurred_at})
        if len(out) >= HISTORY_LIMIT:
            break
    return out


def subscriber_detail(session, entry: Entries, entry_type: EntryTypes, *, full_ip: bool) -> dict:
    """One subscriber in full: the row, every submitted field, where the signup came from (the IP masked below ADMIN) and its history."""
    meta = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    sub = meta.get("submission") if isinstance(meta.get("submission"), dict) else {}
    return {
        **subscriber_row(entry, entry_type),
        "fields": fields_of(entry_type, entry.data_json if isinstance(entry.data_json, dict) else {}),
        "source": _source(sub, full_ip),
        "history": history(session, entry.group_id, entry.id),
    }
