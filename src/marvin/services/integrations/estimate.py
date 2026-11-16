"""What a paid step is likely to cost, said on the approval that guards it — from what this workspace's own earlier calls of
the same kind cost, never from a guess.

A pending approval guards the integration steps after it (up to the next approval). For each one whose provider action is paid
(``cost_hint: paid`` or one that needs an approval), its arguments are resolved as the approved run would resolve them (the
approval's boxes as asked, its first choice) and its earlier calls are read from the AI-executions rows the integration step
writes (services/integrations/usage_log.py): the same integration and operation, newest first. Credits follow the tally's rule
(``budget.integration_tally``): what the provider measured for a call, else its units times the model's multiplier. Then:

* billed by the character (speech): the typical credits per character, times this text's length;
* billed by the length of the audio (a sound, music): the typical credits per second, times the `duration_seconds` asked, when
  both are known; else the typical credits per call;
* a price per call in dollars (an image model's tokens at its known price, ``estimated_cost_usd``): the typical one, among calls
  of the same `size` and `quality` when those are given.

"Typical" is the median of the last ``LOOKBACK`` calls. Nothing to go by (no earlier call, none measured) says so: ``unknown``.
Never raises: an estimate is a courtesy on a card.
"""

from __future__ import annotations

from statistics import median

LOOKBACK = 20  # the earlier calls an estimate reads
SCAN = 200  # the newest rows of that operation looked through for this integration's own
SAME_KIND_ARGS = ("size", "quality", "model_id", "model")  # an image's size and quality, a voice's model: calls only like these count


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number >= 0 else None  # not NaN, not negative


def _billed(meta: dict) -> float | None:
    """The credits a call cost: measured by the provider, else its units times the model's multiplier (budget.integration_tally)."""
    measured = _number(meta.get("credits"))
    if measured is not None:
        return measured
    units = _number(meta.get("units"))
    if units is None or str(meta.get("unit") or "calls") == "calls":
        return None  # a plain call that the provider did not measure: its credits are not known
    return units * (_number(meta.get("multiplier")) or 1.0)


def earlier_calls(session, group_id, integration_id, operation: str, args: dict) -> list:
    """This integration's latest completed calls of `operation`, the same kind as `args` (size, quality, model) where both say."""
    from marvin.db.models.groups.ai_executions import AIExecutionModel as Run

    from .usage_log import INTEGRATION_TRIGGER

    rows = (
        session.query(Run)
        .filter(Run.group_id == group_id, Run.trigger_type == INTEGRATION_TRIGGER, Run.status == "completed", Run.operation_slug == operation)
        .order_by(Run.created_at.desc())
        .limit(SCAN)
        .all()
    )
    found = []
    for run in rows:
        meta = run.metadata_json or {}
        if str(meta.get("integration_id") or "") != str(integration_id):
            continue
        was = ((run.input_json or {}).get("args") or {}) if isinstance(run.input_json, dict) else {}
        if any(args.get(k) not in (None, "") and was.get(k) not in (None, "") and str(args[k]) != str(was[k]) for k in SAME_KIND_ARGS):
            continue
        found.append(run)
        if len(found) >= LOOKBACK:
            break
    return found


def estimate_call(session, group_id, integration, operation: str, args: dict, *, provider_name: str) -> dict:
    """One paid call's estimate: ``{amount, unit, calls, text}`` or ``{unknown: True, text}``."""
    runs = earlier_calls(session, group_id, integration.id, operation, args)
    what = f"{provider_name} credits"
    if not runs:
        return {"unknown": True, "text": f"{provider_name}: cost unknown (nothing like it has been made here yet to go by)"}
    metas = [run.metadata_json or {} for run in runs]
    text = args.get("text") if isinstance(args.get("text"), str) else None
    per_char = [b / u for m in metas if str(m.get("unit")) == "characters" and (u := _number(m.get("units"))) and (b := _billed(m)) is not None]
    if per_char and text is not None:
        return _said(round(median(per_char) * len(text)), what, len(per_char), f"for these {len(text):,} characters")
    seconds = _number(args.get("duration_seconds"))
    lengths = [_number(run.output_json.get("duration_seconds")) if isinstance(run.output_json, dict) else None for run in runs]
    per_second = [b / s for m, s in zip(metas, lengths, strict=True) if s and (b := _number(m.get("credits"))) is not None]
    if per_second and seconds:
        return _said(round(median(per_second) * seconds), what, len(per_second), f"for {seconds:g} seconds")
    per_call = [b for m in metas if (b := _billed(m)) is not None]
    if per_call:
        return _said(round(median(per_call)), what, len(per_call), "a call")
    usd = [c for run in runs if (c := _number(run.estimated_cost_usd)) is not None]
    if usd:
        return _said(round(median(usd), 2), "USD", len(usd), "a call")
    return {"unknown": True, "text": f"{provider_name}: cost unknown (its earlier calls here did not say what they cost)"}


def _shown(amount, unit: str) -> str:
    return f"${amount:,.2f}" if unit == "USD" else f"{amount:,} {unit}"


def _said(amount, unit: str, calls: int, basis: str) -> dict:
    like = "the last call like it" if calls == 1 else f"the last {calls} like it"
    return {"amount": amount, "unit": unit, "calls": calls, "text": f"About {_shown(amount, unit)} ({basis}, going by {like})"}


def approval_estimate(session, row) -> dict | None:
    """The estimate a pending approval shows: ``{text, items: [...], total?}`` for the paid steps it guards; None when it guards
    none (or anything went wrong: never raises)."""
    try:
        return _approval_estimate(session, row)
    except Exception:  # noqa: BLE001 — an estimate is a courtesy
        return None


def _approval_estimate(session, row) -> dict | None:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.workflow_approvals import APPROVAL_PENDING

    from . import INTEGRATIONS_AVAILABLE

    if row.status != APPROVAL_PENDING or not INTEGRATIONS_AVAILABLE:
        return None
    automation = session.get(WorkspaceAutomationModel, row.automation_id)
    from marvin.services.automation.engine import _parked_step

    parked = _parked_step(automation, row, "approval") if automation is not None else None
    if parked is None:
        return None
    index, _ = parked
    actions = (automation.definition or {}).get("actions") or []
    guarded = []
    for step in actions[index + 1 :]:
        if not isinstance(step, dict) or step.get("kind") == "approval":
            break
        if step.get("kind") == "integration" and step.get("integration"):
            guarded.append(step)
    if not guarded:
        return None
    context = _as_approved(session, row, index)
    items = [item for step in guarded if (item := _step_estimate(session, row.group_id, step, context))]
    return combine(items) if items else None


def _as_approved(session, row, index: int) -> dict:
    """The context the steps after the approval would run with if it were approved now, unchanged, with its first choice."""
    from marvin.services.automation.engine import resumed_context

    output: dict = {"decision": "approved", "approved": True}
    if row.choices:
        output.update({"choice": row.choices[0], "choice_index": 0})
    if row.fields:
        output.update({"fields": {f["name"]: f.get("value", "") for f in row.fields}, "edited": []})
    context = resumed_context(session, row, index, output)
    context["steps"], context["previous"] = context.pop("_steps"), output
    context["_approved"] = True
    return context


def _step_estimate(session, group_id, step: dict, context: dict) -> dict | None:
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.services.automation.actions.integration import _declared_action
    from marvin.services.automation.matcher import interpolate, matches
    from marvin.services.integrations.alert_routing import capability_action, needs_approval

    from . import get_provider

    if step.get("when") and not matches(step["when"], context):
        return None  # a branch this run would not take (an animal's sheet for a person)
    slug = str(interpolate(step.get("integration") or "", context) or "").strip()
    integration = session.query(IntegrationModel).filter_by(group_id=group_id, slug=slug).first() if slug else None
    if integration is None or not integration.enabled:
        return None
    provider = get_provider(integration.provider)
    args = interpolate(step.get("args") or {}, context)
    args = args if isinstance(args, dict) else {}
    key, capability = step.get("action"), step.get("capability")
    if not key and capability:
        found = capability_action(provider, capability, args, approved=True)
        if found is None:
            return None
        key, args = found
    declared = _declared_action(provider, key) if key else None
    if declared is None or not (getattr(declared, "cost_hint", None) == "paid" or needs_approval(declared)):
        return None  # not a paid call: nothing to say
    name = getattr(provider, "name", None) or integration.provider
    operation = capability or f"{integration.provider}.{key}"
    return {"step": step.get("id"), **estimate_call(session, group_id, integration, operation, args, provider_name=name)}


def combine(items: list[dict]) -> dict:
    """One line for several estimates: a total when they share a unit and every one is known; each line kept for the card."""
    known = [i for i in items if not i.get("unknown")]
    units = {i["unit"] for i in known}
    out: dict = {"items": items}
    if known and len(known) == len(items) and len(units) == 1:
        unit = units.pop()
        total = round(sum(i["amount"] for i in known), 2) if unit == "USD" else sum(i["amount"] for i in known)
        out["total"] = {"amount": total, "unit": unit}
        out["text"] = items[0]["text"] if len(items) == 1 else f"About {_shown(total, unit)} in all"
    else:
        out["text"] = " · ".join(i["text"] for i in items)
    return out
