"""Metric observations — a number noted down for a metric, a variant and a window (a workflow's `metric` step).

**Window.** A day (`2026-10-18`), an ISO week (`2026-W42`, Monday to Sunday) or a month (`2026-10`). A step can name one
outright, or ask for the day / week / month the run falls in (or a date it points at: `at`) — read in the workspace's time
zone (Settings → Site), so a run at 11:30 pm New York time on the 31st is still that month's, whatever UTC says.

**Idempotency.** One observation per (metric, variant, subject, window). Two ways to write it. **record** replaces the
value (a run repeated, a retry, a scheduled check that reads the same number twice never double-counts) and says whether
it changed: record what you read — "clicks so far", "followers today". **add** increments it — counting things as they
happen, one signup at a time — so it can't tell a retry from a second event by the number alone: it keys each add on the
run's event (the correlation id, the workflow and the step) and claims that key in `metric_contributions` in the same
transaction that raises the number. The same event handled twice adds once; a write that fails takes its claim with it.
A run with no event identity (nothing to tell two deliveries apart by) adds every time it runs.

**Not conclusions.** These are observations. Nothing here compares variants, tests significance or claims a cause; the
report lists the numbers and leaves the reading to a person.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marvin.db.models.groups.metric_contributions import MetricContributionModel
from marvin.db.models.groups.metric_observations import MetricObservationModel

GRANULARITIES = ("day", "week", "month")
METRIC = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_LABEL = 100  # a variant or a subject
MAX_PER_WORKSPACE = 50_000  # rows; a workspace past it records no new windows (an existing one can still change)
_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
_MONTH = re.compile(r"^(\d{4})-(\d{2})$")


class MetricError(ValueError):
    """What can't be recorded or read, in words a workflow author can act on."""


@dataclass(frozen=True)
class Window:
    granularity: str
    start: date
    label: str


def _window(granularity: str, start: date) -> Window:
    if granularity == "day":
        label = start.isoformat()
    elif granularity == "week":
        year, week, _ = start.isocalendar()
        label = f"{year}-W{week:02d}"
    else:
        label = f"{start.year}-{start.month:02d}"
    return Window(granularity, start, label)


def parse_window(text: str) -> Window:
    """`2026-10-18` | `2026-W42` | `2026-10` → its Window; MetricError for anything else (or a date that doesn't exist)."""
    text = str(text or "").strip()
    try:
        if m := _DAY.match(text):
            return _window("day", date(int(m[1]), int(m[2]), int(m[3])))
        if m := _WEEK.match(text):
            return _window("week", date.fromisocalendar(int(m[1]), int(m[2]), 1))
        if m := _MONTH.match(text):
            return _window("month", date(int(m[1]), int(m[2]), 1))
    except ValueError as e:
        raise MetricError(f"window {text!r} isn't a real date, week or month") from e
    raise MetricError(
        f"window {text!r}: give a day (2026-10-18), an ISO week (2026-W42) or a month (2026-10), or day / week / month for the run's own"
    )


def local_day(at, zone: ZoneInfo, *, now: datetime | None = None) -> date:
    """The calendar day `at` falls on in `zone`. `at`: None (now), a date (`2026-10-18`), or a date and time — one with a
    zone or `Z` is converted into `zone`, one without is already local."""
    if at in (None, ""):
        return (now or datetime.now(UTC)).astimezone(zone).date()
    if isinstance(at, datetime):
        parsed = at
    elif isinstance(at, date):
        return at
    else:
        text = str(at).strip()
        if _DAY.match(text):
            try:
                return date.fromisoformat(text)
            except ValueError as e:
                raise MetricError(f"at {text!r} isn't a real date") from e
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as e:
            raise MetricError(f"at {text!r} isn't a date (YYYY-MM-DD) or a date and time") from e
    return (parsed.astimezone(zone) if parsed.tzinfo else parsed).date()


def window_for(spec, zone: ZoneInfo, *, at=None, now: datetime | None = None) -> Window:
    """The Window a step means. `spec`: day | week | month (the one `at`, default the run's time, falls in — in `zone`),
    or an explicit label (then `at` isn't used)."""
    spec = str(spec or "day").strip()
    if spec.lower() in GRANULARITIES:
        granularity = spec.lower()
        day = local_day(at, zone, now=now)
        if granularity == "week":
            day -= timedelta(days=day.weekday())
        elif granularity == "month":
            day = day.replace(day=1)
        return _window(granularity, day)
    return parse_window(spec)


def clean_metric(value) -> str:
    text = str(value if value is not None else "").strip()
    if not METRIC.match(text):
        raise MetricError(f"metric {text!r}: a slug — lowercase letters, digits, - and _, starting with a letter or digit, up to 64 characters")
    return text


def clean_label(value, what: str) -> str:
    text = str(value if value is not None else "").strip()
    if len(text) > MAX_LABEL:
        raise MetricError(f"{what} is longer than {MAX_LABEL} characters")
    return text


def clean_value(value) -> float:
    if isinstance(value, bool):
        raise MetricError("value is a number, not true / false")
    try:
        number = float(str(value).strip().replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError) as e:
        raise MetricError(f"value {value!r} isn't a number") from e
    if not math.isfinite(number):
        raise MetricError("value must be a finite number")
    return number


def _key(session: Session, group_id, metric: str, variant: str, subject: str, window: Window):
    return session.query(MetricObservationModel).filter(
        MetricObservationModel.group_id == group_id,
        MetricObservationModel.metric == metric,
        MetricObservationModel.variant == variant,
        MetricObservationModel.subject == subject,
        MetricObservationModel.window_label == window.label,
    )


def existing(session: Session, group_id, *, metric: str, variant: str, subject: str, window: Window) -> MetricObservationModel | None:
    return _key(session, group_id, metric, variant, subject, window).first()


def record(
    session: Session, group_id, *, metric: str, value: float, variant: str, subject: str, window: Window, automation_id=None, _retry: bool = False
) -> tuple[MetricObservationModel, float | None, bool]:
    """Write the observation. Returns (row, the value it replaced — None when it is new, whether anything changed)."""
    row = existing(session, group_id, metric=metric, variant=variant, subject=subject, window=window)
    if row is not None:
        previous = row.value
        if previous == value:
            return row, previous, False
        row.value = value
        if automation_id is not None:
            row.automation_id = automation_id
        session.commit()
        return row, previous, True
    if session.query(func.count(MetricObservationModel.id)).filter(MetricObservationModel.group_id == group_id).scalar() >= MAX_PER_WORKSPACE:
        raise MetricError(f"this workspace holds {MAX_PER_WORKSPACE:,} observations, the most it keeps: remove some on the Metrics page")
    row = MetricObservationModel(
        session=session,
        group_id=group_id,
        metric=metric,
        variant=variant,
        subject=subject,
        window_label=window.label,
        granularity=window.granularity,
        window_start=window.start,
        value=value,
        automation_id=automation_id,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if _retry or existing(session, group_id, metric=metric, variant=variant, subject=subject, window=window) is None:
            raise
        # Two runs recording the same key at once: the other got there first, so this one is a change.
        return record(
            session, group_id, metric=metric, value=value, variant=variant, subject=subject, window=window, automation_id=automation_id, _retry=True
        )
    return row, None, True


@dataclass(frozen=True)
class Added:
    value: float  # the window's total now
    previous: float  # what it was before this add (0 for a window that is new)
    counted: bool  # False when this event had already been added: nothing changed
    created: bool


def contribution(session: Session, group_id, key: str) -> MetricContributionModel | None:
    return (
        session.query(MetricContributionModel)
        .filter(MetricContributionModel.group_id == group_id, MetricContributionModel.contribution_key == key)
        .first()
        if key
        else None
    )


def add(
    session: Session, group_id, *, metric: str, amount: float, variant: str, subject: str, window: Window, key: str = "", automation_id=None
) -> Added:
    """Raise the window's number by `amount`, once per `key` (the run's event, workflow and step; "" = every time).

    The claim on `key` and the new number are one transaction: two sessions delivering the same event serialize on the
    claim's unique index (the second finds it taken and adds nothing), and a failure anywhere rolls the claim back so a
    retry can still count."""
    claim = None
    try:
        if key:
            claim = MetricContributionModel(session=session, group_id=group_id, contribution_key=key, amount=amount)
            try:
                with session.begin_nested():
                    session.add(claim)
                    session.flush()
            except IntegrityError:
                row = existing(session, group_id, metric=metric, variant=variant, subject=subject, window=window)
                total = row.value if row is not None else 0.0
                return Added(total, total, False, False)
        locked = _key(session, group_id, metric, variant, subject, window).with_for_update()
        row = locked.first()
        created = row is None
        if row is None:
            if session.query(func.count(MetricObservationModel.id)).filter(MetricObservationModel.group_id == group_id).scalar() >= MAX_PER_WORKSPACE:
                raise MetricError(f"this workspace holds {MAX_PER_WORKSPACE:,} observations, the most it keeps: remove some on the Metrics page")
            row = MetricObservationModel(
                session=session,
                group_id=group_id,
                metric=metric,
                variant=variant,
                subject=subject,
                window_label=window.label,
                granularity=window.granularity,
                window_start=window.start,
                value=amount,
                automation_id=automation_id,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
                previous = 0.0
            except IntegrityError:  # another run made the window first: add onto what it wrote
                created = False
                row = locked.one()
                previous = row.value
                row.value = previous + amount
        else:
            previous = row.value
            row.value = previous + amount
        if automation_id is not None:
            row.automation_id = automation_id
        if claim is not None:
            claim.observation_id = row.id
        total = row.value
        session.commit()
        return Added(total, previous, True, created)
    except Exception:
        session.rollback()
        raise


def query(
    session: Session,
    group_id,
    *,
    metric: str | None = None,
    variant: str | None = None,
    subject: str | None = None,
    window_from: str | None = None,
    window_to: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """(rows, total): newest window first, then metric, variant, subject. `variant` / `subject` of "" means the ones with
    none; None means any. `window_from` / `window_to` are any window form (a day, week or month): a window counts when it
    starts on or after `window_from`'s start and on or before `window_to`'s start."""
    q = session.query(MetricObservationModel).filter(MetricObservationModel.group_id == group_id)
    if metric:
        q = q.filter(MetricObservationModel.metric == metric)
    if variant is not None:
        q = q.filter(MetricObservationModel.variant == variant)
    if subject is not None:
        q = q.filter(MetricObservationModel.subject == subject)
    if window_from:
        q = q.filter(MetricObservationModel.window_start >= parse_window(window_from).start)
    if window_to:
        q = q.filter(MetricObservationModel.window_start <= parse_window(window_to).start)
    total = q.count()
    rows = (
        q.order_by(
            MetricObservationModel.window_start.desc(),
            MetricObservationModel.metric,
            MetricObservationModel.variant,
            MetricObservationModel.subject,
            MetricObservationModel.granularity,
        )
        .offset(max(0, offset))
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    return rows, total


def metric_names(session: Session, group_id) -> list[dict]:
    """Each metric the workspace has recorded: its name, how many observations and the span of windows."""
    rows = (
        session.query(
            MetricObservationModel.metric,
            func.count(MetricObservationModel.id),
            func.min(MetricObservationModel.window_start),
            func.max(MetricObservationModel.window_start),
        )
        .filter(MetricObservationModel.group_id == group_id)
        .group_by(MetricObservationModel.metric)
        .order_by(MetricObservationModel.metric)
        .all()
    )
    return [{"metric": m, "count": n, "first_window": a, "last_window": b} for m, n, a, b in rows]


def remove(session: Session, group_id, observation_id) -> bool:
    row = (
        session.query(MetricObservationModel).filter(MetricObservationModel.group_id == group_id, MetricObservationModel.id == observation_id).first()
    )
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def number_text(value: float) -> str:
    """12.0 → "12", 0.25 → "0.25" — what a report shows."""
    return f"{value:.10g}"


def report_text(rows) -> str:
    """One line per observation, with the "observations, not conclusions" header a report always carries."""
    if not rows:
        return "No observations."
    lines = ["Observations, not conclusions:"]
    for r in rows:
        who = " · ".join(p for p in (r.variant and f"variant {r.variant}", r.subject and r.subject) if p)
        lines.append(f"- {r.window_label} {r.metric}{f' ({who})' if who else ''}: {number_text(r.value)}")
    return "\n".join(lines)
