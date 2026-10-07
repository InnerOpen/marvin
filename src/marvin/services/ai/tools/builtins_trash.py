"""Built-in TRASH tools — the agent's "delete" for entries, assets and resources.

Deleting an entry in Marvin moves it to the Trash (services/entries/trash.py): it leaves the site, every
listing and search, sits in the Trash collection, and comes back with Restore until someone empties the
Trash. Assets and resources go to the same Trash (services/trash.py): out of sight, an asset's file kept.
`trash_entries` is that same Delete for an agent — so "delete the test signups" or "delete that old banner
image" does what the user said, and stays reversible — and `restore_entries` is the Trash's Restore. Both
take `entries` and, alongside, `assets` and `resources`. Emptying the Trash and deleting forever stay a
person's action: no tool here does either.

For entries it mirrors `archive_entries` (builtins_archive.py) step for step: EntryService.trash, the path the
entry page's Move to Trash takes, so `entry_updated` / `entry_unpublished` / `entry_trashed`, smart
collections, the site rebuild and the audit log behave identically; each entry is checked with the entry
page's own rule (`require_can_edit_entry` with the new status) and the ones the caller may not change are
skipped and reported. Assets and resources go through services/trash.py, the path their pages' Move to Trash
takes (`asset_trashed` / `resource_trashed`); changing them is EDITOR+, which is every AI write tool's
min_role. Trashing a published entry, or an asset or resource a site shows (attached to a published entry, in
a public collection, the site logo), takes something off the site, so a call that would do that asks first
(`ask_first` → an approval card).
"""

import json
import uuid as _uuid
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import func

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
ITEMS_UNDO_HINT = (
    "Trashed assets and resources are off the site and out of every list (an asset's file is kept); they are on the "
    "Trash's Assets and Resources tabs, and Restore puts each back where it was."
)
# The argument naming each kind besides entries.
ITEM_ARGS = {"assets": "asset", "resources": "resource"}

_ITEM_ARG_SCHEMA = {
    "assets": "assets, by id, slug, or filename/name when only one asset has it",
    "resources": "resources, by id, slug, or name when only one resource has it",
}


def _item_refs(args: dict, key: str) -> list[str]:
    return _refs({"entries": args.get(key)})


def _total(args: dict) -> int:
    return len(_refs(args)) + sum(len(_item_refs(args, key)) for key in ITEM_ARGS)


def _batch_error(args: dict, verb: str) -> str | None:
    """Why a call can't run at all: nothing named, or more than MAX_TRASH_BATCH things."""
    n = _total(args)
    if not n:
        return "name at least one entry (slug or id) in `entries`, or assets / resources in `assets` / `resources`"
    if n > MAX_TRASH_BATCH:
        return f"at most {MAX_TRASH_BATCH} entries, assets and resources per call ({n} given) — {verb} them in smaller batches"
    return None


def _resolve_item(ctx: ToolContext, kind: str, ref: str):
    """An asset or resource of this workspace by id or slug — or, when exactly one has it, by name (an asset also by
    its filename), case-insensitively; never a guess between two. None when nothing (or more than one) matches."""
    from marvin.services import trash

    model = trash.model(kind)
    item_id = resolve_entity_id(ctx.session, ctx.group_id, kind, ref)
    row = ctx.session.get(model, item_id) if isinstance(item_id, _uuid.UUID) else None
    if row is not None:
        return row if row.group_id == ctx.group_id else None
    columns = (model.original_filename, model.name) if kind == "asset" else (model.name,)
    hits = {}
    for col in columns:
        hits.update({r.id: r for r in ctx.session.query(model).filter(model.group_id == ctx.group_id, func.lower(col) == ref.lower()).limit(2)})
    return next(iter(hits.values())) if len(hits) == 1 else None


def _item_row(kind: str, row) -> dict:
    out = {"kind": kind, "id": str(row.id), "name": row.name, "slug": row.slug}
    if kind == "asset":
        out["filename"] = row.original_filename
    return out


def _plan_items(ctx: ToolContext, args: dict, *, in_trash: bool) -> tuple[list, list[dict], list[dict]]:
    """For every asset/resource ref: (to move [(kind, row)], skipped [{kind ref, reason}], already where the move
    would put it [row]). ``in_trash`` is where the rows must be now to move (False to trash, True to restore)."""
    from marvin.services import trash

    move, skipped, already = [], [], []
    seen: set = set()
    for key, kind in ITEM_ARGS.items():
        for ref in _item_refs(args, key):
            row = _resolve_item(ctx, kind, ref)
            if row is None:
                skipped.append({kind: ref, "reason": "not found in this workspace (or the name matches more than one)"})
                continue
            if row.id in seen:
                continue
            seen.add(row.id)
            if trash.is_trashed(row) != in_trash:
                already.append(_item_row(kind, row))
                continue
            move.append((kind, row))
    return move, skipped, already


@dataclass
class _Plan:
    """What one call would do, worked out without writing."""

    trash: list = field(default_factory=list)  # Entries rows to trash
    skipped: list[dict] = field(default_factory=list)  # {entry, reason} (or {asset|resource, reason})
    already: list[dict] = field(default_factory=list)  # {id, title} (or an item row)
    items: list = field(default_factory=list)  # (kind, row) assets and resources to trash

    @property
    def published(self) -> list:
        return [e for e in self.trash if e.status == "published"]

    def on_site(self, session) -> list:
        """The assets and resources to trash that a site shows."""
        from marvin.services.publish_visibility import item_visible_to_sites

        return [(kind, row) for kind, row in self.items if item_visible_to_sites(session, kind, row)]


def _plan(ctx: ToolContext, args: dict) -> tuple[_Plan | None, str | None]:
    """(plan, None), or (None, error) for a call that can't run at all."""
    from marvin.db.models.platform.entries import Entries
    from marvin.routes._base.checks import require_can_edit_entry

    if err := _batch_error(args, "trash"):
        return None, err
    if ctx.user is None:
        return None, "trashing needs a signed-in caller"

    plan = _Plan()
    seen: set = set()
    for ref in _refs(args):
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
    plan.items, item_skips, item_already = _plan_items(ctx, args, in_trash=False)
    plan.skipped += item_skips
    plan.already += item_already
    return plan, None


def _ask_first(ctx: ToolContext, args: dict) -> AskFirst | None:
    """Ask before a call that would take something off the site — a published entry, or an asset or resource a
    site shows; None for everything else."""
    plan, err = _plan(ctx, args)
    if err:
        return None
    live, shown = plan.published, plan.on_site(ctx.session)
    if not live and not shown:
        return None
    if not plan.items:  # entries only: the wording the entry tools have always used
        n, k = len(plan.trash), len(live)
        summary = f"Move {n} {'entry' if n == 1 else 'entries'} to the Trash — {k} {'is' if k == 1 else 'are'} published and will come off the site"
    else:
        n, k = len(plan.trash) + len(plan.items), len(live) + len(shown)
        summary = f"Move {n} {'item' if n == 1 else 'items'} to the Trash — {k} {'is' if k == 1 else 'are'} on the site and will come off it"
    shown_ids = {row.id for _, row in shown}
    targets = [f"{e.title} (published)" if e.status == "published" else e.title for e in plan.trash]
    targets += [f"{row.name} ({kind}, on the site)" if row.id in shown_ids else f"{row.name} ({kind})" for kind, row in plan.items]
    preview = {
        "summary": summary,
        "action": "trash",
        "links": n,
        "targetType": "entry" if not plan.items else "item",
        "targetCount": n,
        "targets": targets[:PREVIEW_MAX_TARGETS],
        "itemKind": "",
        "items": [],
    }
    what = (
        "Trashing a published entry needs the user's approval and this run cannot pause to ask. Call trash_entries "
        "again without the published entries"
        if not plan.items
        else "Taking something off the site needs the user's approval and this run cannot pause to ask. Call "
        "trash_entries again without the published entries and the assets and resources on the site"
    )
    refusal = json.dumps(
        {
            "error": (
                f"Not done: {summary}. {what} to trash the rest, and ask the user to delete "
                f"{'the published ones' if not plan.items else 'those'} themselves or to approve it in a conversation "
                "where they can."
            ),
            "published": [_row(e) for e in live],
            **({"onSite": [_item_row(kind, row) for kind, row in shown]} if shown else {}),
        }
    )
    return AskFirst(preview=preview, refusal=refusal)


def _items_schema(verb: str) -> dict:
    return {
        key: {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": MAX_TRASH_BATCH,
            "description": f"the {desc} to {verb}",
        }
        for key, desc in _ITEM_ARG_SCHEMA.items()
    }


def _move_items(ctx: ToolContext, items: list, *, restore: bool) -> tuple[dict[str, list], list[dict]]:
    """Trash or restore each (kind, row) through services/trash.py: ({assets: [...], resources: [...]}, failures)."""
    from marvin.services import trash
    from marvin.services.ui_links import ui_link

    moved: dict[str, list] = {"assets": [], "resources": []}
    failed: list[dict] = []
    move = trash.restore if restore else trash.trash
    for kind, row in items:
        out = _item_row(kind, row)
        try:
            move(ctx.session, ctx.group_id, kind, row.id, actor_id=getattr(ctx.user, "id", None))
        except Exception as e:  # noqa: BLE001 — one item failing must not lose the others' results
            ctx.session.rollback()
            failed.append({**out, "reason": str(getattr(e, "detail", e))})
            continue
        moved[f"{kind}s"].append({**out, "editUrl": ui_link(f"/workspace/{kind}s/{row.id}")})
    return moved, failed


@register_tool(
    name="trash_entries",
    description=(
        "Move entries, assets or resources to the Trash — what Delete does in Marvin. Use this whenever the user asks "
        "to delete, remove, clear out or get rid of entries (e.g. test or spam entries), assets (images, files) or "
        "resources. Trashed items leave the site, the publishing API and every listing, and can be restored from the "
        "Trash until a person empties it (an asset's file is kept until then). Up to 50 per call in total: `entries` "
        "by slug or id, `assets` by id, slug or filename, `resources` by id, slug or name, plus an optional short "
        "reason. Trashing a published entry, or an asset or resource the site shows, asks the user first. Items "
        "you may not change are skipped and reported. You cannot empty the Trash or delete anything forever: tell "
        "the user the items are in the Trash and how to restore them (the result's `undo`), and give them the "
        "result's trashLink verbatim. To retire an entry that should be kept, use archive_entries instead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_TRASH_BATCH,
                "description": "the entries to move to the Trash, by slug or id",
            },
            **_items_schema("move to the Trash"),
            "reason": {"type": "string", "description": "optional short reason, e.g. 'test signups'"},
        },
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
    items, failed = _move_items(ctx, plan.items, restore=False)
    skipped += failed

    trash = ctx.session.query(Collections.id).filter(Collections.group_id == ctx.group_id, Collections.slug == TRASH_COLLECTION_SLUG).first()
    reason = str(args.get("reason") or "").strip()[:200]
    named_items = any(_item_refs(args, key) for key in ITEM_ARGS)
    return json.dumps(
        {
            "trashed": trashed,
            **({"trashedAssets": items["assets"], "trashedResources": items["resources"]} if named_items else {}),
            "skipped": skipped,
            "alreadyTrashed": plan.already,
            **({"reason": reason} if reason else {}),
            "undo": f"{UNDO_HINT} {ITEMS_UNDO_HINT}" if named_items else UNDO_HINT,
            # A finished markdown link, like revise_entry's reviewLink: models copy strings, they guess hosts.
            **({"trashLink": f"[Open the Trash]({ui_link(f'/workspace/collections/{trash[0]}')})"} if trash else {}),
        }
    )


def _restore_plan(ctx: ToolContext, args: dict) -> tuple[dict | None, str | None]:
    """({restore, items, skipped, notTrashed}, None), or (None, error) for a call that can't run at all."""
    from marvin.db.models.platform.entries import Entries
    from marvin.routes._base.checks import require_can_edit_entry
    from marvin.services.entries.entry_service import restore_status

    if err := _batch_error(args, "restore"):
        return None, err
    if ctx.user is None:
        return None, "restoring needs a signed-in caller"

    plan: dict = {"restore": [], "skipped": [], "notTrashed": []}
    seen: set = set()
    for ref in _refs(args):
        eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", ref)
        entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
        if entry is None or entry.group_id != ctx.group_id:
            plan["skipped"].append({"entry": ref, "reason": "not found in this workspace"})
            continue
        if entry.id in seen:
            continue
        seen.add(entry.id)
        if entry.status != TRASHED:
            plan["notTrashed"].append({**_row(entry), "status": entry.status})
            continue
        try:  # the entry page's rule for the status it goes back to (e.g. an AUTHOR restoring to Approved)
            require_can_edit_entry(ctx.user, ctx.group_id, entry, restore_status(entry))
        except HTTPException as e:
            plan["skipped"].append({**_row(entry), "entry": ref, "reason": str(e.detail)})
            continue
        plan["restore"].append(entry)
    plan["items"], item_skips, not_trashed = _plan_items(ctx, args, in_trash=True)
    plan["skipped"] += item_skips
    plan["notTrashed"] += not_trashed
    return plan, None


@register_tool(
    name="restore_entries",
    description=(
        "Take entries, assets or resources out of the Trash — the Trash's Restore. Use this when the user asks to "
        "restore, undelete, bring back or undo deleting them. Each entry goes back to the status it had before it was "
        "trashed, except that a previously published entry comes back as a draft (restoring never puts an entry on "
        "the site; tell the user to publish it again if they want it live). An asset or resource comes back as it "
        "was, with its links to entries. Up to 50 per call in total: `entries` by slug, id or exact title, `assets` "
        "by id, slug or filename, `resources` by id, slug or name. Items not in the Trash are reported as such; "
        "entries you may not change are skipped and reported."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_TRASH_BATCH,
                "description": "the trashed entries to restore, by slug or id",
            },
            **_items_schema("restore from the Trash"),
        },
    },
    min_role=ROLE_EDITOR,
    read_only=False,
)
def restore_entries(ctx: ToolContext, args: dict) -> str:
    from marvin.services.entries import EntryService
    from marvin.services.ui_links import entry_edit_url

    plan, err = _restore_plan(ctx, args)
    if err:
        return json.dumps({"error": err})

    svc = EntryService(ctx.session, ctx.group_id, actor_id=getattr(ctx.user, "id", None))
    restored, skipped = [], list(plan["skipped"])
    for entry in plan["restore"]:
        row = _row(entry)
        try:
            done = svc.restore_from_trash(entry.id)
        except Exception as e:  # noqa: BLE001 — one entry failing must not lose the others' results
            ctx.session.rollback()
            skipped.append({**row, "reason": str(getattr(e, "detail", e))})
            continue
        restored.append({**row, "status": getattr(done, "status", None), "editUrl": entry_edit_url(entry.id)})
    items, failed = _move_items(ctx, plan["items"], restore=True)
    named_items = any(_item_refs(args, key) for key in ITEM_ARGS)
    return json.dumps(
        {
            "restored": restored,
            **({"restoredAssets": items["assets"], "restoredResources": items["resources"]} if named_items else {}),
            "skipped": skipped + failed,
            "notTrashed": plan["notTrashed"],
        }
    )
