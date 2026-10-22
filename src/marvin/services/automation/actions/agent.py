"""Executor for the ``agent`` step: hand a job to a named agent and wait for its answer.

It runs the agent the way MCP's ``run_agent`` does (``builtins_agents.run_unattended``): alone, with the tools its own permission
matrix allows at the workflow author's role — Ask-first and off tools aren't offered, nobody could approve them — and its
Playbooks, plus any the step adds. What it writes lands as drafts. The step's output is the answer, the entries it made or changed,
the Playbooks it used and how it ended; the AI execution is recorded (trigger ``automation``) and linked from the run.

Guards: the workspace's AI budget is checked before the run; the entries it saves carry the run's reaction depth + 1 (the loop guard
every other step has); and the step doesn't run for an event this same workflow's run caused, so Writer → draft → entry_created →
Writer can't go round. A dry run shows what would happen and makes no AI call.
"""

from __future__ import annotations

from dataclasses import replace

from ..matcher import interpolate
from .base import AutomationActionError, register_action

AUTOMATION_SOURCE = "automation"
FRAMING = (
    "## This is an unattended workflow run\n"
    "Nobody can answer questions or approve anything: do the job with the tools you have, then finish with a short, plain answer "
    "saying what you did. Everything you write lands as a draft for a person to review; never claim anything is published. Write any "
    "text yourself and save it with create_draft or update_draft: compose_entry and revise_entry hand the writing to Marvin's own AI, "
    "which does not see your Playbooks."
)


@register_action("agent")
def run_agent_step(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services.ai.agents import may_talk, resolve_agent
    from marvin.services.ai.tools.base import ToolContext
    from marvin.services.ai.tools.builtins_agents import standalone_tools
    from marvin.services.playbooks import PlaybookScope, always_playbooks

    from ..authz import ROLE_OWNER

    slug = str(interpolate(action.get("agent") or "", context) or "").strip().lower()
    spec = resolve_agent(session, group_id, slug) if slug else None
    if spec is None:
        raise AutomationActionError(f"no agent '{slug}' in this workspace: name one by its slug (Settings → AI → Agents)")
    role = ROLE_OWNER if authorizer_role is None else authorizer_role
    ok, reason = may_talk(spec, role, AUTOMATION_SOURCE)
    if not ok:
        raise AutomationActionError(reason)
    if spec.kind != "persona":
        raise AutomationActionError(f"agent '{spec.slug}' is a plain model with no tools: pick an agent that can work (kind persona)")
    message = _message(action, context)
    names = _playbook_names(session, group_id, action)

    chain = {str(w) for w in (context.get("event") or {}).get("caused_by_workflows") or ()}
    if (workflow := str((context.get("_step") or {}).get("workflow") or "")) and workflow in chain:
        skipped = {
            **_output("", [], [], "refused"),
            "agent": spec.slug,
            "skipped": "this event came from this workflow's own run: its agent step never runs for it",
        }
        return {"dry_run": True, "kind": "agent", **skipped} if dry_run else skipped

    author = _author(session, context)
    tool_ctx = ToolContext(session=session, group_id=group_id, user=author, source=AUTOMATION_SOURCE)
    scope = replace(PlaybookScope.of(spec.playbooks).asking(message), also=tuple(names))
    loaded = [p.name for p in always_playbooks(session, group_id, scope)]
    if dry_run:
        tools = sorted(t.name for t in standalone_tools(spec, ToolContext(session=session, group_id=group_id, user=author, playbooks=scope), role))
        return {
            "dry_run": True,
            "kind": "agent",
            "agent": spec.slug,
            "message": message,
            "tools": tools,
            "playbooks": loaded,
            "max_steps": int(action.get("max_steps") or 8),
            **_output(f"‹AI answer: {spec.slug}›", [], loaded, "complete"),
        }

    from marvin.services.ai import budget
    from marvin.services.ai.factory import AIDisabledError, get_workspace_ai_provider
    from marvin.services.ai.tools.builtins_agents import UnattendedRunError, run_unattended
    from marvin.services.event_bus_service.correlation import reaction_depth_at_least

    from ..runner import _resolve_model

    if reason := budget.blocked_reason(session, group_id):
        raise AutomationActionError(f"AI budget: {reason}")
    settings = _ai_settings(session, group_id)
    if isinstance((policy := getattr(settings, "invocation_sources", None)), dict) and policy.get(AUTOMATION_SOURCE, True) is False:
        raise AutomationActionError("this workspace has disabled AI from the automation source")
    try:
        provider = get_workspace_ai_provider(session, group_id)
    except AIDisabledError as e:
        raise AutomationActionError(f"AI disabled: {e}") from e
    except Exception as e:
        raise AutomationActionError(f"provider error: {e}") from e
    model = spec.model_override or _resolve_model(session, group_id, settings)
    if not model:
        raise AutomationActionError("no default model configured for this workspace")

    tool_ctx.provider = provider
    try:
        with reaction_depth_at_least(int(context.get("depth", 0)) + 1):
            run = run_unattended(
                tool_ctx, spec, message, role=role, model=model, max_steps=int(action.get("max_steps") or 8),
                trigger_type=AUTOMATION_SOURCE, playbooks=tuple(names), note=FRAMING,
            )  # fmt: skip
    except UnattendedRunError as e:
        raise AutomationActionError(str(e)) from e
    if crossing := budget.crossing_after(session, group_id, run.cost_usd):
        budget.emit_crossing(group_id, crossing, user_id=getattr(author, "id", None), source=AUTOMATION_SOURCE)
    out = _output(run.answer, run.entries, [p["name"] for p in run.playbooks], "refused" if run.stopped == "awaiting_approval" else run.stopped)
    return {
        **out,
        "agent": spec.slug,
        "execution_id": run.execution_id,
        "tokens": run.total_tokens,
        "cost_usd": run.cost_usd,
        "steps": len(run.steps),
    }


def _output(answer: str, entries: list, playbooks: list, stopped: str) -> dict:
    return {"answer": answer, "entries": entries, "playbooks": playbooks, "stopped": stopped}


def _message(action: dict, context: dict) -> str:
    """The job as the agent reads it: the step's message, and (``on_entry``, the default) which entry the run is about."""
    message = str(interpolate(action.get("message") or "", context) or "").strip()
    if not message:
        raise AutomationActionError("an agent step needs a message: the job the agent is given")
    entry = context.get("entry")
    if action.get("on_entry", True) and isinstance(entry, dict) and entry.get("id"):
        about = ", ".join(f"{k} {entry[k]}" for k in ("id", "slug", "entry_type", "status", "url") if entry.get(k))
        title = entry.get("title") or entry.get("slug") or entry["id"]
        message += f"\n\nThis run is about the entry “{title}” ({about}). Read it with get_entry when you need its content."
    return message


def _playbook_names(session, group_id, action: dict) -> list[str]:
    """The step's own Playbooks, each a published one that loads by itself (a manual-only Playbook loads only when named in the message)."""
    from marvin.services.playbooks import PlaybookScope, published_playbooks

    names = [str(n).strip() for n in action.get("playbooks") or () if str(n).strip()]
    loadable = {p.name for p in published_playbooks(session, group_id, PlaybookScope())}
    if missing := [n for n in names if n not in loadable]:
        raise AutomationActionError(f"not a published Playbook that loads by itself: {', '.join(missing)}")
    return names


def _author(session, context: dict):
    """The workflow's author, whose role the agent's tools run with (definer's rights, as every step); None for a legacy workflow
    that records none (the engine runs it as an owner)."""
    from marvin.db.models.users.users import Users

    author_id = (context.get("_step") or {}).get("author_id")
    return session.get(Users, author_id) if author_id else None


def _ai_settings(session, group_id):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    return session.query(WorkspaceAISettingsModel).filter_by(group_id=group_id).first()
