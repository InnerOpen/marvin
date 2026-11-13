"""`delete_entries` step — delete many entries at once (services/entries/bulk_delete.py).

`mode` **preview** (the default) counts what `query` selects by entry type and changes nothing (entries in the Trash
too, when the query's statuses name `trashed`: a trash delete leaves those out, a permanent one takes them): output `total`, `text`
("144 scenes, 600 beats and 770 speech lines"), `by_type`, `types`, `published`, `in_trash`. **trash** moves them to the
Trash in chunks (restorable; each slug is moved aside so new entries can use it), **permanent** deletes them for good.
A delete needs `confirm_total`, the preview step's `total` (``${steps.<id>.output.total}``): when the query no longer
selects that many entries it fails and deletes nothing, so a delete never goes beyond what the preview showed. Output:
`mode`, `deleted`, `text`, `by_type`, `types`, `published`, `chunks`, `seconds`.

The run is the job: it records the step like any other, and the wizard's run step polls it. The entries send no event of
their own; one `entries_bulk_deleted` (with `description`) says what went, at the run's depth + 1.

Authority (the workflow author's role, services/automation/authz.py): a preview and a trash need EDITOR (any entry, as an
editor deletes them one by one), a permanent delete ADMIN — put an approval with `approvers: admin` in front of it, since
the person who decides is not the author. A dry run is a preview, whatever the mode.
"""

from __future__ import annotations

from ..matcher import interpolate
from .base import AutomationActionError, register_action


@register_action("delete_entries")
def run_delete_entries_action(session, group_id, action: dict, context: dict, *, user_id=None, authorizer_role=None, dry_run=False) -> dict:
    from marvin.services.entries import bulk_delete

    from ..authz import BULK_DELETE_MIN_ROLE, BULK_TRASH_MIN_ROLE, ROLE_OWNER, require_role

    mode = action.get("mode") or "preview"
    if mode not in ("preview", *bulk_delete.MODES):
        raise AutomationActionError(f"delete_entries mode must be preview, trash or permanent, not {mode!r}")
    role = ROLE_OWNER if authorizer_role is None else authorizer_role
    require_role(role, BULK_DELETE_MIN_ROLE if mode == "permanent" else BULK_TRASH_MIN_ROLE, f"delete_entries {mode}")
    spec = interpolate(action.get("query") or {}, context)
    # A preview counts what the query selects, nothing left out (entries in the Trash too when its statuses name trashed):
    # the total a permanent delete of the same query confirms. A trash delete never counts what is already in the Trash.
    counted_as = "trash" if mode == "trash" else "permanent"
    try:
        if refused := bulk_delete.refusal(session, group_id, spec, "permanent" if mode == "permanent" else "trash", role=role):
            raise AutomationActionError(f"delete_entries {mode}: {refused}")
        if mode == "preview" or dry_run:
            found = bulk_delete.preview(session, group_id, spec, mode=counted_as)
            return {**found, "mode": mode, **({"dry_run": True, "would": mode} if dry_run else {})}
        description = interpolate(action.get("description"), context) if action.get("description") else None
        return bulk_delete.execute(
            session,
            group_id,
            spec,
            mode=mode,
            confirm_total=interpolate(action.get("confirm_total"), context),
            actor_id=user_id,
            description=str(description) if description else None,
            integration_id="automation",
            reaction_depth=int(context.get("depth", 0)) + 1,
        )
    except bulk_delete.BulkDeleteError as e:
        raise AutomationActionError(f"delete_entries: {e}") from e
