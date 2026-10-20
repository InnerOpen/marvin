"""Automation results: what happened to the work Marvin handed to another system (Settings › Automation › Results).

An integration action that hands work off declares it (``marvin_integration_sdk.HandsOff``) and the engine keeps one
``automation_results`` row per hand-off (db/models/groups/automation_results.py):

* ``track`` — called by the integration step after the provider call. A call that succeeded writes the row **in flight**; one that
  failed writes it **failed** with the provider's (already redacted) message. A retry of the same hand-off (the error policy's, or a
  person's Retry) reuses the failed row and counts up ``attempt`` instead of starting another. Recording never breaks the step: it
  runs in a savepoint and a fault is logged.
* ``settle`` — what the ``automation_result`` step calls when the other side reports back: the row with that ``remote_id`` (on that
  connection, when named), else the newest in-flight row for that entry and connection. A report that matches nothing is kept as a
  fresh row rather than dropped. A status the provider doesn't know leaves the row in flight with the word in its message.
* **No reply** — a row still in flight 24 hours after it was sent. Computed from ``sent_at`` (``is_no_reply``), never a status, so a
  late reply settles it as usual. There is no automatic failure.
* ``prune`` — the daily system task: settled and dismissed rows go after 30 days, in flight and undismissed failures after 180.
* ``retry`` — re-runs the hand-off step of the Marvin workflow that sent a failed row, for that entry (see ``retry``).

The words are Marvin's: in_flight | succeeded | failed. The provider maps its own (``IntegrationProvider.result_status``).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy import func

from marvin.core.root_logger import get_logger
from marvin.db.models.groups.automation_results import AutomationResultModel as Result
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.platform.entries import Entries

logger = get_logger(__name__)

IN_FLIGHT, SUCCEEDED, FAILED = "in_flight", "succeeded", "failed"
STATUSES = (IN_FLIGHT, SUCCEEDED, FAILED)
FILTERS = ("in_flight", "no_reply", "failed", "succeeded")
"""What the Results page filters on: the three statuses and No reply (in flight past ``NO_REPLY_AFTER``)."""
NO_REPLY_AFTER = timedelta(hours=24)
RETENTION_DAYS = 30
"""How long a settled (or dismissed) result is kept, from when it finished."""
UNHANDLED_RETENTION_DAYS = 180
"""How long one still asking for attention (in flight, or failed and not dismissed) is kept, from when it was sent."""
MESSAGE_MAX = 2000
FIELD_MAX = 2000
SEARCH_SCAN_LIMIT = 5000
"""A text search reads at most this many of the newest results."""

RESULTS_PATH = "/automation/results"


class ResultError(ValueError):
    """What a person asked for can't be done to this result (a 409 for the API): the message says why."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _text(value, limit: int = FIELD_MAX) -> str | None:
    return None if value in (None, "") else str(value).strip()[:limit] or None


def _link(value) -> str | None:
    """A run's URL, kept only when it is a web address (the page renders it as a link)."""
    text = _text(value)
    return text if text and re.match(r"https?://", text, re.IGNORECASE) else None


def _uuid(value):
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def is_no_reply(row: Result, now: datetime | None = None) -> bool:
    """In flight, and sent more than ``NO_REPLY_AFTER`` ago."""
    return row.status == IN_FLIGHT and _aware(row.sent_at) < (now or _now()) - NO_REPLY_AFTER


def needs_attention(row: Result, now: datetime | None = None) -> bool:
    """What the dashboard counts: a failure nobody has dismissed, or a hand-off nobody has heard back about."""
    return (row.status == FAILED and row.dismissed_at is None) or is_no_reply(row, now)


# --- recording a hand-off (the engine's hook) ---


def _entry_id(context: dict):
    entry = context.get("entry") or {}
    return _uuid(entry.get("id") or (context.get("event") or {}).get("entry_id"))


def _declaration(declared):
    """The action's ``hands_off`` declaration, or None (an action of an older SDK has no such attribute)."""
    return getattr(declared, "hands_off", None)


def track(session, group_id, row, declared, args: dict, context: dict, *, out: dict | None = None, error: str | None = None) -> None:
    """Keep the hand-off an integration step just made (``out``, the provider's result) or failed to make (``error``, its message).
    Does nothing for an action that doesn't declare ``hands_off``. Never raises."""
    hands_off = _declaration(declared)
    if hands_off is None:
        return
    try:
        with session.begin_nested():
            _track(session, group_id, row, declared, hands_off, args, context, out or {}, error)
    except Exception as e:  # noqa: BLE001 — the record is a convenience: the step that handed the work off has already done so
        logger.warning("automation results: could not record the hand-off of %s.%s: %s", getattr(row, "slug", "?"), declared.key, e)


def _track(session, group_id, row, declared, hands_off, args: dict, context: dict, out: dict, error: str | None) -> None:
    now = _now()
    step = context.get("_step") or {}
    entry_id = _entry_id(context)
    workflow_id = _uuid(step.get("automation_id"))
    target = _text(args.get(hands_off.target)) if hands_off.target else None
    fields = {
        "group_id": group_id,
        "entry_id": entry_id,
        "integration_id": row.id,
        "workflow_id": workflow_id,
        "action": declared.key,
        "target": target,
        "sent_at": now,
        "attempt": 1,
        "dismissed_at": None,
        "dismissed_by": None,
    }
    if error is None:
        fields |= {
            "status": IN_FLIGHT,
            "remote_id": _text(out.get(hands_off.remote_id)) if hands_off.remote_id else None,
            "remote_url": _link(out.get(hands_off.remote_url)) if hands_off.remote_url else None,
            "message": None,
            "finished_at": None,
        }
    else:
        fields |= {"status": FAILED, "remote_id": None, "remote_url": None, "message": _text(error, MESSAGE_MAX), "finished_at": now}
    earlier = _failed_attempt(session, context, fields)
    if earlier is None:
        session.add(Result(session=session, **fields))
        return
    fields["attempt"] = earlier.attempt + 1
    for key, value in fields.items():
        setattr(earlier, key, value)


def _failed_attempt(session, context: dict, fields: dict) -> Result | None:
    """The failed result this hand-off is another try of: the one a person's Retry named, or — for a retry run — the newest failed,
    undismissed one for the same workflow, entry, connection, action and target."""
    chosen = context.get("_result_retry")
    if chosen:
        return session.get(Result, _uuid(chosen))
    if not context.get("_retry"):
        return None
    query = session.query(Result).filter(
        Result.group_id == fields["group_id"],
        Result.integration_id == fields["integration_id"],
        Result.status == FAILED,
        Result.dismissed_at.is_(None),
        Result.action == fields["action"],
        Result.workflow_id.is_(None) if fields["workflow_id"] is None else Result.workflow_id == fields["workflow_id"],
        Result.entry_id.is_(None) if fields["entry_id"] is None else Result.entry_id == fields["entry_id"],
        Result.target.is_(None) if fields["target"] is None else Result.target == fields["target"],
    )
    return query.order_by(Result.sent_at.desc()).first()


# --- settling it (the automation_result step) ---


def settle(
    session,
    group_id,
    *,
    status: str | None,
    word: str | None = None,
    integration: IntegrationModel | None = None,
    remote_id: str | None = None,
    entry_id=None,
    target: str | None = None,
    message: str | None = None,
    finished_at: datetime | None = None,
) -> tuple[Result, str]:
    """Apply a report to the hand-off it is about and return ``(row, matched)``: ``matched`` is ``remote_id``, ``entry`` or ``none``
    (the report matched nothing and was kept as a fresh row). ``status`` is Marvin's word, or None when the provider didn't know the
    one it was sent (``word``): the row then stays in flight with that word in its message."""
    now = _now()
    remote_id, message = _text(remote_id), _text(message, MESSAGE_MAX)
    if status is None:
        said = f"Reported an unrecognised status: {word!r}"
        message = f"{said}. {message}" if message else said
    row, matched = find(session, group_id, integration, remote_id, entry_id)
    status = status or IN_FLIGHT
    settled_at = _aware(finished_at) or now
    if row is None:
        row = Result(
            session=session,
            group_id=group_id,
            entry_id=entry_id,
            integration_id=integration.id if integration is not None else None,
            target=_text(target),
            remote_id=remote_id,
            status=status,
            message=message,
            sent_at=settled_at,
            finished_at=None if status == IN_FLIGHT else settled_at,
            attempt=1,
        )
        session.add(row)
        session.flush()
        return row, "none"
    row.status = status
    row.finished_at = None if status == IN_FLIGHT else settled_at
    if message is not None or status != FAILED:
        row.message = message
    if remote_id and not row.remote_id:
        row.remote_id = remote_id
    if status == FAILED:
        row.dismissed_at, row.dismissed_by = None, None  # a failure reported again asks for attention again
    session.flush()
    return row, matched


def find(session, group_id, integration, remote_id: str | None, entry_id) -> tuple[Result | None, str]:
    """The hand-off a report is about and how it was matched (``remote_id`` | ``entry`` | ``none``): see ``settle``."""
    base = session.query(Result).filter(Result.group_id == group_id)
    if integration is not None:
        base = base.filter(Result.integration_id == integration.id)
    if remote_id:
        row = base.filter(Result.remote_id == remote_id).order_by(Result.sent_at.desc()).first()
        if row is not None:
            return row, "remote_id"
    if entry_id is not None:
        row = base.filter(Result.entry_id == entry_id, Result.status == IN_FLIGHT).order_by(Result.sent_at.desc()).first()
        if row is not None:
            return row, "entry"
    return None, "none"


def entry_in(session, group_id, value):
    """The id of the workspace entry a step names (a UUID), or None when it names none or one that isn't here."""
    found = _uuid(value)
    if found is None:
        return None
    return session.query(Entries.id).filter(Entries.id == found, Entries.group_id == group_id).scalar()


def parse_moment(value) -> datetime | None:
    """A report's finish time (ISO 8601, with or without a zone, or epoch seconds/milliseconds), aware UTC; None when unreadable."""
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int | float) or (isinstance(value, str) and re.fullmatch(r"\d{9,13}(\.\d+)?", value.strip())):
        number = float(value)
        try:
            return datetime.fromtimestamp(number / 1000 if number > 1e11 else number, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return _aware(datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")))
    except ValueError:
        return None


# --- reading them (the Results API) ---


def _scope(session, group_id):
    return session.query(Result).filter(Result.group_id == group_id)


def summary(session, group_id) -> dict:
    """``{show, in_flight, no_reply, failed, succeeded, attention}``: ``show`` is whether a result has ever been kept (the page and
    its tab are drawn only then); ``in_flight`` excludes No reply; ``failed`` excludes dismissed ones; ``attention`` = failed + no reply."""
    now = _now()
    cutoff = now - NO_REPLY_AFTER
    flight = func.sum(sa.case((sa.and_(Result.status == IN_FLIGHT, Result.sent_at >= cutoff), 1), else_=0))
    late = func.sum(sa.case((sa.and_(Result.status == IN_FLIGHT, Result.sent_at < cutoff), 1), else_=0))
    failed = func.sum(sa.case((sa.and_(Result.status == FAILED, Result.dismissed_at.is_(None)), 1), else_=0))
    done = func.sum(sa.case((Result.status == SUCCEEDED, 1), else_=0))
    total, in_flight, no_reply, failed_n, succeeded = (
        session.query(func.count(Result.id), flight, late, failed, done).filter(Result.group_id == group_id).one()
    )
    counts = {"in_flight": int(in_flight or 0), "no_reply": int(no_reply or 0), "failed": int(failed_n or 0), "succeeded": int(succeeded or 0)}
    return {"show": bool(total), **counts, "attention": counts["failed"] + counts["no_reply"]}


def attention(session, group_id) -> tuple[int, int]:
    """``(failed, no reply)`` waiting for a person: what the dashboard shows."""
    counts = summary(session, group_id)
    return counts["failed"], counts["no_reply"]


def connections(session, group_id) -> list[tuple[str, str, str]]:
    """``(slug, name, provider)`` of every connection that has a result, by name: the Results page's connection filter."""
    rows = (
        session.query(IntegrationModel.slug, IntegrationModel.name, IntegrationModel.provider)
        .join(Result, Result.integration_id == IntegrationModel.id)
        .filter(Result.group_id == group_id)
        .distinct()
        .order_by(IntegrationModel.name)
        .all()
    )
    return [tuple(r) for r in rows]


def query(
    session,
    group_id,
    *,
    states: list[str] | None = None,
    connection: str | None = None,
    entry_id=None,
    text: str | None = None,
    include_dismissed: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Result], int]:
    """The results, newest first: filtered by state (any of in flight, no reply, failed, succeeded), connection slug, entry and text
    (in the target, message, remote id, the entry's title and the connection's name), and the page of them."""
    now = _now()
    q = _scope(session, group_id)
    q = _filtered(q, states, now)
    if connection:
        q = q.join(IntegrationModel, Result.integration_id == IntegrationModel.id).filter(IntegrationModel.slug == connection)
    if entry_id is not None:
        q = q.filter(Result.entry_id == entry_id)
    if not include_dismissed:
        q = q.filter(sa.or_(Result.dismissed_at.is_(None), Result.status != FAILED))
    if text and text.strip():
        return _search(session, q, text.strip(), limit, offset)
    total = q.count()
    return q.order_by(Result.sent_at.desc(), Result.id).offset(offset).limit(limit).all(), total


def _filtered(q, states: list[str] | None, now: datetime):
    if not states:
        return q
    cutoff = now - NO_REPLY_AFTER
    clauses = []
    for state in dict.fromkeys(states):
        if state == "no_reply":
            clauses.append(sa.and_(Result.status == IN_FLIGHT, Result.sent_at < cutoff))
        elif state == "in_flight":
            clauses.append(sa.and_(Result.status == IN_FLIGHT, Result.sent_at >= cutoff))
        else:
            clauses.append(Result.status == state)
    return q.filter(sa.or_(*clauses))


def _search(session, q, text: str, limit: int, offset: int) -> tuple[list[Result], int]:
    needle = text.lower()
    scanned = q.order_by(Result.sent_at.desc(), Result.id).limit(SEARCH_SCAN_LIMIT).all()
    titles = {
        r.id: (r.title or "")
        for r in session.query(Entries.id, Entries.title).filter(Entries.id.in_({x.entry_id for x in scanned if x.entry_id})).all()
    }
    names = {
        r.id: f"{r.name} {r.slug}"
        for r in session.query(IntegrationModel).filter(IntegrationModel.id.in_({x.integration_id for x in scanned if x.integration_id})).all()
    }
    hits = [
        r
        for r in scanned
        if needle
        in " ".join([r.target or "", r.message or "", r.remote_id or "", titles.get(r.entry_id, ""), names.get(r.integration_id, "")]).lower()
    ]
    return hits[offset : offset + limit], len(hits)


def get(session, group_id, result_id) -> Result | None:
    found = _uuid(result_id)
    return None if found is None else _scope(session, group_id).filter(Result.id == found).first()


def read(session, row: Result, *, now: datetime | None = None) -> dict:
    """One result as the API returns it (the entry, connection and workflow it names are looked up, and may be gone)."""
    return reads(session, [row], now=now)[0]


def reads(session, rows: list[Result], *, now: datetime | None = None) -> list[dict]:
    """The results as the API returns them, the entries, connections and workflows they name looked up once for the page."""
    now = now or _now()
    entry_ids = {r.entry_id for r in rows if r.entry_id}
    entries = {e[0]: e for e in session.query(Entries.id, Entries.title, Entries.slug).filter(Entries.id.in_(entry_ids)).all()} if entry_ids else {}
    connection_ids = {r.integration_id for r in rows if r.integration_id}
    connections = {c.id: c for c in session.query(IntegrationModel).filter(IntegrationModel.id.in_(connection_ids)).all()} if connection_ids else {}
    workflow_ids = {r.workflow_id for r in rows if r.workflow_id}
    workflows = (
        {w.id: w for w in session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.id.in_(workflow_ids)).all()} if workflow_ids else {}
    )
    out = []
    for row in rows:
        entry, connection, workflow = entries.get(row.entry_id), connections.get(row.integration_id), workflows.get(row.workflow_id)
        out.append(
            {
                "id": row.id,
                "status": row.status,
                "no_reply": is_no_reply(row, now),
                "entry": {"id": entry[0], "title": entry[1], "slug": entry[2]} if entry else None,
                "connection": {"slug": connection.slug, "name": connection.name, "provider": connection.provider} if connection else None,
                "workflow": {"id": workflow.id, "name": workflow.name, "slug": workflow.slug} if workflow else None,
                "target": row.target,
                "remote_id": row.remote_id,
                "remote_url": row.remote_url,
                "message": row.message,
                "sent_at": _aware(row.sent_at),
                "finished_at": _aware(row.finished_at),
                "attempt": row.attempt,
                "dismissed": row.dismissed_at is not None,
                "can_retry": can_retry(row),
            }
        )
    return out


def can_retry(row: Result) -> bool:
    """A failure that names the workflow step that made it and the entry it was about — whether that step can be run again safely is
    checked when the person asks (``retry``)."""
    return row.status == FAILED and row.workflow_id is not None and row.entry_id is not None and row.integration_id is not None and bool(row.action)


# --- acting on one ---


def dismiss(session, row: Result, user_id) -> Result:
    """Mark a failure dealt with: it stops asking for attention. Only a failed result can be dismissed."""
    if row.status != FAILED:
        raise ResultError("Only a failed hand-off can be dismissed.")
    if row.dismissed_at is None:
        row.dismissed_at, row.dismissed_by = _now(), user_id
        session.flush()
    return row


# --- retention ---


def prune(session, settled_before: datetime, unhandled_before: datetime) -> int:
    """Delete settled results (and dismissed failures) that finished before ``settled_before``, and in-flight or undismissed-failed ones
    sent before ``unhandled_before``; returns how many."""
    handled = sa.or_(Result.status == SUCCEEDED, sa.and_(Result.status == FAILED, Result.dismissed_at.isnot(None)))
    ended = func.coalesce(Result.finished_at, Result.sent_at)
    deleted = session.query(Result).filter(handled, ended < settled_before).delete(synchronize_session=False)
    deleted += session.query(Result).filter(sa.not_(handled), Result.sent_at < unhandled_before).delete(synchronize_session=False)
    session.commit()
    return deleted


# --- Retry ---

# What a repeated hand-off step can read: the entry as it is now and the site. Anything else in its arguments (the triggering event's
# payload, an earlier step's output) belonged to the run that is over, and would come out empty.
_RETRY_READS = frozenset({"entry", "site"})
_BRACED = re.compile(r"\$\{([^}]+)\}")


def _reads(value) -> set[str]:
    """The roots of the ``${…}`` / ``$…`` templates in a step (``entry`` for ``${entry.title|truncate:20}``)."""
    found: set[str] = set()
    if isinstance(value, str):
        for path in _BRACED.findall(value):
            found.add(re.split(r"[.|\[ ]", path.strip(), maxsplit=1)[0])
        if value.startswith("$") and not value.startswith("${"):
            found.add(re.split(r"[.|\[ ]", value[1:], maxsplit=1)[0])
    elif isinstance(value, dict):
        for item in value.values():
            found |= _reads(item)
    elif isinstance(value, list):
        for item in value:
            found |= _reads(item)
    return found


def _target_key(connection: IntegrationModel, action: str) -> str:
    """The argument the provider's ``hands_off`` declaration says names the target (empty when it names none, or the provider is gone)."""
    from marvin.services.integrations import get_provider

    try:
        declared = get_provider(connection.provider).get_action(action)
    except KeyError:
        return ""
    return getattr(getattr(declared, "hands_off", None), "target", "") or ""


def _hand_off_step(session, group_id, row: Result, automation) -> tuple[int, dict, dict]:
    """``(index, step, context)`` for the one step of the workflow that handed this off, or a ResultError saying why it can't be found
    or repeated safely."""
    from marvin.services.automation import engine
    from marvin.services.automation.matcher import interpolate, matches

    connection = session.get(IntegrationModel, row.integration_id)
    defn = automation.definition or {}
    actions = (defn.get("actions") or [])[: engine.workflow_max_steps(session, group_id)]
    candidates = [
        (i, a)
        for i, a in enumerate(actions)
        if a.get("kind") == "integration" and a.get("action") == row.action and connection is not None and a.get("integration") == connection.slug
    ]
    if not candidates:
        raise ResultError(f"The workflow “{automation.name}” no longer has the step that handed this off, so there is nothing to repeat.")
    entry_context = engine._entry_context(session, group_id, row.entry_id)
    if entry_context is None:
        raise ResultError("The entry is gone, so the hand-off can't be repeated.")
    context: dict = {
        "event": {"event_type": "manual", "entry_id": str(row.entry_id)},
        "depth": 0,
        "site": engine._site_context(session, group_id),
        "entry": entry_context,
    }
    if len(candidates) > 1:  # several hand-offs on one connection: the one that asked for this target
        key = _target_key(connection, row.action)
        candidates = [(i, a) for i, a in candidates if key and str(interpolate((a.get("args") or {}).get(key), context) or "") == (row.target or "")]
    if len(candidates) != 1:
        raise ResultError(f"The workflow “{automation.name}” has more than one step like it, so Marvin can't tell which one to repeat.")
    index, step = candidates[0]
    outside = (_reads(step) | _reads(defn.get("conditions"))) - _RETRY_READS
    if outside:
        raise ResultError(
            "That step reads from the run that first started it (" + ", ".join(sorted(f"${{{r}…}}" for r in outside)) + "), "
            "which is over. Open the entry and run the workflow again instead."
        )
    if not matches(defn.get("conditions"), context):
        raise ResultError("The entry no longer matches the workflow's conditions, so the hand-off isn't repeated.")
    if step.get("when") and not matches(step["when"], context):
        raise ResultError("The step's own condition (when) doesn't hold for the entry now, so it isn't repeated.")
    return index, step, context


def retry(session, group_id, row: Result, user_id, logger=None) -> Result:
    """Repeat a failed hand-off: run the step of the Marvin workflow that made it, alone, for the same entry, as the entry is now.

    Only that one step runs (the rest of the workflow, which may have posted or emailed, does not), under the workflow author's
    authority as every run of it is. It is refused, with the reason, when it can't be done honestly: the workflow is gone or
    switched off, its step is gone or ambiguous, the entry is gone or no longer matches, or the step reads from the run that first
    started it (``${event.payload…}``, an earlier step's output), which a repeat can't supply. A repeat that fails again is the same
    result with its attempt counted up; one that goes out is in flight again and waits for the reply as any hand-off does. The
    provider's error policy doesn't schedule further retries for it: the person is the retry."""
    from marvin.services.automation import engine

    if not can_retry(row):
        raise ResultError("Only a failed hand-off from a workflow can be retried.")
    automation = session.get(WorkspaceAutomationModel, row.workflow_id)
    if automation is None or automation.group_id != group_id:
        raise ResultError("The workflow that sent this was deleted, so there is nothing to repeat.")
    if not automation.enabled:
        raise ResultError(f"The workflow “{automation.name}” is switched off. Turn it on to retry.")
    index, _, context = _hand_off_step(session, group_id, row, automation)
    context["_result_retry"] = str(row.id)
    before = (row.attempt, row.sent_at)
    error = engine.run_step_once(session, group_id, automation, index, context, user_id=user_id, logger=logger)
    session.refresh(row)
    if (row.attempt, row.sent_at) == before:  # nothing was recorded: the step refused before calling out, or was skipped as a duplicate
        if error:
            raise ResultError(f"Nothing was sent: {error}")
        raise ResultError("Nothing new was recorded: the step's idempotency key may say it already went out.")
    return row
