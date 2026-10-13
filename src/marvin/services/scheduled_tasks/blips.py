"""When a scheduled task's network blip (services/integrations/http_client.is_transient_network_error: a timeout, a
dropped connection) is announced.

Quiet only while it's a blip: the task has been failing for less than ``QUIET_WINDOW`` *and* will run again within it,
so either the next run recovers or the alert comes soon. A frequent poll (every two minutes) rides out a slow API and
alerts once it has been failing for ten minutes; a slow task (a monthly token refresh) alerts on its first failure —
nothing retries it for a month. Any other failure always alerts on the first. Every failure is still in the event log
and the task's runs.
"""

from datetime import UTC, datetime, timedelta

QUIET_WINDOW = timedelta(minutes=10)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)  # SQLite hands datetimes back naive; all are UTC


def failing_since(session, task_id, prior_failures: int, now: datetime) -> datetime:
    """When the current failure streak began: this run if nothing failed before it, else the oldest of the last
    ``prior_failures`` failed runs (every failure is logged; a quiet success isn't, but it resets the count)."""
    if not prior_failures:
        return now
    from marvin.db.models.platform.scheduled_tasks import ScheduledTaskExecutionLogModel as Log

    rows = (
        session.query(Log.executed_at)
        .filter(Log.task_id == task_id, Log.status == "failed")
        .order_by(Log.executed_at.desc())
        .limit(prior_failures)
        .all()
    )
    return min((_aware(r[0]) for r in rows if r[0]), default=now)


def defer_alert(session, task, exc: BaseException | None, now: datetime | None = None) -> bool:
    """True when this failure is a network blip to keep quiet about for now (see the module docstring)."""
    from marvin.repos.platform.scheduled_tasks import ScheduledTasksRepository
    from marvin.services.integrations.http_client import is_transient_network_error

    if not is_transient_network_error(exc):
        return False
    now = now or datetime.now(UTC)
    next_run = ScheduledTasksRepository._compute_next_run(getattr(task, "schedule_type", None), getattr(task, "schedule_config", None))
    if next_run is None or _aware(next_run) - now > QUIET_WINDOW:
        return False  # nothing retries it soon: say so now
    since = failing_since(session, getattr(task, "id", None), getattr(task, "failure_count", 0) or 0, now)
    return now - since < QUIET_WINDOW
