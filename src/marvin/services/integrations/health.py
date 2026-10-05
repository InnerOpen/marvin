"""The Alerts & health page — what integration error handling is doing across one workspace.

Read side: open and resolved alerts, live retries, failed steps a provider's policy handled, and a
one-row-per-connection summary. Write side: two admin levers on a live retry — **retry now** (due now;
the sweep runs it on its next tick, never the request) and **give up** (the chain ends, nothing else
happens). Both are a single conditional UPDATE, so they never fight the sweep's claim
(:func:`errors.claim_next` is conditional too): a row the sweep holds is refused until its lease runs out.

Everything is filtered by ``group_id``. Nothing here returns secrets: messages were redacted when they
were stored, and snapshots, partial progress and idempotency seeds stay on the server.

SDK-free (only the database), so it is importable — and tested — without ``marvin_integration_sdk``.
"""

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
from marvin.db.models.groups.automations import WorkspaceAutomationModel
from marvin.db.models.groups.integration_errors import RETRY_LIVE, IntegrationAlertModel, IntegrationRetryModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.schemas.group.integration import (
    HandledFailurePage,
    HandledFailureRead,
    IntegrationAlertPage,
    IntegrationAlertRead,
    IntegrationHealthRow,
    IntegrationRetryRead,
)

from . import errors

HANDLED_WINDOW = timedelta(days=7)
MAX_PER_PAGE = 100
MAX_LIVE_RETRIES = 500
GIVEN_UP = "given up by an admin"
"""The reason a retry the admin gave up on keeps (its status is ``superseded``)."""

_HANDLED_WORDS = {
    "review": "sent to review",
    "flagged": "flagged on the entry (left published)",
    "notify": "admins notified",
    "succeed": "ignored",
    "exhausted": "retries used up",
}


class RetryConflict(Exception):
    """The retry can't take that action in its current state (the sweep holds it, or it finished)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    return errors._aware(value)


def _per_page(per_page: int) -> int:
    return max(1, min(int(per_page or 1), MAX_PER_PAGE))


def _page(page: int) -> int:
    return max(1, int(page or 1))


def _as_uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _entry_titles(session, group_id, ids) -> dict:
    """{entry id: title} for the entries that still exist in the workspace."""
    from marvin.db.models.platform import Entries

    wanted = {i for i in (_as_uuid(v) for v in ids) if i is not None}
    if not wanted:
        return {}
    rows = session.query(Entries.id, Entries.title).filter(Entries.group_id == group_id, Entries.id.in_(wanted)).all()
    return {r.id: r.title for r in rows}


def _automations(session, group_id, ids) -> dict:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = (
        session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == group_id, WorkspaceAutomationModel.id.in_(wanted)).all()
    )
    return {r.id: r for r in rows}


def _integrations(session, group_id) -> dict:
    """The workspace's connections, by id."""
    return {r.id: r for r in session.query(IntegrationModel).filter(IntegrationModel.group_id == group_id).all()}


# ── alerts ──────────────────────────────────────────────────────────────────────


def _alert_read(alert: IntegrationAlertModel, *, name: str | None, reminder_hours: int, resolver: str | None) -> IntegrationAlertRead:
    notified = _aware(alert.notified_at)
    first, resolved = _aware(alert.first_at), _aware(alert.resolved_at)
    remind_after = notified + timedelta(hours=reminder_hours) if alert.status == "open" and notified and reminder_hours > 0 else None
    return IntegrationAlertRead(
        id=alert.id,
        integration_id=alert.integration_id,
        integration_name=name,
        integration_slug=alert.integration_slug,
        provider=alert.provider,
        provider_name=errors._provider_name(alert.provider),
        code=alert.code,
        message=alert.message,
        count=alert.count or 0,
        status=alert.status,
        first_at=first,
        last_at=_aware(alert.last_at),
        notified_at=notified,
        remind_after=remind_after,
        reminder_hours=reminder_hours,
        resolved_at=resolved,
        resolution=alert.resolution,
        resolved_by_name=resolver,
        open_seconds=int((resolved - first).total_seconds()) if resolved and first else None,
    )


def list_alerts(session, group_id, *, status: str = "open", page: int = 1, per_page: int = 25) -> IntegrationAlertPage:
    """Open alerts (latest failure first) or resolved ones (latest resolution first), a page at a time."""
    from marvin.db.models.users.users import Users

    page, per_page = _page(page), _per_page(per_page)
    query = session.query(IntegrationAlertModel).filter(IntegrationAlertModel.group_id == group_id, IntegrationAlertModel.status == status)
    order = IntegrationAlertModel.resolved_at.desc() if status == "resolved" else IntegrationAlertModel.last_at.desc()
    total = query.count()
    rows = query.order_by(order, IntegrationAlertModel.id).offset((page - 1) * per_page).limit(per_page).all()

    names = {r.id: r.name for r in session.query(IntegrationModel.id, IntegrationModel.name).filter(IntegrationModel.group_id == group_id)}
    resolver_ids = {r.resolved_by for r in rows if r.resolved_by}
    resolvers = {u.id: u.full_name or u.username for u in session.query(Users).filter(Users.id.in_(resolver_ids))} if resolver_ids else {}
    hours = errors._reminder_hours(session, group_id)
    items = [_alert_read(r, name=names.get(r.integration_id), reminder_hours=hours, resolver=resolvers.get(r.resolved_by)) for r in rows]
    return IntegrationAlertPage(items=items, page=page, per_page=per_page, total=total)


# ── retries ─────────────────────────────────────────────────────────────────────


def _retry_reads(session, group_id, rows: list[IntegrationRetryModel]) -> list[IntegrationRetryRead]:
    automations = _automations(session, group_id, {r.automation_id for r in rows})
    titles = _entry_titles(session, group_id, {r.entry_id for r in rows})
    connections = _integrations(session, group_id)
    reads = []
    for row in rows:
        automation = automations.get(row.automation_id)
        connection = connections.get(row.integration_id)
        snapshot_entry = (row.snapshot or {}).get("entry") or {}
        exists = row.entry_id in titles
        reads.append(
            IntegrationRetryRead(
                id=row.id,
                status=row.status,
                automation_id=row.automation_id,
                automation_name=automation.name if automation else None,
                automation_enabled=bool(automation.enabled) if automation else False,
                entry_id=row.entry_id,
                # The entry as it is now, or the title the run saw (it may since have been deleted).
                entry_title=titles.get(row.entry_id) if exists else (snapshot_entry.get("title") if row.entry_id else None),
                entry_exists=exists,
                integration_id=row.integration_id,
                integration_name=connection.name if connection else None,
                integration_slug=row.integration_slug,
                provider=row.provider,
                provider_name=errors._provider_name(row.provider),
                action=row.action,
                code=row.code,
                attempt=row.attempt or 0,
                max_attempts=row.max_attempts or 0,
                next_attempt_at=_aware(row.next_attempt_at),
                lease_until=_aware(row.lease_until),
                last_error=row.last_error,
                created_at=_aware(row.created_at),
            )
        )
    return reads


def list_retries(session, group_id) -> list[IntegrationRetryRead]:
    """Live retries: running first, then by when they're due; parked ones (no due time) last."""
    rank = sa.case((IntegrationRetryModel.status == "running", 0), (IntegrationRetryModel.status == "pending", 1), else_=2)
    rows = (
        session.query(IntegrationRetryModel)
        .filter(IntegrationRetryModel.group_id == group_id, IntegrationRetryModel.status.in_(RETRY_LIVE))
        .order_by(rank, IntegrationRetryModel.next_attempt_at.asc(), IntegrationRetryModel.created_at.asc())
        .limit(MAX_LIVE_RETRIES)
        .all()
    )
    return _retry_reads(session, group_id, rows)


def _retry_or_none(session, group_id, retry_id) -> IntegrationRetryModel | None:
    row = session.get(IntegrationRetryModel, retry_id)
    return row if row is not None and row.group_id == group_id else None


def _conditional(session, group_id, retry_id, allowed, values: dict) -> bool:
    """Update the row only if it is still in an allowed state — the sweep may claim it at any moment."""
    updated = (
        session.query(IntegrationRetryModel)
        .filter(IntegrationRetryModel.id == retry_id, IntegrationRetryModel.group_id == group_id, allowed)
        .update(values, synchronize_session=False)
    )
    session.commit()
    return bool(updated)


def retry_now(session, group_id, retry_id) -> IntegrationRetryRead | None:
    """Make a pending or parked retry due now; the sweep runs it on its next tick (about a minute).
    None if there is no such retry in the workspace; RetryConflict if it is running or finished."""
    row = _retry_or_none(session, group_id, retry_id)
    if row is None:
        return None
    ok = _conditional(
        session,
        group_id,
        retry_id,
        IntegrationRetryModel.status.in_(("pending", "parked")),
        {"status": "pending", "next_attempt_at": _now(), "lease_until": None},
    )
    session.refresh(row)
    if not ok:
        raise RetryConflict("It's running right now." if row.status == "running" else "It has already finished.")
    return _retry_reads(session, group_id, [row])[0]


def give_up(session, group_id, retry_id) -> IntegrationRetryRead | None:
    """End a live retry chain: superseded, no more attempts, and nothing else applied (no `then`, no
    review, no alert). A running retry is refused unless its lease ran out (the run died mid-way).
    None if there is no such retry in the workspace; RetryConflict if it is running or finished."""
    row = _retry_or_none(session, group_id, retry_id)
    if row is None:
        return None
    now = _now()
    allowed = IntegrationRetryModel.status.in_(("pending", "parked")) | (
        (IntegrationRetryModel.status == "running") & (IntegrationRetryModel.lease_until < now)
    )
    ok = _conditional(
        session,
        group_id,
        retry_id,
        allowed,
        {"status": "superseded", "live_key": None, "lease_until": None, "next_attempt_at": None, "finished_at": now, "last_error": GIVEN_UP},
    )
    session.refresh(row)
    if not ok:
        raise RetryConflict("It's running right now; try again once it finishes." if row.status == "running" else "It has already finished.")
    return _retry_reads(session, group_id, [row])[0]


# ── handled failures ────────────────────────────────────────────────────────────


def _has_handling():
    # The recorder writes handling=None as JSON null on some backends; count only real records.
    column = AutomationActionExecutionModel.handling
    return column.isnot(None) & (sa.cast(column, sa.String) != "null")


def _chain_outcome(retry: IntegrationRetryModel) -> str:
    n, of = retry.attempt or 0, retry.max_attempts or 0
    return {
        "succeeded": f"retried, succeeded on retry {n}",
        "pending": f"retry {n + 1} of {of} scheduled",
        "parked": "will retry when the connection recovers",
        "running": f"retry {n} of {of} running",
        "exhausted": "retries used up",
        "failed": "retry chain ended",
        "superseded": GIVEN_UP if retry.last_error == GIVEN_UP else "retry no longer needed",
    }.get(retry.status, retry.status)


def _outcome(handling: dict, retry: IntegrationRetryModel | None) -> str:
    """ "sent to review", "admins notified, retried, succeeded on retry 2", … — the immediate effects the
    policy applied, then where its retry chain is now. Falls back to the summary stored with the step."""
    applied = handling.get("applied") or []
    parts = [_HANDLED_WORDS[a] for a in applied if a in _HANDLED_WORDS and a != "exhausted"]
    if retry is not None:
        parts.append(_chain_outcome(retry))
    elif "exhausted" in applied:
        parts.append(_HANDLED_WORDS["exhausted"])
    elif any(a in ("retry", "parked") for a in applied) or handling.get("retry"):
        summary = str(handling.get("summary") or "")
        tail = summary.split(": ", 1)[1] if ": " in summary else summary
        return tail or "retry scheduled"
    return ", ".join(parts) or "fails as usual"


def handled_failures(session, group_id, *, since: datetime | None = None, page: int = 1, per_page: int = 25) -> HandledFailurePage:
    """Failed integration steps whose provider's policy took them in hand, newest first."""
    page, per_page = _page(page), _per_page(per_page)
    since = _aware(since) if since else _now() - HANDLED_WINDOW
    query = (
        session.query(AutomationActionExecutionModel, AutomationExecutionModel)
        .join(AutomationExecutionModel, AutomationExecutionModel.id == AutomationActionExecutionModel.execution_id)
        .filter(
            AutomationActionExecutionModel.group_id == group_id,
            AutomationExecutionModel.group_id == group_id,
            AutomationActionExecutionModel.created_at >= since,
            _has_handling(),
        )
    )
    total = query.count()
    rows = (
        query.order_by(AutomationActionExecutionModel.created_at.desc(), AutomationActionExecutionModel.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    handlings = [(step, run, step.handling if isinstance(step.handling, dict) else {}) for step, run in rows]
    retry_ids = {_as_uuid((h.get("retry") or {}).get("id")) for _, _, h in handlings} - {None}
    retries = (
        {
            r.id: r
            for r in session.query(IntegrationRetryModel).filter(IntegrationRetryModel.group_id == group_id, IntegrationRetryModel.id.in_(retry_ids))
        }
        if retry_ids
        else {}
    )
    entry_ids = {_as_uuid(step.target_entity_id) for step, _, _ in handlings if step.target_entity_type == "entry"} - {None}
    titles = _entry_titles(session, group_id, entry_ids)
    automations = _automations(session, group_id, {run.automation_id for _, run, _ in handlings})
    slugs = {c.slug: c for c in _integrations(session, group_id).values()}

    items = []
    for step, run, handling in handlings:
        retry = retries.get(_as_uuid((handling.get("retry") or {}).get("id")))
        entry_id = _as_uuid(step.target_entity_id) if step.target_entity_type == "entry" else None
        slug = handling.get("integration")
        action = (step.label or "").removeprefix("on failure: ").split(".", 1)[1] if "." in (step.label or "") else None
        connection = slugs.get(slug)
        automation = automations.get(run.automation_id)
        items.append(
            HandledFailureRead(
                id=step.id,
                execution_id=run.id,
                run_status=run.status,
                is_retry=run.retry_of_id is not None,
                at=_aware(step.created_at),
                automation_id=run.automation_id,
                automation_name=automation.name if automation else run.automation_slug,
                entry_id=entry_id,
                entry_title=titles.get(entry_id),
                entry_exists=entry_id in titles,
                integration_id=connection.id if connection else None,
                integration_slug=slug,
                provider=handling.get("provider"),
                provider_name=handling.get("provider_name") or (errors._provider_name(handling["provider"]) if handling.get("provider") else None),
                action=action,
                code=handling.get("code"),
                error=step.error,
                outcome=_outcome(handling, retry),
                retry_status=retry.status if retry else None,
            )
        )
    return HandledFailurePage(items=items, page=page, per_page=per_page, total=total, since=since)


# ── health summary ──────────────────────────────────────────────────────────────


def _failures_by_slug(session, group_id, since: datetime) -> dict[str, int]:
    """Failed integration steps per connection slug (labels read "<slug>.<action>")."""
    step = AutomationActionExecutionModel
    rows = (
        session.query(step.label, sa.func.count(step.id))
        .filter(
            step.group_id == group_id,
            step.kind == "integration",
            step.created_at >= since,
            (step.status == "failed") | _has_handling(),
        )
        .group_by(step.label)
        .all()
    )
    counts: dict[str, int] = {}
    for label, count in rows:
        slug = (label or "").removeprefix("on failure: ").split(".", 1)[0]
        if slug:
            counts[slug] = counts.get(slug, 0) + count
    return counts


def _installed(provider: str) -> bool:
    try:
        from marvin.services.integrations import INTEGRATION_REGISTRY
    except ImportError:  # no SDK: nothing is installed
        return False
    return provider in INTEGRATION_REGISTRY


def health(session, group_id) -> list[IntegrationHealthRow]:
    """One row per connection: last successful action, last check, 7-day failures, open alerts, live retries."""
    connections = session.query(IntegrationModel).filter(IntegrationModel.group_id == group_id).order_by(IntegrationModel.name).all()
    failures = _failures_by_slug(session, group_id, _now() - HANDLED_WINDOW)
    alerts = errors.open_alerts(session, group_id)
    live = dict(
        session.query(IntegrationRetryModel.integration_id, sa.func.count(IntegrationRetryModel.id))
        .filter(IntegrationRetryModel.group_id == group_id, IntegrationRetryModel.status.in_(RETRY_LIVE))
        .group_by(IntegrationRetryModel.integration_id)
        .all()
    )
    rows = []
    for c in connections:
        open_alerts = alerts.get(c.id, [])
        installed = _installed(c.provider)
        rows.append(
            IntegrationHealthRow(
                id=c.id,
                name=c.name,
                slug=c.slug,
                provider=c.provider,
                provider_name=errors._provider_name(c.provider),
                enabled=c.enabled,
                status=c.status if installed else "unavailable",
                last_checked_at=_aware(c.last_checked_at),
                last_error=c.last_error if installed else f"Provider '{c.provider}' is not installed.",
                last_success_at=_aware(c.last_success_at),
                failures_7d=failures.get(c.slug, 0),
                open_alerts=len(open_alerts),
                alert_codes=[a.code for a in open_alerts],
                live_retries=live.get(c.id, 0),
            )
        )
    return rows
