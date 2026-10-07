"""Just enough of cron to know when a backup CronJob runs next: the five standard fields (minute, hour,
day of month, month, day of week) with ``*``, lists, ranges and steps, plus the ``@hourly``-style
shorthands Kubernetes accepts, read in an IANA time zone.

Marvin has no cron library (croniter isn't a dependency), and the backend only needs "when is the next
run" and "how far apart are runs" for the schedules the chart passes along (``0 * * * *``,
``30 2 * * *``), so this stays small. Like Kubernetes (and Vixie cron), when both day fields are
restricted a day matches either. Names (``MON``, ``JAN``) and ``?``/``L``/``W`` are not understood:
``parse`` raises ``ValueError`` and the caller shows the schedule without a next run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_SEARCH_DAYS = 366 * 5  # a schedule with no fire time in five years (Feb 30) has none


def _field(text: str, low: int, high: int) -> frozenset[int]:
    values: set[int] = set()
    for part in text.split(","):
        rng, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError(f"bad step in {part!r}")
        if rng == "*":
            start, end = low, high
        elif "-" in rng:
            a, b = rng.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(rng)
            end = high if step_text else start
        if not (low <= start <= high and low <= end <= high) or start > end:
            raise ValueError(f"{part!r} is outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return frozenset(values)


@dataclass(frozen=True)
class CronSchedule:
    expression: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]  # 0 = Sunday … 6 = Saturday (7 folds into 0)
    any_day: bool
    any_weekday: bool
    zone: ZoneInfo

    def _day_matches(self, day: datetime) -> bool:
        if day.month not in self.months:
            return False
        dom = day.day in self.days
        dow = (day.isoweekday() % 7) in self.weekdays
        if self.any_day and self.any_weekday:
            return True
        if self.any_day:
            return dow
        if self.any_weekday:
            return dom
        return dom or dow  # both restricted: either one (cron's rule)

    def next_after(self, when: datetime) -> datetime | None:
        """The first fire time strictly after ``when`` (aware, returned in UTC), or None if there is none."""
        local = when.astimezone(self.zone).replace(second=0, microsecond=0, tzinfo=None) + timedelta(minutes=1)
        day = local.replace(hour=0, minute=0)
        for _ in range(_SEARCH_DAYS):
            if self._day_matches(day):
                for hour in sorted(self.hours):
                    for minute in sorted(self.minutes):
                        candidate = day.replace(hour=hour, minute=minute)
                        if candidate >= local:
                            # A wall time skipped by a DST jump resolves forward, as the CronJob controller's does.
                            return candidate.replace(tzinfo=self.zone).astimezone(UTC)
            day += timedelta(days=1)
            local = day
        return None

    def interval(self, around: datetime) -> timedelta | None:
        """The longest gap between the next few fire times after ``around``: how often it runs (a daily
        schedule across a DST change counts its 25-hour day)."""
        times: list[datetime] = []
        t = around
        for _ in range(4):
            nxt = self.next_after(t)
            if nxt is None:
                break
            times.append(nxt)
            t = nxt
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        return max(gaps) if gaps else None


def zone(name: str | None) -> ZoneInfo:
    """The IANA zone, or UTC for empty (the CronJob controller's default). Raises ValueError if unknown."""
    if not name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ValueError(f"unknown time zone {name!r}") from e


def parse(expression: str, time_zone: str | None = None) -> CronSchedule:
    """A cron expression (5 fields or a shorthand) in ``time_zone``. Raises ValueError when not understood."""
    text = " ".join((expression or "").split())
    text = _MACROS.get(text.lower(), text)
    fields = text.split(" ")
    if len(fields) != 5:
        raise ValueError(f"expected 5 fields, got {len(fields)}: {expression!r}")
    try:
        parsed = [_field(f, lo, hi) for f, (lo, hi) in zip(fields, _BOUNDS, strict=True)]
    except ValueError as e:
        raise ValueError(f"can't read {expression!r}: {e}") from None
    minutes, hours, days, months, weekdays = parsed
    return CronSchedule(
        expression=expression,
        minutes=minutes,
        hours=hours,
        days=days,
        months=months,
        weekdays=frozenset(d % 7 for d in weekdays),
        any_day=fields[2] == "*",
        any_weekday=fields[4] == "*",
        zone=zone(time_zone),
    )
