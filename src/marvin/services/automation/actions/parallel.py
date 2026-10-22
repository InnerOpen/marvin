"""Executor for the ``parallel`` step: named branches of steps that run independently, then join.

``{"kind": "parallel", "id": "checks", "join": "all", "branches": [{"name": "text", "steps": [...]}, {"name": "images",
"steps": [...]}]}`` — the engine is synchronous and a run is one transaction-sized unit, so the branches run **one after
another, in the order written, inside this run**. What parallel means here is independence and a deterministic merge:

* a branch reads what ran before the parallel step (``steps.*``, ``previous``, the entry) but never a sibling's output;
  its own steps read each other as ``${steps.<id>.output}``; nothing a branch ran leaks into the next branch or past the
  step except through this step's output;
* the merge is by name in written order — ``branches.<name>`` plus ``order`` — so it can't depend on which branch
  finished first;
* ``join``: ``all`` (every branch must succeed) or ``any`` (the first branch that succeeds satisfies it and the later ones
  are skipped — a fallback chain: try the cheap check, else the next);
* ``on_branch_failure``: ``fail`` (default) fails the step when the join isn't met — under ``all`` the first failing
  branch stops the rest, which are skipped; under ``any`` it fails only when every branch did. ``continue`` never fails
  the step for a branch: every branch under ``all`` still runs, and the output reports ``satisfied``, ``failed`` and each
  branch's ``status`` (ok / failed / skipped) for a ``when`` to act on. A branch that already ran keeps what it did.

A branch's steps are plain steps keyed per branch (``_step.index`` = ``<step>.<branch>.<n>``) so a create inside makes its
entry once per event. No wait, approval, repeat or another parallel inside (a run can't park mid-branch; nesting stops at
one level), and all the branches' steps together count against the workspace's steps-per-workflow limit. A dry run
previews every branch — under ``any`` too, where the branches after the winner show ``skipped`` with what they would do.
"""

from __future__ import annotations

from typing import Any

from marvin.schemas.group.automation_definition import NOT_IN_A_BRANCH

from ..matcher import matches
from .approval import PARK
from .base import AutomationActionError, register_action, run_action

_SCOPE = ("steps", "previous", "_step")
_MISSING = object()


def _branches(action: dict, limit: int) -> list[tuple[str, list[dict]]]:
    """The branches as (name, steps), checked the way the definition model does for a workflow that skipped it."""
    raw = [b for b in action.get("branches") or [] if isinstance(b, dict)]
    if len(raw) < 2:
        raise AutomationActionError("a parallel step needs at least two branches")
    out: list[tuple[str, list[dict]]] = []
    for i, branch in enumerate(raw):
        name = str(branch.get("name") or "").strip()
        steps = [s for s in branch.get("steps") or [] if isinstance(s, dict)]
        if not name:
            raise AutomationActionError(f"branch {i + 1} of a parallel step needs a name")
        if name in {n for n, _ in out}:
            raise AutomationActionError(f"two branches are called “{name}”: each needs its own name")
        if not steps:
            raise AutomationActionError(f"branch “{name}” needs steps")
        if any(s.get("kind") == "agent" for s in steps):
            raise AutomationActionError(f"branch “{name}” can't hold an agent step: put it before or after the parallel step")
        if held := sorted({str(s.get("kind")) for s in steps} & set(NOT_IN_A_BRANCH)):
            raise AutomationActionError(f"branch “{name}” can't hold a {', '.join(held)} step: a run can't wait, or nest, in the middle of branches")
        out.append((name, steps))
    if (total := sum(len(steps) for _, steps in out)) > limit:
        raise AutomationActionError(
            f"the branches hold {total} steps, over this workspace's limit of {limit} steps per workflow "
            "(Settings → General → Workflows): trim a branch or raise the limit"
        )
    return out


@register_action("parallel")
def run_parallel_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from ..engine import workflow_max_steps

    branches = _branches(action, workflow_max_steps(session, group_id))
    join = "any" if action.get("join") == "any" else "all"
    keep_going = action.get("on_branch_failure") == "continue"
    saved = {key: context.get(key, _MISSING) for key in _SCOPE}
    outer = dict(saved["_step"]) if isinstance(saved["_step"], dict) else {}
    results: dict[str, dict] = {}
    errors: list[dict] = []
    winner: str | None = None
    stopped: str | None = None  # why the branches left are skipped
    try:
        for name, steps in branches:
            preview_only = False
            if winner is not None:  # join any, already satisfied
                if not dry_run:
                    results[name] = {"status": "skipped", "reason": f"“{winner}” already satisfied the join"}
                    continue
                preview_only = True
            elif stopped:
                results[name] = {"status": "skipped", "reason": stopped}
                continue
            context["steps"] = dict(saved["steps"]) if isinstance(saved["steps"], dict) else {}
            context["previous"] = dict(saved["previous"]) if isinstance(saved["previous"], dict) else {}
            outputs, last, failure = _run_branch(
                session, group_id, name, steps, context, outer, user_id=user_id, authorizer_role=authorizer_role, dry_run=dry_run
            )
            result: dict[str, Any] = {"status": "ok" if failure is None else "failed", "steps": outputs, "output": last}
            if failure is not None:
                step, error = failure
                result["step"], result["error"] = step, str(error)
                errors.append({"branch": name, "step": step, "error": str(error), "code": getattr(error, "code", None)})
                if join == "all" and not keep_going:
                    stopped = f"branch “{name}” failed, so the join can't be met"
            elif join == "any" and winner is None:
                winner = name
            if preview_only:  # a dry run shows what the branch would do; a real run would have skipped it
                result = {"status": "skipped", "reason": f"“{winner}” already satisfied the join", "would_run": result}
            results[name] = result
    finally:
        for key, value in saved.items():
            if value is _MISSING:
                context.pop(key, None)
            else:
                context[key] = value
    ok = sum(1 for r in results.values() if r["status"] == "ok")
    failed = len(errors)
    satisfied = ok >= 1 if join == "any" else failed == 0 and ok == len(branches)
    if not satisfied and not keep_going:
        first = errors[0]
        if join == "any":
            raise AutomationActionError(
                f"every branch failed — the first, “{first['branch']}”, step {first['step']}: {first['error']}", code=first["code"]
            )
        after = sum(1 for r in results.values() if r["status"] == "skipped")
        left = f"; {after} branch{'es' if after != 1 else ''} not run" if after else ""
        raise AutomationActionError(f"branch “{first['branch']}” failed, step {first['step']}: {first['error']}{left}", code=first["code"])
    out: dict[str, Any] = {
        "join": join,
        "on_branch_failure": "continue" if keep_going else "fail",
        "count": len(branches),
        "ok": ok,
        "failed": failed,
        "skipped": sum(1 for r in results.values() if r["status"] == "skipped"),
        "satisfied": satisfied,
        "winner": winner,
        "order": [name for name, _ in branches],
        "branches": results,
        "errors": errors,
        "text": "\n".join(f"- {e['branch']}: {e['error']}" for e in errors),
    }
    return out


def _run_branch(session, group_id, name: str, steps: list[dict], context: dict, outer: dict, **run) -> tuple[dict, dict, tuple | None]:
    """One branch's steps in order: their outputs by id (or position), the last one's output, and the first failure."""
    outputs: dict[str, Any] = {}
    last: dict = {}
    for j, step in enumerate(steps):
        key = str(step.get("id") or j)
        when = step.get("when")
        if when and not matches(when, context):
            outputs[key] = {"skipped": True}
            continue
        context["_step"] = {**outer, "index": f"{outer.get('index')}.{name}.{j}", "step_id": step.get("id")}
        try:
            out = run_action(session, group_id, step, context, **run)
        except AutomationActionError as e:
            return outputs, last, (key, e)
        if PARK in out:  # an executor that parks (none allowed here; a guard, not a path)
            return outputs, last, (key, AutomationActionError("a step inside a branch can't wait"))
        outputs[key] = out
        last = out
        context["previous"] = out
        if step.get("id"):
            context["steps"][str(step["id"])] = {"output": out}
    return outputs, last, None
