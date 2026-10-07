"""Backup health: what the backup targets' runs say, when each target runs next, and whether one has gone
quiet — for Admin → Backup health and the ``backup_completed`` / ``backup_failed`` events.

The backend can't see Kubernetes, so the backup CronJobs report to it through the database: each run of
``python -m marvin.scripts.backup run`` writes a ``backup_runs`` row at its end, whatever its outcome
(``services/backup_engine/recorder.py``), carrying the CronJob's schedule and time zone. From those rows:

- a **target** is every name that has recorded a run (one the backend has never heard from can't be
  known: its first run, or its first failure, introduces it);
- its **next run** comes from the recorded schedule (``cron``);
- it is **overdue** when no successful run started within ``overdue_window(interval)`` of the last one
  (hourly: 2 h, daily: 26 h, plus ``GRACE``): the job didn't run, died before recording itself, or keeps
  failing. A target that never succeeded counts from its first recorded run.

``check`` (a scheduler task, on the leader only) turns rows into events: an overdue target first gets
one ``missed`` row per incident — the marker, so the next check doesn't repeat it; the incident ends with
the next successful run — then every row the backend hasn't announced yet is dispatched: a job's run →
``backup_completed`` (ok) or ``backup_failed`` (failed, partial); a ``missed`` row → ``backup_failed``
(reason ``overdue``). Failed runs alert once per incident, too (the run of non-ok rows since the last ok
one): the CronJob retries a failing run (``backoffLimit: 2``), so one bad hour records up to three failed
runs, and only the first is sent. The ok run that ends an incident is sent as ``backup_completed`` with
reason ``recovered``.
Runs older than ``RUN_RETENTION`` are deleted, so a target removed from the chart drops off the page.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from marvin.db.models.platform.backup_runs import (
    STATUS_FAILED,
    STATUS_MISSED,
    STATUS_OK,
    STATUS_PARTIAL,
    BackupRunModel,
)

from . import cron

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

GRACE = timedelta(minutes=15)
"""On top of the window: a run takes a few minutes between its start and the row it writes."""
MAX_SLACK = timedelta(hours=2)
"""How many missed intervals' worth of slack a target gets, at most: one for hourly, two hours for daily."""
RUN_RETENTION = timedelta(days=90)
ANNOUNCE_WITHIN = timedelta(days=1)
"""A run recorded longer ago than this (the backend was down meanwhile) is marked announced, not announced."""
INTEGRATION_ID = "backup_health"


def overdue_window(interval: timedelta) -> timedelta:
    """How long after a successful run's start the next one may take: one interval, plus one more for a
    short one (hourly → 2 h) or two hours for a long one (daily → 26 h), plus GRACE."""
    return interval + min(interval, MAX_SLACK) + GRACE


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


@dataclass
class TargetHealth:
    name: str
    type: str
    state: str
    """ok, partial, failed, overdue, or unknown (no schedule recorded yet, nothing to compare with)."""
    schedule: str | None = None
    time_zone: str | None = None
    schedule_error: str | None = None
    interval: timedelta | None = None
    retention: tuple[int | None, int | None, int | None] = (None, None, None)
    location: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    last_run: BackupRunModel | None = None
    """The newest run a job recorded (not a ``missed`` marker)."""
    last_success: BackupRunModel | None = None
    first_seen: datetime | None = None
    next_run_at: datetime | None = None
    due_by: datetime | None = None
    """When the target becomes overdue without a successful run (past: it is)."""
    overdue: bool = False
    overdue_since: datetime | None = None
    """When the current overdue incident was detected (its ``missed`` row), if it has been."""


def _latest(session: Session, name: str, statuses: tuple[str, ...]) -> BackupRunModel | None:
    return (
        session.query(BackupRunModel)
        .filter(BackupRunModel.target_name == name, BackupRunModel.status.in_(statuses))
        .order_by(BackupRunModel.started_at.desc())
        .first()
    )


def target_names(session: Session) -> list[str]:
    return [n for (n,) in session.query(BackupRunModel.target_name).distinct().order_by(BackupRunModel.target_name)]


def target_health(session: Session, name: str, now: datetime | None = None) -> TargetHealth:
    now = _utc(now) or datetime.now(UTC)
    last_run = _latest(session, name, (STATUS_OK, STATUS_PARTIAL, STATUS_FAILED))
    last_success = _latest(session, name, (STATUS_OK,))
    last_missed = _latest(session, name, (STATUS_MISSED,))
    first_seen = session.query(sa.func.min(BackupRunModel.started_at)).filter(BackupRunModel.target_name == name).scalar()
    described = last_run or last_missed
    health = TargetHealth(
        name=name,
        type=described.target_type if described else "",
        state="unknown",
        last_run=last_run,
        last_success=last_success,
        first_seen=_utc(first_seen),
    )
    if described is not None:
        health.schedule = described.schedule
        health.time_zone = described.time_zone
        health.retention = (described.keep_hourly, described.keep_daily, described.keep_weekly)
        health.location = described.location
        health.settings = dict(described.settings_json or {})

    if health.schedule:
        try:
            schedule = cron.parse(health.schedule, health.time_zone)
        except ValueError as e:
            health.schedule_error = str(e)
        else:
            health.next_run_at = schedule.next_after(now)
            health.interval = schedule.interval(now)
    else:
        health.schedule_error = "no schedule recorded (the CronJob predates BACKUP_SCHEDULE: upgrade the chart)"

    since = _utc(last_success.started_at) if last_success else health.first_seen
    if health.interval is not None and since is not None:
        health.due_by = since + overdue_window(health.interval)
        health.overdue = now > health.due_by
    if last_missed is not None and (since is None or _utc(last_missed.started_at) > since):
        health.overdue_since = _utc(last_missed.started_at)

    if health.overdue:
        health.state = "overdue"
    elif last_run is not None:
        health.state = last_run.status
    return health


def all_targets(session: Session, now: datetime | None = None) -> list[TargetHealth]:
    return [target_health(session, name, now) for name in target_names(session)]


def recent_runs(session: Session, limit: int = 50, target: str | None = None) -> list[BackupRunModel]:
    q = session.query(BackupRunModel)
    if target:
        q = q.filter(BackupRunModel.target_name == target)
    return q.order_by(BackupRunModel.started_at.desc()).limit(max(1, min(limit, 500))).all()


# --------------------------------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------------------------------


def _size(n: int | None) -> str | None:
    if not n:
        return None
    return f"{n / 1_000_000:.1f} MB"


def _event_data(run: BackupRunModel, reason: str, last_success: datetime | None = None):
    from marvin.services.event_bus_service.event_types import EventBackupData, EventOperation

    return EventBackupData(
        operation=EventOperation.info,
        target_name=run.target_name,
        target_type=run.target_type,
        status=run.status,
        reason=reason,
        run_id=run.id,
        location=run.location,
        started_at=_utc(run.started_at),
        finished_at=_utc(run.finished_at),
        duration_seconds=run.duration_seconds,
        duration=f"{run.duration_seconds:.1f}s" if run.duration_seconds is not None and run.status != STATUS_MISSED else None,
        db_bytes=run.db_bytes,
        backup_size=_size(run.db_bytes),
        error_message=run.error_summary,
        last_success_at=last_success,
        schedule=run.schedule,
        time_zone=run.time_zone,
    )


def _dispatch(event_bus, run: BackupRunModel, reason: str, last_success: datetime | None = None) -> None:
    from marvin.services.event_bus_service.event_types import EventTypes

    if reason in ("completed", "recovered"):
        # "recovered" is what the activity bell keys on to show the end of an incident (lib/activity/toast.ts).
        event_type, message = EventTypes.backup_completed, f"Backup {run.target_name}: {'recovered' if reason == 'recovered' else 'ok'}"
    else:  # the error itself travels as error_message (the bell shows it under the message)
        event_type, message = EventTypes.backup_failed, f"Backup {run.target_name}: {'overdue' if reason == 'overdue' else run.status}"
    # A platform event: no workspace. Only the super-admin Events page and bell show it.
    event_bus.dispatch(
        integration_id=INTEGRATION_ID,
        group_id=None,
        event_type=event_type,
        document_data=_event_data(run, reason, last_success),
        message=message[:1000],
        entity_id=run.id,
        entity_type="backup_run",
    )


@dataclass
class CheckOutcome:
    announced: int = 0
    overdue: list[str] = field(default_factory=list)
    pruned: int = 0


def _last_success_before(session: Session, run: BackupRunModel) -> datetime | None:
    started = (
        session.query(sa.func.max(BackupRunModel.started_at))
        .filter(BackupRunModel.target_name == run.target_name, BackupRunModel.status == STATUS_OK, BackupRunModel.started_at < run.started_at)
        .scalar()
    )
    return _utc(started)


def _incident_before(session: Session, run: BackupRunModel) -> set[str]:
    """The statuses of the target's rows between its last ok run and ``run``: the incident ``run``
    continues or ends (empty when none is open)."""
    q = session.query(BackupRunModel.status).filter(
        BackupRunModel.target_name == run.target_name,
        BackupRunModel.status != STATUS_OK,
        BackupRunModel.started_at < run.started_at,
    )
    last_ok = _last_success_before(session, run)
    if last_ok is not None:
        q = q.filter(BackupRunModel.started_at > _naive(last_ok))
    return {status for (status,) in q.distinct()}


def _reason(session: Session, run: BackupRunModel) -> str | None:
    """Why ``run`` is announced, or None when it isn't: a failed or partial run after another one in the
    same incident (the CronJob's retries) says nothing new. An ok run ending an incident is ``recovered``;
    a ``missed`` marker is already one per incident (``detect_overdue``)."""
    if run.status == STATUS_MISSED:
        return "overdue"
    incident = _incident_before(session, run)
    if run.status == STATUS_OK:
        return "recovered" if incident else "completed"
    if incident & {STATUS_FAILED, STATUS_PARTIAL}:
        return None
    return run.status


def announce_runs(session: Session, event_bus, now: datetime) -> int:
    """Dispatch the event for each run not announced yet, oldest first: a job's run → backup_completed
    (completed, or recovered when it ends an incident) or backup_failed (the incident's first failed or
    partial run only); a ``missed`` marker → backup_failed (reason overdue). A row is marked only after its
    dispatch, and no write is pending while dispatching (the event log writes on its own connection,
    which SQLite would otherwise refuse as locked)."""
    pending = session.query(BackupRunModel).filter(BackupRunModel.notified_at.is_(None)).order_by(BackupRunModel.started_at).all()
    announced = 0
    for run in pending:
        reason = _reason(session, run) if _utc(run.started_at) >= now - ANNOUNCE_WITHIN else None
        if reason is not None:
            last_success = _last_success_before(session, run) if reason == "overdue" else None
            try:
                _dispatch(event_bus, run, reason, last_success)
                announced += 1
            except Exception:
                logger.exception(f"backup health: could not announce run {run.id} ({run.target_name})")
                continue  # stays pending: the next check tries again
        run.notified_at = _naive(now)
        session.commit()
    return announced


def detect_overdue(session: Session, now: datetime) -> list[str]:
    """For each overdue target without an open incident, record a ``missed`` row: the incident's marker
    (no second one until a successful run ends it), announced as backup_failed (reason overdue) by
    ``announce_runs``. Returns the targets newly found overdue."""
    reported: list[str] = []
    for name in target_names(session):
        health = target_health(session, name, now)
        if not health.overdue or health.overdue_since is not None:
            continue  # fine, or already reported for this incident (cleared by the next successful run)
        since = _utc(health.last_success.started_at) if health.last_success else None
        every = _duration(health.interval)
        if since:
            why = (
                f"no successful run since {since:%Y-%m-%d %H:%M} UTC (runs every {every}; overdue after {_duration(overdue_window(health.interval))})"
            )
        else:
            why = f"no successful run since the target was first seen, {health.first_seen:%Y-%m-%d %H:%M} UTC (runs every {every})"
        if health.last_run is not None and health.last_run.status != STATUS_OK and health.last_run.error_summary:
            why += f"; last run {health.last_run.status}: {health.last_run.error_summary}"
        source = health.last_run
        session.add(
            BackupRunModel(
                session=session,
                target_name=name,
                target_type=health.type or "unknown",
                status=STATUS_MISSED,
                started_at=_naive(now),
                finished_at=_naive(now),
                schedule=health.schedule,
                time_zone=health.time_zone,
                keep_hourly=health.retention[0],
                keep_daily=health.retention[1],
                keep_weekly=health.retention[2],
                location=health.location,
                settings_json=health.settings or None,
                db_engine=source.db_engine if source else None,
                failures=0,
                error_summary=why[:2000],
            )
        )
        session.commit()
        reported.append(name)
        logger.warning(f"backup health: target {name!r} is overdue: {why}")
    return reported


def prune_runs(session: Session, now: datetime) -> int:
    cutoff = _naive(now - RUN_RETENTION)
    deleted = session.query(BackupRunModel).filter(BackupRunModel.started_at < cutoff).delete(synchronize_session=False)
    session.commit()
    return deleted


def check(session: Session, event_bus, now: datetime | None = None) -> CheckOutcome:
    now = _utc(now) or datetime.now(UTC)
    outcome = CheckOutcome()
    outcome.overdue = detect_overdue(session, now)
    outcome.announced = announce_runs(session, event_bus, now)
    outcome.pruned = prune_runs(session, now)
    return outcome


def _duration(delta: timedelta | None) -> str:
    if delta is None:
        return "?"
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h{minutes:02d}m"
    return f"{hours}h" if hours else f"{minutes}m"
