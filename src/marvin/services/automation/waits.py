"""Wait steps: a workflow run that goes on later (``{"kind": "wait", …}``).

**When.** ``for`` waits a while (``3d``, ``12h``, ``2w``, ``30m``); ``until`` waits for a moment — a date or a datetime,
usually a template (``${entry.data.event_date}``) — moved by ``offset`` (``-7d``: a week before) and, for a date, at
the time of day ``at`` (default 09:00), all read in the workspace's time zone (Settings → Site: ``site_timezone``), so
"a week before, at nine" stays nine across a clock change. A moment already past doesn't wait (``late``).

**Park.** As an approval does (approvals.py): the run's snapshot goes into a ``workflow_waits`` row, the step is recorded
``waiting``, the run ends ``waiting``.

**Resume.** ``resume_due`` (the minutely sweep) claims each wait whose time has come and ``engine.resume_after_wait``
runs the steps after it in a new run (``retry_of`` the parked one), re-reading the entry as it is now — unless the
workflow was switched off or changed, or the entry went to the Trash meanwhile (then the wait is ``cancelled``).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from marvin.db.models.groups.workflow_waits import WAIT_WAITING, WorkflowWaitModel

from .actions.base import AutomationActionError

MAX_WAIT = timedelta(days=366)
DEFAULT_AT = time(9, 0)
DEFAULT_TIMEZONE = "America/New_York"  # the site settings' own default
SPAN = re.compile(r"^\s*([+-]?)(\d{1,4})\s*([mhdw])\s*$", re.IGNORECASE)
UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
CLOCK = re.compile(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$")
MAX_DUE_PER_SWEEP = 100


def now() -> datetime:
    return datetime.now(UTC)


def span(text, *, signed: bool = False) -> timedelta | None:
    """``"3d"`` → 3 days (``"-7d"`` too when ``signed``); None when it isn't one."""
    m = SPAN.match(str(text or ""))
    if not m or (m.group(1) and not signed):
        return None
    delta = timedelta(**{UNITS[m.group(3).lower()]: int(m.group(2))})
    return -delta if m.group(1) == "-" else delta


def workspace_zone(session, group_id) -> ZoneInfo:
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    prefs = session.query(GroupPreferencesModel).filter(GroupPreferencesModel.group_id == group_id).first()
    try:
        return ZoneInfo((prefs.site_timezone if prefs and prefs.site_timezone else None) or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def resume_time(session, group_id, *, wait_for=None, until=None, offset=None, at=None, now_: datetime | None = None) -> datetime:
    """When the run goes on (aware, UTC). Raises AutomationActionError saying what can't be read."""
    now_ = now_ or now()
    if wait_for not in (None, ""):
        delta = span(wait_for)
        if delta is None:
            raise AutomationActionError(f"wait for {wait_for!r}: give a span like 30m, 12h, 3d or 2w")
        return now_ + delta
    if until in (None, ""):
        raise AutomationActionError("a wait needs `for` (a span) or `until` (a date) — the until resolved to empty")
    zone = workspace_zone(session, group_id)
    moment = _moment(str(until).strip(), zone, at)
    if offset not in (None, ""):
        delta = span(offset, signed=True)
        if delta is None:
            raise AutomationActionError(f"offset {offset!r}: give a span like -7d, -12h or +1w")
        # Calendar arithmetic in the workspace's zone: a week before 9:00 is 9:00, a clock change between or not.
        moment = (moment.astimezone(zone).replace(tzinfo=None) + delta).replace(tzinfo=zone)
    return moment.astimezone(UTC)


def _moment(text: str, zone: ZoneInfo, at) -> datetime:
    clock = DEFAULT_AT
    if at not in (None, ""):
        m = CLOCK.match(str(at))
        if not m:
            raise AutomationActionError(f"at {at!r}: give a time of day like 09:00")
        clock = time(int(m.group(1)), int(m.group(2)))
    try:
        if len(text) == 10:  # a date: at the time of day, in the workspace's zone
            return datetime.combine(date.fromisoformat(text), clock, tzinfo=zone)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise AutomationActionError(f"until {text!r} isn't a date (YYYY-MM-DD) or a date and time") from e
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)


def check_reach(when: datetime, now_: datetime | None = None) -> None:
    if when - (now_ or now()) > MAX_WAIT:
        raise AutomationActionError(f"a wait is at most a year: {when.date().isoformat()} is further off")


def park(session, group_id, automation, context: dict, *, exec_id, step_index: int, target_index: int, step_id, spec: dict, run: dict):
    """Keep the run at this step until ``spec["resume_at"]``. Raises AutomationActionError when it can't wait."""
    from marvin.services.integrations.errors import _snapshot

    automation_id = getattr(automation, "id", None)
    if automation_id is None:
        raise AutomationActionError("a wait step needs a saved workflow to come back to")
    snapshot = _snapshot(context, run)
    if snapshot is None:
        raise AutomationActionError("this run is too large to wait")
    row = WorkflowWaitModel(
        session=session,
        group_id=group_id,
        automation_id=automation_id,
        execution_id=exec_id if exec_id is not None and not isinstance(exec_id, str) else None,
        step_index=step_index,
        step_id=step_id,
        target_index=target_index,
        resume_at=spec["resume_at"],
        status=WAIT_WAITING,
        snapshot=snapshot,
        entry_id=(context.get("entry") or {}).get("id"),
    )
    session.add(row)
    session.commit()
    return row


def resume_due(session, *, logger=None, now_: datetime | None = None) -> int:
    """Go on with every run whose wait is over. Each is claimed first, so two sweeps can't both resume it."""
    from sqlalchemy import update

    from .engine import resume_after_wait

    due = (
        session.query(WorkflowWaitModel)
        .filter(WorkflowWaitModel.status == WAIT_WAITING, WorkflowWaitModel.resume_at <= (now_ or now()))
        .order_by(WorkflowWaitModel.resume_at)
        .limit(MAX_DUE_PER_SWEEP)
        .all()
    )
    done = 0
    for row in due:
        claimed = session.execute(
            update(WorkflowWaitModel).where(WorkflowWaitModel.id == row.id, WorkflowWaitModel.status == WAIT_WAITING).values(status="resumed")
        ).rowcount
        session.commit()
        if not claimed:
            continue
        session.refresh(row)
        try:
            resume_after_wait(session, row, logger=logger)
            done += 1
        except Exception as e:  # noqa: BLE001 — one run's failure mustn't stop the others going on
            session.rollback()
            if logger:
                logger.error(f"resuming wait {row.id} failed: {e}", exc_info=True)
    return done


def cancel(session, row: WorkflowWaitModel, why: str) -> None:
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    row.status, row.note = "cancelled", why
    parked = session.get(AutomationExecutionModel, row.execution_id) if row.execution_id else None
    if parked is not None and parked.status == "waiting":
        parked.status = "cancelled"
        parked.error = why
    session.commit()
