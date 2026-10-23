"""An agent checks its work before it finishes (``run_agent_loop(work_check=…)``).

When the model stops calling tools, the loop asks a ``WorkCheck`` what is left: gaps Marvin sees for itself in the run's
transcript (a tool that failed and was never retried, a draft that still can't be published), and — once — the "Done
when" checklist of the Playbooks steering the run, which the agent is asked to go through with evidence. Anything left
goes back to the model as a user message and the loop carries on, within the run's own step budget. Off unless an agent
(``check_work``) or a workflow step turns it on: without a ``WorkCheck`` the loop is exactly what it was.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

MAX_GATE_ROUNDS = 2  # times one run may be sent back before it answers
MAX_CRITERIA = 12  # checklist items shown to the model, across the Playbooks in effect
DRAFT_TOOLS = ("create_draft", "update_draft")

# "## Done when", "### Done-when", "## Definition of done" … up to the next heading.
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*(done[\s-]*when|definition of done)\b.*$", re.IGNORECASE | re.MULTILINE)
_NEXT_HEADING = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.+?)\s*$")


def done_when(body: str | None) -> list[str]:
    """The bullet items under a Playbook's "Done when" heading (empty when it has none)."""
    if not body:
        return []
    found = _HEADING.search(body)
    if not found:
        return []
    rest = body[found.end() :]
    stop = _NEXT_HEADING.search(rest)
    section = rest[: stop.start()] if stop else rest
    return [m.group(1) for line in section.splitlines() if (m := _BULLET.match(line))]


def criteria_of(playbooks: Iterable) -> list[str]:
    """The checklist of a run: every "Done when" item of the Playbooks in effect, in order, without repeats."""
    seen: dict[str, None] = {}
    for playbook in playbooks:
        for item in done_when(getattr(playbook, "body", None)):
            seen.setdefault(item, None)
    return list(seen)[:MAX_CRITERIA]


def _tool_results(convo) -> list[tuple[str, dict | None]]:
    """(tool name, its JSON answer or None) for every tool call in the transcript, in order."""
    names = {c.id: c.name for m in convo if getattr(m, "role", None) == "assistant" for c in (getattr(m, "tool_calls", None) or [])}
    out: list[tuple[str, dict | None]] = []
    for m in convo:
        if getattr(m, "role", None) != "tool" or m.tool_call_id not in names:
            continue
        try:
            parsed = json.loads(m.content)
        except (TypeError, ValueError):
            parsed = None
        out.append((names[m.tool_call_id], parsed if isinstance(parsed, dict) else None))
    return out


def gaps_in(convo) -> list[str]:
    """What Marvin can see is unfinished in a run's transcript, with no model call: a tool whose last answer was an
    error, and a draft written this run whose latest answer still lists what blocks publishing."""
    gaps: list[str] = []
    last_by_tool: dict[str, dict | None] = {}
    drafts: dict[str, dict] = {}
    for name, out in _tool_results(convo):
        last_by_tool[name] = out
        if name in DRAFT_TOOLS and out and out.get("entryId"):
            drafts[out["entryId"]] = out
    for name, out in last_by_tool.items():
        if out and out.get("error"):
            gaps.append(f"{name} failed: {out['error']}")
    for entry_id, out in drafts.items():
        if warnings := [str(w) for w in (out.get("warnings") or []) if str(w).strip()]:
            label = (out.get("saved") or {}).get("title") or out.get("title") or entry_id
            gaps.append(f"the draft '{label}' can't be published yet: {'; '.join(warnings)}")
    return gaps


@dataclass
class WorkCheck:
    """What a run checks before it answers. ``criteria`` reads the checklist from the transcript so far (the Playbooks in
    effect can change as the run loads them); ``rounds`` and ``asked`` are this run's own state."""

    criteria: Callable[[list], list[str]] = lambda convo: []
    rounds: int = 0
    asked: bool = False
    seen_criteria: list[str] = field(default_factory=list)

    def follow_up(self, convo) -> str | None:
        """The message that sends the run back to work, or None when there is nothing left to check."""
        if self.rounds >= MAX_GATE_ROUNDS:
            return None
        gaps = gaps_in(convo)
        items = self.criteria(convo)
        self.seen_criteria = items
        ask_checklist = bool(items) and not self.asked
        if not gaps and not ask_checklist:
            return None
        self.rounds += 1
        parts = ["Before you finish, check your work."]
        if gaps:
            parts.append("These are not done yet:\n" + "\n".join(f"- {g}" for g in gaps) + "\nFix them with your tools if you can.")
        if ask_checklist:
            self.asked = True
            parts.append(
                "Go through this checklist from the Playbook you are following. For each item, check it with your tools "
                "or point to a tool result that shows it; work on any you can't show yet:\n" + "\n".join(f"- {c}" for c in items)
            )
            parts.append("Then give your final answer, ending with a short 'Checked:' list (✓ or ✗ for each item).")
        else:
            parts.append("Then give your final answer.")
        return "\n\n".join(parts)

    def summary(self, convo) -> dict:
        """What was checked and what is still unmet when the run answers (stored on the run)."""
        return {"criteria": self.seen_criteria or self.criteria(convo), "unmet": gaps_in(convo), "rounds": self.rounds}


def with_unmet(answer: str, check: dict | None) -> str:
    """The answer, plus an honest "Still to do" list when Marvin's own checks found gaps the run didn't close."""
    unmet = (check or {}).get("unmet") or []
    if not unmet:
        return answer
    return (answer or "").rstrip() + "\n\nStill to do:\n" + "\n".join(f"- {g}" for g in unmet)


def for_run(session, group_id, thread=None, scope=None) -> WorkCheck:
    """The work check for an agent run: its checklist is the "Done when" of the Playbooks in effect (the agent's
    always-load ones, those the thread remembers, those loaded in this run — the same seam as the tool limit)."""
    from marvin.services.playbooks import playbooks_in_effect

    return WorkCheck(criteria=lambda convo: criteria_of(playbooks_in_effect(session, group_id, convo, thread, scope)))
