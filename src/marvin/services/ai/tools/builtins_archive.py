"""Built-in ARCHIVE tool — the agent's reversible "remove" for entries.

Asked to delete test inbox entries, an agent with no tool to remove anything once staged no-op
`revise_entry` suggestions ("Deleted test inbox entry.") on seven newsletter signups. Archive is
Marvin's reversible delete: an archived entry is off the site and the publishing API, sits in the
Archive collection, and comes back by setting its status again. Hard delete stays a human action.

`archive_entries` changes status through EntryService.set_status, the same path as a person picking
Archived on the entry page, so `entry_updated` / `entry_unpublished` / `entry_archived`, smart
collections, the site rebuild and the audit log behave identically. Each entry is checked with the
entry page's own rule (`require_can_edit_entry` with the new status) and the ones the caller may not
change are skipped and reported. min_role is EDITOR like every AI write tool (an AUTHOR archives their
own drafts on the entry page); the per-entry check still runs, so the tool never does more than the
entry page would let the caller do.

Archiving a published entry takes it off the site, so a call that would do that asks first
(`ask_first` → an approval card); drafts, inbox and review entries archive straight away.
"""

import json
import uuid as _uuid
from dataclasses import dataclass, field

from fastapi import HTTPException

from ..entity_resolve import resolve_entity_id
from ..operations.base import ROLE_EDITOR
from .base import ToolContext, register_tool
from .bulk_writes import PREVIEW_MAX_TARGETS, AskFirst

MAX_ARCHIVE_BATCH = 50
ARCHIVED = "archived"
UNDO_HINT = (
    "Nothing is deleted. Archived entries are off the site and the publishing API and are listed in the "
    "Archive collection (or Entries filtered by status Archived). To undo, open the entry and set its status "
    "back (for example to Draft); an entry that was published has to be published again."
)


@dataclass
class _Plan:
    """What one call would do, worked out without writing."""

    archive: list = field(default_factory=list)  # Entries rows to archive
    skipped: list[dict] = field(default_factory=list)  # {entry, reason}
    already: list[dict] = field(default_factory=list)  # {id, title}

    @property
    def published(self) -> list:
        return [e for e in self.archive if e.status == "published"]


def _refs(args: dict) -> list[str]:
    raw = args.get("entries")
    if isinstance(raw, str):
        raw = [raw]
    refs: list[str] = []
    for r in raw or []:
        r = str(r or "").strip()
        if r and r not in refs:
            refs.append(r)
    return refs


def _row(entry) -> dict:
    return {"id": str(entry.id), "title": entry.title}


def _plan(ctx: ToolContext, args: dict) -> tuple[_Plan | None, str | None]:
    """(plan, None), or (None, error) for a call that can't run at all."""
    from marvin.db.models.platform.entries import Entries
    from marvin.routes._base.checks import require_can_edit_entry

    refs = _refs(args)
    if not refs:
        return None, "name at least one entry (slug or id) in `entries`"
    if len(refs) > MAX_ARCHIVE_BATCH:
        return None, f"at most {MAX_ARCHIVE_BATCH} entries per call ({len(refs)} given) — archive them in smaller batches"
    if ctx.user is None:
        return None, "archiving needs a signed-in caller"

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
        if entry.status == ARCHIVED:
            plan.already.append(_row(entry))
            continue
        try:
            require_can_edit_entry(ctx.user, ctx.group_id, entry, ARCHIVED)
        except HTTPException as e:
            plan.skipped.append({**_row(entry), "entry": ref, "reason": str(e.detail)})
            continue
        plan.archive.append(entry)
    return plan, None


def _ask_first(ctx: ToolContext, args: dict) -> AskFirst | None:
    """Ask before a call that would archive a published entry; None for everything else."""
    plan, err = _plan(ctx, args)
    if err or not plan.published:
        return None
    live = plan.published
    n, k = len(plan.archive), len(live)
    summary = f"Archive {n} {'entry' if n == 1 else 'entries'} — {k} {'is' if k == 1 else 'are'} published and will come off the site"
    shown = plan.archive[:PREVIEW_MAX_TARGETS]
    preview = {
        "summary": summary,
        "action": "archive",
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
                f"Not done: {summary}. Archiving a published entry needs the user's approval and this run cannot "
                "pause to ask. Call archive_entries again without the published entries to archive the rest, and ask "
                "the user to archive the published ones themselves or to approve it in a conversation where they can."
            ),
            "published": [_row(e) for e in live],
        }
    )
    return AskFirst(preview=preview, refusal=refusal)


@register_tool(
    name="archive_entries",
    description=(
        "Archive entries — retire them while keeping them. Use this when the user asks to archive or retire "
        "entries; to delete or remove entries use trash_entries when you have it, and this only when you don't. "
        "Archived entries leave the site and the "
        "publishing API but are kept and can be restored. Up to 50 entries per call by slug or id, plus an "
        "optional short reason. Archiving a published entry asks the user first. Entries you may not change "
        "are skipped and reported. There is no hard delete: tell the user it is archived, not deleted, and "
        "how to undo it (the result's `undo`)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_ARCHIVE_BATCH,
                "description": "the entries to archive, by slug or id",
            },
            "reason": {"type": "string", "description": "optional short reason, e.g. 'test signups'"},
        },
        "required": ["entries"],
    },
    min_role=ROLE_EDITOR,
    read_only=False,
    ask_first=_ask_first,
)
def archive_entries(ctx: ToolContext, args: dict) -> str:
    from marvin.services.entries import EntryService
    from marvin.services.ui_links import entry_edit_url, ui_link

    plan, err = _plan(ctx, args)
    if err:
        return json.dumps({"error": err})

    svc = EntryService(ctx.session, ctx.group_id, actor_id=getattr(ctx.user, "id", None))
    archived, skipped = [], list(plan.skipped)
    for entry in plan.archive:
        was, row = entry.status, _row(entry)
        try:
            svc.set_status(entry.id, ARCHIVED)
        except Exception as e:  # noqa: BLE001 — one entry failing must not lose the others' results
            ctx.session.rollback()
            skipped.append({**row, "reason": str(getattr(e, "detail", e))})
            continue
        archived.append({**row, "was": was, "editUrl": entry_edit_url(entry.id)})

    reason = str(args.get("reason") or "").strip()[:200]
    return json.dumps(
        {
            "archived": archived,
            "skipped": skipped,
            "alreadyArchived": plan.already,
            **({"reason": reason} if reason else {}),
            "undo": UNDO_HINT,
            "archivedUrl": ui_link("/workspace/entries?status=archived"),
        }
    )
