"""`apply_picture_preset` step — treat pictures with one of an entry type's picture presets (services/assets/
picture_presets.py, the service behind POST /assets/apply-preset).

`preset` names the preset (or `template` names a template that has one). `assets` treats those pictures; `entries` treats
each entry's picture and puts the treated one in its place (the template's treated role, featured by default, and its
asset field, where they still hold the original). Either is a list of ids or slugs, or a template naming one (a collect
step's ids, a guided setup's picks); at most 200.

`mode` **preview** (the default) changes nothing: `rows` (each picture, `create` or `reuse` its treated version, or
`skip` with the reason), `create`, `reuse`, `skip`, `todo`, `text`. **apply** does it here, in the run (a run is already
in the background), in chunks of 10 pictures per transaction, and needs `confirm_total`, the preview's `todo`
(``${steps.<id>.output.todo}``). Output then adds `made`, `reused`, `placed`, `failed`, `errors` and `treated` (original
id → treated id) and `ids` (the treated pictures, in order), for a later step.

Each original makes one new picture (`<original>--preset-<hash8>`, reused by a re-run), kept as its version; the original
is never changed and no `asset_uploaded` is sent. Authority: treating pictures needs AUTHOR (as making an asset); putting
them in entries needs EDITOR (any entry).
"""

from __future__ import annotations

from ..matcher import interpolate
from .base import AutomationActionError, register_action
from .entry_templates import _refs


@register_action("apply_picture_preset")
def run_apply_picture_preset_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services.assets import picture_presets as presets

    from ..authz import ROLE_OWNER, TEMPLATE_CREATE_MIN_ROLE, TEMPLATE_FILL_MIN_ROLE, require_role

    kind = "apply_picture_preset"
    mode = action.get("mode") or "preview"
    if mode not in ("preview", "apply"):
        raise AutomationActionError(f"{kind} mode must be preview or apply, not {mode!r}")
    role = ROLE_OWNER if authorizer_role is None else authorizer_role
    entry_type = interpolate(action.get("entry_type"), context)
    preset = interpolate(action.get("preset"), context) or None
    template = interpolate(action.get("template"), context) or None
    entries = _refs(action.get("entries"), context, "entries") if action.get("entries") not in (None, "", []) else []
    try:
        if entries:
            require_role(role, TEMPLATE_FILL_MIN_ROLE, f"{kind} (putting treated pictures in entries)")
            plan = presets.plan_for_entries(
                session, group_id, entry_type, entries, preset=preset, template=template, role=interpolate(action.get("role"), context) or None
            )
        else:
            require_role(role, TEMPLATE_CREATE_MIN_ROLE, kind)
            plan = presets.plan_for_assets(
                session, group_id, entry_type, _refs(action.get("assets"), context, "assets"), preset=preset, template=template
            )
        found = presets.describe(plan)
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
        work = presets.work_of(plan)
        done = presets.execute(session, group_id, work, actor_id=user_id)
    except presets.PresetError as e:
        raise AutomationActionError(f"{kind}: {e}") from e
    ids = [done["treated"][str(s)] for s, _ in work.items if str(s) in done["treated"]]
    return {
        **found,
        "preview": False,
        "mode": mode,
        **{k: done[k] for k in ("made", "reused", "placed", "failed", "errors", "treated", "seconds")},
        "ids": ids,
        "text": f"{found['text']}: {done['made']} made, {done['reused']} reused" + (f", {done['failed']} failed" if done["failed"] else ""),
    }
