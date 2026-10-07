"""Built-in TRASH tool — the agent's "delete" for entries.

Deleting an entry in Marvin moves it to the Trash (services/entries/trash.py): it leaves the site, every
listing and search, sits in the Trash collection, and comes back with Restore until someone empties the
Trash. `trash_entries` is that same Delete for an agent — so "delete the test signups" does what the user
said, and stays reversible. Emptying the Trash and deleting forever stay a person's action: no tool here
does either.

It mirrors `archive_entries` (builtins_archive.py) step for step: EntryService.trash, the path the entry
page's Move to Trash takes, so `entry_updated` / `entry_unpublished` / `entry_trashed`, smart collections,
the site rebuild and the audit log behave identically; each entry is checked with the entry page's own
rule (`require_can_edit_entry` with the new status) and the ones the caller may not change are skipped
and reported; min_role is EDITOR like every AI write tool. Trashing a published entry takes it off the
site, so a call that would do that asks first (`ask_first` → an approval card).
"""

import json
import uuid as _uuid
from dataclasses import dataclass, field

from fastapi import HTTPException

from ..entity_resolve import resolve_entity_id
from ..operations.base import ROLE_EDITOR
from .base import ToolContext, register_tool
from .builtins_archive import _refs, _row
from .bulk_writes import PREVIEW_MAX_TARGETS, AskFirst

MAX_TRASH_BATCH = 50
TRASHED = "trashed"
UNDO_HINT = (
    "Nothing is deleted forever. Trashed entries are off the site and the publishing API and are listed in the "
    "Trash collection. To undo, open the Trash and choose Restore: each entry goes back to the status it had "
    "(a published entry comes back as a draft, to publish again). Only a person can empty the Trash."
)


@dataclass
class _Plan:
    """What one call would do, worked out without writing."""

    trash: list = field(default_factory=list)  # Entries rows to trash
    skipped: list[dict] = field(default_factory=list)  # {entry, reason}
    already: list[dict] = field(default_factory=list)  # {id, title}

    @property
    def published(self) -> list:
        return [e for e in self.trash if e.status == "published"]


def _plan(ctx: ToolContext, args: dict) -> tuple[_Plan | None, str | None]:
    """(plan, None), or (None, error) for a call that can't run at all."""
    from marvin.db.models.platform.entries import Entries
    from marvin.routes._base.checks import require_can_edit_entry

    refs = _refs(args)
    if not refs:
        return None, "name at least one entry (slug or id) in `entries`"
    if len(refs) > MAX_TRASH_BATCH:
        return None, f"at most {MAX_TRASH_BATCH} entries per call ({len(refs)} given) — trash them in smaller batches"
    if ctx.user is None:
        return None, "trashing needs a signed-in caller"

    plan = _Plan()
    seen: set = set()
    for ref in refs:
        eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", ref)
        entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
        if entry is None or entry.group_id != ctx.group_id:
            plan.skipped.append({"entry": ref, "reason": "not found in this workspace"})
            continue
        if entry.id in seen:
            continue
        seen.add(entry.id)
        if entry.status == TRASHED:
            plan.already.append(_row(entry))
            continue
        try:
            require_can_edit_entry(ctx.user, ctx.group_id, entry, TRASHED)
        except HTTPException as e:
            plan.skipped.append({**_row(entry), "entry": ref, "reason": str(e.detail)})
            continue
        plan.trash.append(entry)
    return plan, None


def _ask_first(ctx: ToolContext, args: dict) -> AskFirst | None:
    """Ask before a call that would trash a published entry; None for everything else."""
    plan, err = _plan(ctx, args)
    if err or not plan.published:
        return None
    live = plan.published
    n, k = len(plan.trash), len(live)
    summary = f"Move {n} {'entry' if n == 1 else 'entries'} to the Trash — {k} {'is' if k == 1 else 'are'} published and will come off the site"
    shown = plan.trash[:PREVIEW_MAX_TARGETS]
    preview = {
        "summary": summary,
        "action": "trash",
        "links": n,
        "targetType": "entry",
        "targetCount": n,
        "targets": [f"{e.title} (published)" if e.status == "published" else e.title for e in shown],
        "itemKind": "",
        "items": [],
    }
    refusal = json.dumps(
        {
            "error": (
                f"Not done: {summary}. Trashing a published entry needs the user's approval and this run cannot "
                "pause to ask. Call trash_entries again without the published entries to trash the rest, and ask "
                "the user to delete the published ones themselves or to approve it in a conversation where they can."
            ),
            "published": [_row(e) for e in live],
        }
    )
    return AskFirst(preview=preview, refusal=refusal)


@register_tool(
    name="trash_entries",
    description=(
        "Move entries to the Trash — what Delete does in Marvin. Use this whenever the user asks to delete, remove, "
        "clear out or get rid of entries (e.g. test or spam entries). Trashed entries leave the site, the publishing "
        "API and every listing, and can be restored from the Trash until a person empties it. Up to 50 entries per "
        "call by slug or id, plus an optional short reason. Trashing a published entry asks the user first. Entries "
        "you may not change are skipped and reported. You cannot empty the Trash or delete anything forever: tell "
        "the user the entries are in the Trash and how to restore them (the result's `undo`), and give them the "
        "result's trashLink verbatim. To retire an entry that should be kept, use archive_entries instead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_TRASH_BATCH,
                "description": "the entries to move to the Trash, by slug or id",
            },
            "reason": {"type": "string", "description": "optional short reason, e.g. 'test signups'"},
        },
        "required": ["entries"],
    },
    min_role=ROLE_EDITOR,
    read_only=False,
    ask_first=_ask_first,
)
def trash_entries(ctx: ToolContext, args: dict) -> str:
    from marvin.db.models.platform.collections import Collections
    from marvin.services.collections.system_collections import TRASH_COLLECTION_SLUG
    from marvin.services.entries import EntryService
    from marvin.services.ui_links import entry_edit_url, ui_link

    plan, err = _plan(ctx, args)
    if err:
        return json.dumps({"error": err})

    svc = EntryService(ctx.session, ctx.group_id, actor_id=getattr(ctx.user, "id", None))
    trashed, skipped = [], list(plan.skipped)
    for entry in plan.trash:
        was, row = entry.status, _row(entry)
        try:
            svc.trash(entry.id)
        except Exception as e:  # noqa: BLE001 — one entry failing must not lose the others' results
            ctx.session.rollback()
            skipped.append({**row, "reason": str(getattr(e, "detail", e))})
            continue
        trashed.append({**row, "was": was, "editUrl": entry_edit_url(entry.id)})

    trash = ctx.session.query(Collections.id).filter(Collections.group_id == ctx.group_id, Collections.slug == TRASH_COLLECTION_SLUG).first()
    reason = str(args.get("reason") or "").strip()[:200]
    return json.dumps(
        {
            "trashed": trashed,
            "skipped": skipped,
            "alreadyTrashed": plan.already,
            **({"reason": reason} if reason else {}),
            "undo": UNDO_HINT,
            # A finished markdown link, like revise_entry's reviewLink: models copy strings, they guess hosts.
            **({"trashLink": f"[Open the Trash]({ui_link(f'/workspace/collections/{trash[0]}')})"} if trash else {}),
        }
    )
