"""What a manual workflow would act on, before it runs: the entries its first step gathers.

A guided setup's run step lists them above its button ("the next 30 of 45"), so a person sees what will be made or kept
before saying go. The list is the workflow's own, declared once: its first step, a ``collect`` of entries, run with the
same inputs and the same ``${entry.*}`` a run would bind (engine.manual_context), only reading. A workflow that does
not start that way has no list (``found`` False): a first step that is something else, a collect with a ``when``
(it may not run at all), one that keeps only invalid entries or reads an earlier step's output, or a ``target``
(the run repeats per target entry, each gathering its own).

A workflow that starts by previewing a template (``create_entries_from_template`` or ``apply_template`` in ``mode:
preview``, the usual first step before the one that writes with ``confirm_total``) has a list too: that step's own
answer (``preview``: one row per picture or entry with its title, the values it would set and its picture), so a page
shows what would be made before the button is pressed. ``count`` is its ``todo``.

``left_out`` says what is not in the list, for a page to give the reasons in plain words: each reason is a ``where``
counted in place of the collect's own over the rest of its query (the same type, the same story), so "music" counts
the story's sounds that are music. Counts may overlap; a reason is the package's words, not a proof.
"""

from __future__ import annotations

import json
import re

_EARLIER = re.compile(r"\$\{\s*(steps|previous)\b")  # a value read from a step before it


def first_collect(definition: dict | None) -> dict | None:
    """The workflow's first step when it gathers entries with nothing but its query (see the module doc), else None."""
    definition = definition or {}
    actions = definition.get("actions") or []
    first = actions[0] if actions and isinstance(actions[0], dict) else None
    if first is None or definition.get("target") or first.get("kind") != "collect" or (first.get("entity") or "entry") != "entry":
        return None
    if first.get("when") or first.get("only_invalid") or not isinstance(first.get("query") or {}, dict):
        return None
    return None if _EARLIER.search(json.dumps(first.get("query") or {})) else first


TEMPLATE_STEPS = ("create_entries_from_template", "apply_template")


def first_template_preview(definition: dict | None) -> dict | None:
    """The workflow's first step when it previews a template (see the module doc) with nothing but the run's inputs, else
    None: a step that writes (``mode`` create or apply), one with a ``when``, or one that reads an earlier step's output."""
    definition = definition or {}
    actions = definition.get("actions") or []
    first = actions[0] if actions and isinstance(actions[0], dict) else None
    if first is None or definition.get("target") or first.get("kind") not in TEMPLATE_STEPS:
        return None
    if first.get("when") or (first.get("mode") or "preview") != "preview":
        return None
    return None if _EARLIER.search(json.dumps(first, default=str)) else first


def selection(session, group_id, automation, inputs: dict | None, *, left_out: list[list[dict]] = ()) -> dict:
    """{found, step, ids, count, total, limit, left_out} for `automation` run with `inputs` (the shape of schemas
    WorkflowSelection). Raises inputs.RunInputError for inputs it does not take, and AutomationActionError for a
    query the collect itself would refuse."""
    from .actions.collect import collect_limit, run_collect_action
    from .engine import manual_context
    from .matcher import interpolate

    step = first_collect(getattr(automation, "definition", None))
    context = manual_context(session, group_id, automation, inputs)  # checks the inputs even when there is no list
    if step is None:
        previewing = first_template_preview(getattr(automation, "definition", None))
        return {"found": False} if previewing is None else _template_preview(session, group_id, previewing, context)
    gathered = run_collect_action(session, group_id, step, context, dry_run=True)
    base = {k: v for k, v in interpolate(step.get("query") or {}, context).items() if k not in ("where", "sort")}
    return {
        "found": True,
        "step": step.get("id"),
        "ids": [str(row["id"]) for row in gathered["rows"]],
        "count": gathered["count"],
        "total": gathered["total"],
        "limit": collect_limit(step),
        "left_out": [_count(session, group_id, {**base, "where": where}) for where in left_out],
    }


def _template_preview(session, group_id, step: dict, context: dict) -> dict:
    """The selection a template's preview step gives: the step itself, run as the run would run it (a preview changes
    nothing), with the rows it answers in ``preview``. ``count`` is what the step that writes would confirm, its ``todo``."""
    from .actions.base import run_action

    found = run_action(session, group_id, {**step, "mode": "preview"}, context, dry_run=True)
    preview = {k: v for k, v in found.items() if k not in ("mode", "dry_run", "would")}
    return {
        "found": True,
        "step": step.get("id"),
        "ids": [],
        "count": preview["todo"],
        "total": preview["todo"],
        "limit": None,
        "left_out": [],
        "preview": preview,
    }


def _count(session, group_id, query: dict) -> int:
    from marvin.services.entries.query import run as run_entry_query

    result = run_entry_query(session, group_id, query, limit=1)
    return 0 if result.note else result.total
