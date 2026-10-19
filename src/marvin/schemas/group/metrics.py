"""Metric observations (services/metrics.py): what the Metrics API returns. Observations, not conclusions."""

from datetime import date, datetime

from pydantic import UUID4

from marvin.schemas._marvin import _MarvinModel


class MetricObservationRead(_MarvinModel):
    id: UUID4
    metric: str
    variant: str
    """"" when the step named none."""
    subject: str
    """"" when the step named none."""
    window: str
    """`2026-10-18` (a day), `2026-W42` (an ISO week) or `2026-10` (a month)."""
    granularity: str
    """day | week | month."""
    window_start: date
    """The window's first day (a week's Monday)."""
    value: float
    workflow_name: str | None = None
    """The workflow whose step recorded it; None once it is deleted."""
    workflow_slug: str | None = None
    updated_at: datetime | None = None


class MetricObservationList(_MarvinModel):
    items: list[MetricObservationRead]
    total: int
    limit: int
    offset: int
    note: str = "Observations, not conclusions: these are numbers a workflow recorded, with nothing said about what caused them."


class MetricSummary(_MarvinModel):
    metric: str
    count: int
    first_window: date
    last_window: date
