"""Executor for the ``repeat`` step: its inner steps once for each item of a list.

``{"kind": "repeat", "for_each": "${steps.people.output.rows}", "as": "person", "steps": [...]}`` — each item is
``${person.*}`` (``as``, default ``item``) with ``${each.index}`` / ``${each.number}`` / ``${each.count}``; an inner
step reads the ones before it for the same item as ``${steps.<id>.output}``, and nothing of one item leaks into the
next. Inner steps run through the same executors as top-level ones, keyed per item (``_step.index`` =
``<step>.<item id, or its place>.<inner>``) so a create step makes one entry per item and the same event handled
twice makes none again, whatever order the list comes in. A run can't park mid-loop, so a wait, an approval or another repeat isn't allowed inside.
"""

from __future__ import annotations

from typing import Any

from marvin.schemas.group.automation_definition import MAX_REPEAT_ITEMS as MAX_ITEMS
from marvin.schemas.group.automation_definition import RESERVED_ITEM_NAMES as RESERVED

from ..matcher import interpolate, matches
from .approval import PARK
from .base import AutomationActionError, register_action, run_action

NOT_INSIDE = frozenset({"wait", "approval", "repeat"})
_MISSING = object()


def _items(value: Any) -> list:
    """The list to repeat over: a list as it is, one object as itself, comma-separated text split; nothing → none."""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def _check(action: dict) -> tuple[str, list[dict]]:
    name = str(action.get("as") or "item")
    if name in RESERVED:
        raise AutomationActionError(f"a repeat's item can't be called “{name}”: a run already reads that name")
    steps = [s for s in action.get("steps") or [] if isinstance(s, dict)]
    if not steps:
        raise AutomationActionError("a repeat needs steps to repeat")
    if any(s.get("kind") == "agent" for s in steps):
        raise AutomationActionError("a repeat can't hold an agent step: it would run the agent once per item, unbounded")
    if inside := sorted({str(s.get("kind")) for s in steps} & NOT_INSIDE):
        raise AutomationActionError(f"a repeat can't hold a {', '.join(inside)} step: a run can't wait in the middle of a loop")
    return name, steps


@register_action("repeat")
def run_repeat_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    name, steps = _check(action)
    every = _items(interpolate(action.get("for_each"), context))
    limit = max(1, min(int(action.get("limit") or MAX_ITEMS), MAX_ITEMS))
    items, stop = every[:limit], (action.get("on_item_error") or "stop") == "stop"
    saved = {key: context.get(key, _MISSING) for key in (name, "each", "steps", "previous", "_step")}
    outer = dict(saved["_step"]) if isinstance(saved["_step"], dict) else {}
    results: list[dict] = []
    errors: list[dict] = []
    try:
        for i, item in enumerate(items):
            context[name] = item
            context["each"] = {"index": i, "number": i + 1, "count": len(items)}
            context["steps"] = dict(saved["steps"]) if isinstance(saved["steps"], dict) else {}
            outputs, failure = _one_item(
                session, group_id, steps, context, outer, i, item, user_id=user_id, authorizer_role=authorizer_role, dry_run=dry_run
            )
            results.append(outputs)
            if failure is None:
                continue
            step, error = failure
            errors.append({"index": i, "step": step, "error": str(error)})
            if stop:
                done = f" ({i} done before it)" if i else ""
                raise AutomationActionError(f"item {i + 1} of {len(items)}, step {step}: {error}{done}", code=getattr(error, "code", None))
    finally:
        for key, value in saved.items():
            if value is _MISSING:
                context.pop(key, None)
            else:
                context[key] = value
    if items and len(errors) == len(items):
        raise AutomationActionError(f"every item failed — the first: step {errors[0]['step']}: {errors[0]['error']}")
    out = {"count": len(items), "done": len(items) - len(errors), "failed": len(errors), "results": results, "errors": errors}
    if len(every) > len(items):
        out["left_out"] = len(every) - len(items)  # past the limit
    return out


def _item_key(item, i: int) -> str:
    """What tells this item apart in a step's key: its id when it has one (a gathered row), so the same item is the same
    whatever order the list comes in; else its place."""
    ident = item.get("id") if isinstance(item, dict) else None
    return str(ident) if ident else str(i)


def _one_item(session, group_id, steps: list[dict], context: dict, outer: dict, i: int, item, **run) -> tuple[dict, tuple | None]:
    """Run the inner steps for one item: their outputs by id (or position), and the first failure, if any."""
    outputs: dict[str, Any] = {}
    for j, step in enumerate(steps):
        key = str(step.get("id") or j)
        when = step.get("when")
        if when and not matches(when, context):
            outputs[key] = {"skipped": True}
            continue
        context["_step"] = {**outer, "index": f"{outer.get('index')}.{_item_key(item, i)}.{j}", "step_id": step.get("id")}
        try:
            out = run_action(session, group_id, step, context, **run)
        except AutomationActionError as e:
            return outputs, (key, e)
        if PARK in out:  # an executor that parks (none allowed here; a guard, not a path)
            return outputs, (key, AutomationActionError("a step inside a repeat can't wait"))
        outputs[key] = out
        context["previous"] = out
        if step.get("id"):
            context["steps"][str(step["id"])] = {"output": out}
    return outputs, None
