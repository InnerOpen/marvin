"""`create_entries_from_template` and `apply_template` steps — entries from pictures with a template, and existing entries
filled with one (services/entries/templates.py, the service behind POST /entries/from-template and /entries/apply-template).

`mode` **preview** (the default) changes nothing: output as the REST answer (EntryTemplateResult): `rows` (each with its
title, from the picture's name, the values it would set and the picture), `create`, `fill`, `skip`, `todo`, `errors`,
`text`. **create** / **apply** does it, and needs `confirm_total`, the preview step's `todo`
(``${steps.<id>.output.todo}``): when there is no longer that much to do it fails and changes nothing, so a run never goes
beyond what the preview showed. Nothing is made while any row has an error. Output then adds `created`, `updated`,
`entry_ids`, `seconds`.

`assets` / `entries` is a list of ids or slugs, or a template naming one (a collect step's ids). The entries send no event
of their own; one `entry_template_applied` (at the run's depth + 1) says what was made and filled.

Authority (the workflow author's role, services/automation/authz.py): making entries needs AUTHOR, as making one does;
filling existing ones (apply_template, or a picture whose entry exists) needs EDITOR. A dry run is a preview, whatever
the mode.
"""

from __future__ import annotations

from ..matcher import interpolate
from .base import AutomationActionError, register_action


def _refs(value, context: dict, what: str) -> list:
    value = interpolate(value, context)
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")] if value.strip() else []
    if not isinstance(value, list):
        raise AutomationActionError(f"{what} must be a list of ids or slugs, not {type(value).__name__}")
    flat = []
    for v in value:
        if isinstance(v, dict):  # a collect step's items: take their id
            v = v.get("id") or v.get("slug")
        if v:
            flat.append(str(v))
    return flat


def _run(session, group_id, action: dict, context: dict, *, kind: str, doing: str, user_id, authorizer_role, dry_run) -> dict:
    from marvin.services.entries import templates

    from ..authz import ROLE_OWNER, TEMPLATE_CREATE_MIN_ROLE, TEMPLATE_FILL_MIN_ROLE, require_role

    mode = action.get("mode") or "preview"
    if mode not in ("preview", doing):
        raise AutomationActionError(f"{kind} mode must be preview or {doing}, not {mode!r}")
    role = ROLE_OWNER if authorizer_role is None else authorizer_role
    entry_type = interpolate(action.get("entry_type"), context)
    template = interpolate(action.get("template"), context)
    replace = bool(action.get("replace"))
    try:
        if kind == "apply_template":
            require_role(role, TEMPLATE_FILL_MIN_ROLE, kind)
            plan = templates.plan_for_entries(
                session, group_id, entry_type, template, _refs(action.get("entries"), context, "entries"), replace=replace
            )
        else:
            require_role(role, TEMPLATE_CREATE_MIN_ROLE, kind)
            plan = templates.plan_from_assets(
                session, group_id, entry_type, template, _refs(action.get("assets"), context, "assets"), replace=replace
            )
            if any(r.action == "fill" for r in plan.rows):
                require_role(role, TEMPLATE_FILL_MIN_ROLE, f"{kind} (filling entries those pictures already have)")
        found = templates.describe(plan)
        if mode == "preview" or dry_run:
            return {**found, "mode": mode, **({"dry_run": True, "would": mode} if dry_run else {})}
        confirm = interpolate(action.get("confirm_total"), context)
        try:
            expected = int(confirm)
        except (TypeError, ValueError) as e:
            raise AutomationActionError(f"{kind}: confirm_total must be the preview's todo, a number, not {confirm!r}") from e
        if expected != found["todo"]:
            raise AutomationActionError(
                f"{kind}: the preview counted {expected} to do, there are {found['todo']} now ({found['text']}); nothing was changed"
            )
        result = templates.execute(
            session, group_id, plan, actor_id=user_id, integration_id="automation", reaction_depth=int(context.get("depth", 0)) + 1
        )
        return {**result, "mode": mode}
    except templates.TemplateError as e:
        raise AutomationActionError(f"{kind}: {e}") from e


@register_action("create_entries_from_template")
def run_create_entries_from_template_action(
    session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False
) -> dict:
    return _run(
        session, group_id, action, context, kind="create_entries_from_template", doing="create", user_id=user_id, authorizer_role=authorizer_role,
        dry_run=dry_run,
    )  # fmt: skip


@register_action("apply_template")
def run_apply_template_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    return _run(
        session, group_id, action, context, kind="apply_template", doing="apply", user_id=user_id, authorizer_role=authorizer_role, dry_run=dry_run
    )  # fmt: skip
