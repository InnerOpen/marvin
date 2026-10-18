"""`metric` step — record a metric observation, add to a count, or read observations back (services/metrics.py).

**record** (the default `op`): `metric` (a slug), `value` (a number; usually a template — `${input.clicks}`, an earlier step's
output), optional `variant` and `subject` (labels: "a" / "b", an entry's slug, a campaign), and the `window` the number
belongs to — `day`, `week` or `month` (the one the run falls in, read in the workspace's time zone; `at` points at another
date, e.g. `${entry.published_at}`) or an explicit `2026-10-18` / `2026-W42` / `2026-10`. One observation per metric,
variant, subject and window: recording again **replaces** the value, so a run repeated for the same window doesn't
double-count, and an unchanged value saves nothing. Output: `recorded`, `created`, `changed`, `metric`, `variant`, `subject`,
`window`, `value`, `previous_value`. A dry run resolves and previews it (`would`: create | change | leave) and writes nothing.

**add**: counting things as they happen — one per signup, a negative `value` for a decrement. Same `metric` / `variant` /
`subject` / `window` / `at`; `value` is optional and defaults to 1 (a number otherwise; an empty template is refused, never
counted as 1). It raises the window's number by `value`, **once per event delivery**: the step claims a key made of the
run's event (its correlation id), the workflow and the step in `metric_contributions`, in the same transaction as the new
number, so the same event handled twice (a re-delivery, a retry, a run of the same trigger again) adds once, a different
event adds again, and a failed write leaves no claim behind. A run with no event identity adds every time. Output: `value`
(the window's new total), `previous_value` (0 for a new window), `added`, `counted` (false, with `skipped`, when this
event was already added), `changed`, `created`, `metric`, `variant`, `subject`, `window`. A dry run says `would: add`
with the previous and new value and writes and claims nothing (`would: leave` when this event is already counted).

**read**: `metric` with optional `variant` / `subject` filters and `window_from` / `window_to` (any window form) →
`rows` ([{metric, variant, subject, window, value}], newest window first), `count`, `total` and `text`, a plain list headed
"Observations, not conclusions:". Reading only, so a dry run runs it too.

These are observations, not findings: nothing here compares variants or says what caused a number.
"""

from __future__ import annotations

from marvin.services import metrics

from ..matcher import interpolate
from .base import AutomationActionError, register_action


@register_action("metric")
def run_metric_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    try:
        metric = metrics.clean_metric(interpolate(action.get("metric"), context))
        if action.get("op") == "read":
            return _read(session, group_id, metric, action, context)
        if action.get("op") == "add":
            return _add(session, group_id, metric, action, context, context.get("_step") or {}, dry_run)
        return _record(session, group_id, metric, action, context, context.get("_step") or {}, dry_run)
    except metrics.MetricError as e:
        raise AutomationActionError(f"metric: {e}") from e


def _label(action: dict, context: dict, key: str) -> str:
    return metrics.clean_label(interpolate(action.get(key), context) if action.get(key) is not None else "", key)


def _where(session, group_id, action: dict, context: dict):
    """The variant, subject and window a record or an add means."""
    from ..waits import workspace_zone

    variant, subject = _label(action, context, "variant"), _label(action, context, "subject")
    at = interpolate(action["at"], context) if action.get("at") is not None else None
    if action.get("at") is not None and at in (None, ""):
        raise metrics.MetricError("at resolved to empty: it points at the date the observation belongs to")
    window = metrics.window_for(interpolate(action.get("window"), context) or "day", workspace_zone(session, group_id), at=at)
    return variant, subject, window


def _no_number_yet(raw) -> bool:
    from ..runner import is_stand_in

    # An earlier step didn't really run (an AI answer, a fetch) or a run input wasn't given: no number to preview yet.
    return raw in (None, "") or is_stand_in(raw) or _placeholder(raw)


def _record(session, group_id, metric: str, action: dict, context: dict, step: dict, dry_run: bool) -> dict:
    raw = interpolate(action.get("value"), context)
    variant, subject, window = _where(session, group_id, action, context)
    if dry_run and _no_number_yet(raw):
        return {"dry_run": True, "would": "record", "metric": metric, "variant": variant, "subject": subject, "window": window.label, "value": None}
    value = metrics.clean_value(raw)
    row = metrics.existing(session, group_id, metric=metric, variant=variant, subject=subject, window=window)
    previous = row.value if row is not None else None
    out = {"metric": metric, "variant": variant, "subject": subject, "window": window.label, "granularity": window.granularity, "value": value}
    if dry_run:
        would = "create" if row is None else ("leave" if previous == value else "change")
        return {"dry_run": True, "would": would, **out, "previous_value": previous}
    _, previous, changed = metrics.record(
        session, group_id, metric=metric, value=value, variant=variant, subject=subject, window=window, automation_id=_workflow_id(session, step)
    )
    return {"recorded": True, "created": previous is None, "changed": changed, **out, "previous_value": previous}


def _add(session, group_id, metric: str, action: dict, context: dict, step: dict, dry_run: bool) -> dict:
    # Left out, a count goes up by 1; one given that resolves to nothing is a mistake, not a 1.
    given = action.get("value") not in (None, "")
    raw = interpolate(action.get("value"), context) if given else None
    variant, subject, window = _where(session, group_id, action, context)
    out = {"metric": metric, "variant": variant, "subject": subject, "window": window.label, "granularity": window.granularity}
    if dry_run and given and _no_number_yet(raw):
        return {"dry_run": True, "would": "add", **out, "added": None, "previous_value": None, "value": None}
    amount = metrics.clean_value(raw) if given else 1.0
    key = _event_key(context, step)
    row = metrics.existing(session, group_id, metric=metric, variant=variant, subject=subject, window=window)
    previous = row.value if row is not None else 0.0
    if dry_run:
        counted = metrics.contribution(session, group_id, key) is not None
        return {
            "dry_run": True,
            "would": "leave" if counted else "add",
            **out,
            "added": 0.0 if counted else amount,
            "previous_value": previous,
            "value": previous if counted else previous + amount,
            "already_counted": counted,
        }
    result = metrics.add(
        session,
        group_id,
        metric=metric,
        amount=amount,
        variant=variant,
        subject=subject,
        window=window,
        key=key,
        automation_id=_workflow_id(session, step),
    )
    if not result.counted:
        return {
            "recorded": False,
            "counted": False,
            "skipped": True,
            "reason": "already counted for this event",
            **out,
            "added": 0.0,
            "changed": False,
            "created": False,
            "previous_value": result.previous,
            "value": result.value,
        }
    return {
        "recorded": True,
        "counted": True,
        **out,
        "added": amount,
        "changed": amount != 0,
        "created": result.created,
        "previous_value": result.previous,
        "value": result.value,
    }


def _event_key(context: dict, step: dict) -> str:
    """Which event this step is counting: the run's correlation id, the workflow, the step and its place (a repeat's item).
    "" without a correlation id or a step: nothing to tell two deliveries of one event apart by, so every run adds."""
    from marvin.services.event_bus_service.correlation import current_correlation_id

    correlation = (context.get("event") or {}).get("correlation_id") or current_correlation_id.get()
    if not correlation or not step:
        return ""
    on_failure = ":on_failure" if step.get("on_failure") else ""
    place = f"{step.get('target')}:{step.get('index')}{on_failure}"
    return f"{step.get('workflow') or 'workflow'}:{step.get('step_id') or step.get('index')}:{correlation}:{place}"[:400]


def _read(session, group_id, metric: str, action: dict, context: dict) -> dict:
    filters: dict = {}
    for key in ("variant", "subject", "window_from", "window_to"):
        if action.get(key) is None:
            continue
        resolved = interpolate(action[key], context)
        if resolved in (None, ""):  # an unresolved template must not widen a report to everything
            raise metrics.MetricError(f"{key} resolved to empty: a read filters on what it names, so it needs a value")
        filters[key] = str(resolved).strip()
    rows, total = metrics.query(session, group_id, metric=metric, limit=int(action.get("limit") or 50), **filters)
    facts = [{"metric": r.metric, "variant": r.variant, "subject": r.subject, "window": r.window_label, "value": r.value} for r in rows]
    return {"metric": metric, "count": len(facts), "total": total, "rows": facts, "text": metrics.report_text(rows)}


def _workflow_id(session, step: dict):
    """The saved workflow whose step this is (None for one that isn't saved: the observation just has no source)."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    automation_id = step.get("automation_id")
    return automation_id if automation_id is not None and session.get(WorkspaceAutomationModel, automation_id) is not None else None


def _placeholder(value) -> bool:
    """A dry run's stand-in for a run input nobody gave (‹name›): not a number, and not worth failing the preview on."""
    return isinstance(value, str) and value.startswith("‹") and value.endswith("›")
