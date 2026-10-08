"""Workflow authoring tools: read the format and the workspace, then draft a workflow — always disabled.

Asked to "create a workflow", an agent once said it couldn't, then wrote JSON in a format Marvin doesn't
have. These give it the real one and a way to save it:

- ``workflow_authoring_guide`` — the definition format and this workspace's names, generated from the
  code that runs workflows (services/automation/authoring.py);
- ``get_workflow`` — one workflow's definition and last run, to copy or adapt (``list_workflows`` lists them);
- ``draft_workflow`` — create a workflow through the same write path as ``POST /api/automations``,
  switched off; a definition that wouldn't work comes back as path-by-path issues and nothing is created;
- ``update_workflow_draft`` — revise a workflow that is still switched off.

None of them enables or runs a workflow: that stays a person's decision, in the workflow editor. All are
ADMIN, like the automation routes (a workflow runs with its author's role and can reach the workspace's
integrations and webhooks).
"""

import json

from marvin.services.ui_links import ui_link

from ..operations.base import ROLE_ADMIN
from .base import ToolContext, register_tool
from .builtins import _find_workflow, _workflow_ref

WORKFLOW_EDIT_PATH = "/automation/workflows?workflow={id}&edit=1"


def workflow_edit_link(row) -> str:
    """A finished markdown link to the workflow in the editor (models copy strings; they guess hosts)."""
    return f"[Open “{row.name}” in the workflow editor]({ui_link(WORKFLOW_EDIT_PATH.format(id=row.id))})"


def _last_run(session, row) -> dict | None:
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    run = (
        session.query(AutomationExecutionModel)
        .filter_by(group_id=row.group_id, automation_id=row.id)
        .order_by(AutomationExecutionModel.started_at.desc())
        .first()
    )
    if run is None:
        return None
    return {
        "status": run.status,
        "trigger": run.trigger_type,
        "startedAt": run.started_at.isoformat() if run.started_at else None,
        "durationMs": run.duration_ms,
        "steps": {"total": run.steps_total, "ok": run.steps_ok, "failed": run.steps_failed},
        "error": run.error,
    }


@register_tool(
    name="workflow_authoring_guide",
    description=(
        "How to write a Marvin workflow (automation) definition, read from Marvin's own code: the definition's "
        "shape, trigger types, the events a workflow can start on, the target query keys, condition operators, "
        "step kinds with their fields, entry ops (publish, unpublish → draft, archive, trash, add_to_collection, "
        "set_data…), template syntax (${event.*}, ${entry.*}, ${steps.<id>.output.*}), this workspace's "
        "collections, entry types, integrations and their actions, webhooks and workflows, and the Library recipes "
        "this workspace can run (section=examples lists them; recipe=<id> shows one in full with its setup "
        "variables). Call it before draft_workflow. Without `section` it gives everything in brief; with one, that "
        "part in detail."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["shape", "triggers", "events", "target", "conditions", "actions", "templates", "workspace", "examples"],
                "description": "one part in detail (event descriptions, field types, integration action args, the recipes)",
            },
            "recipe": {"type": "string", "description": "a Library recipe id (from section=examples): its full definition and setup variables"},
        },
    },
    min_role=ROLE_ADMIN,  # it names the workspace's webhooks and integrations, which only admins see
)
def workflow_authoring_guide(ctx: ToolContext, args: dict) -> str:
    from marvin.services.automation.authoring import authoring_guide

    section = args.get("section") or ("examples" if args.get("recipe") else None)
    try:
        return json.dumps(authoring_guide(ctx.session, ctx.group_id, section, args.get("recipe") or None))
    except ValueError as e:
        return json.dumps({"error": str(e)})


@register_tool(
    name="get_workflow",
    description=(
        "One workflow (automation) by slug, name or id: its name, slug, whether it is enabled, its full definition, "
        "its last run and a link to it in the editor. Use it to copy or adapt an existing workflow, or to see why "
        "one didn't do what was expected."
    ),
    input_schema={
        "type": "object",
        "properties": {"workflow": {"type": "string", "description": "workflow slug, name, or id"}},
        "required": ["workflow"],
    },
    min_role=ROLE_ADMIN,
)
def get_workflow(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    ref = str(args.get("workflow") or "").strip()
    row = _find_workflow(ctx.session, ctx.group_id, ref) if ref else None
    if row is None:
        rows = ctx.session.query(WorkspaceAutomationModel).filter_by(group_id=ctx.group_id).order_by(WorkspaceAutomationModel.name).all()
        return json.dumps({"error": f"no workflow '{ref}' in this workspace", "available": [_workflow_ref(a) for a in rows]})
    return json.dumps(
        {
            "id": str(row.id),
            "name": row.name,
            "slug": row.slug,
            "enabled": bool(row.enabled),
            "definition": row.definition or {},
            "installedBy": row.source_blueprint,
            "lastRun": _last_run(ctx.session, row),
            "editLink": workflow_edit_link(row),
        },
        default=str,
    )


_DEFINITION_SCHEMA = {
    "type": "object",
    "description": (
        'The workflow definition: {"trigger": {…}, "target"?: {…}, "conditions"?: […], "actions": […], "on_failure"?: […]} '
        "exactly as workflow_authoring_guide describes (a whole workflow {name, definition} is accepted too)."
    ),
}


def _refused(error: str, issues: list[dict] | None = None, **extra) -> str:
    out: dict = {"error": error, **extra}
    if issues:
        out["issues"] = [{"path": i.get("path") or i.get("where") or "", "message": i["message"]} for i in issues]
        out["fix"] = "Nothing was saved. Fix each issue (workflow_authoring_guide has the valid names) and call again."
    return json.dumps(out)


def _check(ctx: ToolContext, definition: dict) -> str | None:
    """The refusal for a definition that can't be drafted, or None."""
    from marvin.services.automation.authoring import draft_issues

    issues = draft_issues(ctx.session, ctx.group_id, definition)
    return _refused("The workflow definition has problems.", issues) if issues else None


def _from_recipe(ctx: ToolContext, recipe_id: str, values) -> tuple[dict | None, str | None]:
    """A Library recipe instantiated with `vars`: the whole workflow document, or the refusal — the recipe
    isn't offered here (unknown, not runnable, a prerequisite missing) or a value is missing / mistyped."""
    from marvin.services.automation import recipes
    from marvin.services.automation.authoring import workspace_refs
    from marvin.services.automation.library import RecipeConfigError

    refs = workspace_refs(ctx.session, ctx.group_id)
    offered = {r["id"]: r for r in recipes.offered(refs)}
    if recipe_id not in offered:
        known = next((r for r in recipes.entries() if r["id"] == recipe_id), None)
        if known is None:
            return None, _refused(f"No recipe “{recipe_id}”.", available=sorted(offered))
        why = "; ".join(recipes.missing_prerequisites(known, refs)) or f"its status is {known['status']} (not runnable)"
        return None, _refused(f"Recipe “{recipe_id}” can't be drafted in this workspace: {why}.", available=sorted(offered))
    if values is not None and not isinstance(values, dict):
        return None, _refused("vars must be an object of setup variable values.")
    try:
        return recipes.instantiate(recipe_id, dict(values or {})), None
    except RecipeConfigError as e:
        return None, _refused(
            f"Recipe “{recipe_id}”: {e}",
            setup_variables=recipes.load_vars(recipe_id),
            fix="Pass every setup variable in vars, typed as described, and call again.",
        )


def _saved(ctx: ToolContext, row, parsed, *, created: bool) -> str:
    from marvin.services.automation.validation import validate_definition

    out = {
        "workflow": {"id": str(row.id), "slug": row.slug, "name": row.name, "enabled": bool(row.enabled)},
        "created" if created else "updated": True,
        "editLink": workflow_edit_link(row),
        "next": (
            "It is switched off. Give the user the editLink verbatim and say what to check before they enable it: the "
            "trigger, which entries it acts on (a dry run shows them without changing anything), and each step. Tell them "
            "every warning in your own words."
        ),
    }
    warnings = [w["message"] for w in validate_definition(row.definition)]
    if warnings:
        out["warnings"] = warnings
    if not created:
        out["next"] += f" Say plainly that you changed the existing workflow “{row.name}” — it is not a new one."
    if parsed.ignored:
        out["ignored"] = parsed.ignored
    return json.dumps(out)


@register_tool(
    name="draft_workflow",
    description=(
        "Create a workflow (automation), switched OFF, for the user to review and enable — either from a Library recipe "
        "(`recipe` + `vars`: the recipe's {{placeholders}} are filled with typed values from this workspace, see "
        "workflow_authoring_guide section=examples) or from a `definition` you write from workflow_authoring_guide "
        "(call it first) — Marvin's format only: trigger / target / conditions / actions with `kind` steps. It is "
        "checked exactly as the workflow editor's save is, plus unknown keys and names this workspace doesn't have; on "
        "problems nothing is saved and `issues` say what to fix at which path — fix them and call again. Never enables "
        "or runs anything. Keep the trigger the user asked for (`manual` when they named none). Give the user the "
        "result's editLink verbatim."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "the workflow's name, e.g. 'Move entries with images to draft' (a recipe's title when omitted)",
            },
            "definition": _DEFINITION_SCHEMA,
            "recipe": {"type": "string", "description": "a Library recipe id to instantiate instead of writing a definition"},
            "vars": {
                "type": "object",
                "description": (
                    "the recipe's setup variables by name, typed as its setup_variables say (an entry type slug, a collection slug, "
                    "an integration slug, a webhook id, a number…)"
                ),
            },
        },
    },
    # ADMIN, like POST /automations: the workflow runs with its author's role.
    min_role=ROLE_ADMIN,
    read_only=False,
)
def draft_workflow(ctx: ToolContext, args: dict) -> str:
    from marvin.schemas.group.automation import AutomationCreate
    from marvin.services.automation.authoring import parse_workflow
    from marvin.services.automation.workflows import SlugConflict, WorkflowError, create_workflow

    if args.get("recipe"):
        document, refusal = _from_recipe(ctx, str(args["recipe"]), args.get("vars"))
        if refusal:
            return refusal
    elif args.get("definition") is not None:
        document = args["definition"]
    else:
        return _refused("Pass a definition, or a recipe id (with vars) from workflow_authoring_guide section=examples.")
    parsed = parse_workflow(document)
    if parsed.error:
        return _refused(parsed.error, [{"path": "definition", "message": parsed.error}])
    name = str(args.get("name") or "").strip() or parsed.name
    if not name:
        return _refused("name is required.")
    refusal = _check(ctx, parsed.definition)
    if refusal:
        return refusal
    # Never enabled from here, whatever was passed: switching it on is the user's call.
    data = AutomationCreate(name=name, slug=parsed.slug, enabled=False, definition=parsed.definition)
    try:
        row = create_workflow(ctx.session, ctx.group_id, getattr(ctx.user, "id", None), data, agent_draft=True)
    except SlugConflict as e:
        taken = _find_workflow(ctx.session, ctx.group_id, e.slug)
        revisable = taken is not None and not taken.enabled and taken.agent_draft
        revise = ", or revise that one with update_workflow_draft (an agent's draft, still switched off)" if revisable else ""
        error = f"A workflow with the slug '{e.slug}' already exists. Pick another name{revise}."
        return _refused(error, existing=_workflow_ref(taken) if taken else None)
    except WorkflowError as e:  # the gate draft_issues already ran; kept so a refusal never surfaces as a crash
        return _refused(str(e), getattr(e, "issues", None))
    return _saved(ctx, row, parsed, created=True)


@register_tool(
    name="update_workflow_draft",
    description=(
        "Revise a workflow an agent drafted that is still switched OFF and unedited by the user: a new name and/or a whole "
        "new definition (checked like draft_workflow). Anything else — enabled, or the user's own work — is refused: ask "
        "the user, who can edit it themselves. "
        "Never enables or runs it. get_workflow gives the current definition to start from."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "workflow": {"type": "string", "description": "workflow slug, name, or id"},
            "name": {"type": "string", "description": "a new name (the slug stays)"},
            "definition": _DEFINITION_SCHEMA,
        },
        "required": ["workflow"],
    },
    min_role=ROLE_ADMIN,
    read_only=False,
)
def update_workflow_draft(ctx: ToolContext, args: dict) -> str:
    from marvin.schemas.group.automation import AutomationUpdate
    from marvin.services.automation.authoring import ParsedWorkflow, parse_workflow
    from marvin.services.automation.workflows import WorkflowError, update_workflow

    ref = str(args.get("workflow") or "").strip()
    row = _find_workflow(ctx.session, ctx.group_id, ref) if ref else None
    if row is None:
        return _refused(f"no workflow '{ref}' in this workspace — list_workflows lists them.")
    if row.enabled:
        return _refused(
            f"“{row.name}” is enabled, so it can't be changed from here. The user can switch it off first, or edit it themselves.",
            editLink=workflow_edit_link(row),
        )
    if not row.agent_draft:
        return _refused(
            f"“{row.name}” is the user's own work (they made it, or saved it since an agent drafted it), so it can't be "
            "changed from here. Ask them first — they can edit it themselves — or draft a new workflow under another name.",
            editLink=workflow_edit_link(row),
        )
    changes: dict = {}
    parsed = ParsedWorkflow()
    if args.get("definition") is not None:
        parsed = parse_workflow(args["definition"])
        if parsed.error:
            return _refused(parsed.error, [{"path": "definition", "message": parsed.error}])
        refusal = _check(ctx, parsed.definition)
        if refusal:
            return refusal
        changes["definition"] = parsed.definition
    name = str(args.get("name") or "").strip()
    if name:
        changes["name"] = name
    if not changes:
        return _refused("Nothing to change: pass a name and/or a definition.")
    try:
        row = update_workflow(ctx.session, ctx.group_id, row, AutomationUpdate(**changes), by_agent=True)
    except WorkflowError as e:
        return _refused(str(e), getattr(e, "issues", None))
    return _saved(ctx, row, parsed, created=False)
