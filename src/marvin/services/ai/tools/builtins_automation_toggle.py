"""Built-in `set_automation_enabled` — switch an existing automation on or off, after the admin approves.

Asked to turn on Slack announcements for publishes, an agent could find the integration action the
`announce-published-entries` blueprint installed — switched off, as blueprints install them on purpose — but
could only tell the admin to flip it. This tool flips it, and nothing else: `enabled` on an integration action
(an event → action connection) or a workflow, by the id `describe_event` returns. Never args, definitions,
triggers, credentials or the integration itself (services/automation/toggle.py, shared with the admin pages so
a switch from either is audited the same way).

Every call asks first: an automation reaches outside the workspace (a Slack post, an email, a webhook), and
switching one off silently stops alerts. The approval card says what it is, what it reacts to, what it does,
who installed it, the switch from → to, and whether its integration is on. A run that can't pause (MarvinMCP)
is refused. ADMIN only, like the pages.
"""

import json

from ..operations.base import ROLE_ADMIN
from .base import ToolContext, register_tool
from .bulk_writes import AskFirst

_KIND_LABEL = {"integration_action": "integration action", "workflow": "workflow"}


def _target(ctx: ToolContext, args: dict):
    """(automation, wanted state, None), or (None, None, error)."""
    from marvin.services.automation import toggle

    kind = str(args.get("kind") or "")
    if kind not in toggle.KINDS:
        return None, None, f"`kind` must be one of {', '.join(toggle.KINDS)}"
    enabled = args.get("enabled")
    if not isinstance(enabled, bool):
        return None, None, "`enabled` must be true or false"
    target = toggle.find(ctx.session, ctx.group_id, kind, args.get("id"))
    if target is None:
        return None, None, f"no {_KIND_LABEL[kind]} with that id in this workspace — use describe_event to find it"
    return target, enabled, None


def _ask_first(ctx: ToolContext, args: dict) -> AskFirst | None:
    """Every real switch asks; a call that can't run, or one that changes nothing, answers without asking."""
    target, enabled, err = _target(ctx, args)
    if err or target.enabled == enabled:
        return None
    verb = "Switch on" if enabled else "Switch off"
    summary = f"{verb} the {_KIND_LABEL[target.kind]} “{target.name}”"
    targets = [
        f"It {target.does}",
        f"Now {'on' if target.enabled else 'off'} → {'on' if enabled else 'off'}",
    ]
    if target.source_blueprint:
        targets.append(f"Installed by the {target.source_blueprint} blueprint")
    if target.agent_draft and enabled:
        targets.append("It is a draft an agent wrote; switching it on makes it live")
    if warning := target.warning(enabled):
        targets.append(warning)
    preview = {
        "summary": summary,
        "action": "enable" if enabled else "disable",
        "links": 1,
        "targetType": target.kind,
        "targetCount": 1,
        "targets": targets,
        "itemKind": "",
        "items": [],
    }
    refusal = json.dumps(
        {
            "error": (
                f"Not done: {summary}. Switching an automation on or off needs the admin's approval and this run cannot "
                "pause to ask. Ask them to do it on the Events or Workflows page, or in a conversation where they can approve it."
            )
        }
    )
    return AskFirst(preview=preview, refusal=refusal)


@register_tool(
    name="set_automation_enabled",
    description=(
        "Switch an existing automation on or off: an integration action (an event → action connection, e.g. Slack "
        "send_message on entry_published) or a workflow. Use the `kind` and `id` describe_event returns for it. Always "
        "asks the user first. Changes only whether it runs — never its settings, and never the integration itself: if "
        "the integration is switched off the result says the action still won't run (tell the user). Already in that "
        "state → nothing changes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["integration_action", "workflow"], "description": "what it is, as describe_event lists it"},
            "id": {"type": "string", "description": "its id, as describe_event lists it"},
            "enabled": {"type": "boolean", "description": "true to switch it on, false to switch it off"},
            "reason": {"type": "string", "description": "optional short reason, kept in the audit log"},
        },
        "required": ["kind", "id", "enabled"],
    },
    min_role=ROLE_ADMIN,
    read_only=False,
    ask_first=_ask_first,
)
def set_automation_enabled(ctx: ToolContext, args: dict) -> str:
    from marvin.services.automation import toggle

    target, enabled, err = _target(ctx, args)
    if err:
        return json.dumps({"error": err})
    changed = toggle.set_enabled(
        ctx.session, ctx.group_id, target, enabled, actor_id=getattr(ctx.user, "id", None), via=toggle.VIA_AGENT, reason=args.get("reason")
    )
    result = {
        "kind": target.kind,
        "id": str(target.row.id),
        "name": target.name,
        "enabled": enabled,
        "effective": target.effective(enabled),
        "changed": changed,
    }
    if not changed:
        result["note"] = f"It was already {'on' if enabled else 'off'}; nothing changed."
    if warning := target.warning(enabled):
        result["warning"] = warning
    return json.dumps(result)
