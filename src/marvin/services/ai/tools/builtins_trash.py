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

"All of them" / "everything that matches": the named lists hold at most 50 refs, and a model told to delete
every asset once passed `assets: ["*"]`. So both tools also take `match` — one kind, and either `all: true` or
a `query` in the vocabulary that kind's lists already speak (services/entries/query.py for entries,
services/item_query.py for assets and resources) — resolved here, at most MAX_MATCH per call, the rest
reported for another call. A call with a `match` always asks first (the card says how many, names a sample,
and that it is the Trash, not deleting forever); where the run can't pause to ask it is refused with the
count. A wildcard in a named list ("*", "all", "everything", …) that names no real item is refused with an
error pointing at `match` — never read as a name, never widened to everything without the card.
"""

import json
import re
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
# Most items one `match` selects in one call; the rest are reported (`remaining`) for the next call, which
# finds them because what this one moved no longer matches.
MAX_MATCH = 500
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
# `match.kind` → the kind of thing it selects.
MATCH_KINDS = {"entries": "entry", **ITEM_ARGS}
# A ref that means "all of them" rather than naming one (when nothing is actually called that).
_WILDCARD = re.compile(
    r"^(\*|\*\.\*|%|all|any|every|everything|all of them|(all|every) (entries|entry|assets|asset|resources|resource|items|files|images))$",
    re.IGNORECASE,
)

_ITEM_ARG_SCHEMA = {
    "assets": "assets, by id, slug, or filename/name when only one asset has it",
    "resources": "resources, by id, slug, or name when only one resource has it",
}


def _item_refs(args: dict, key: str) -> list[str]:
    return _refs({"entries": args.get(key)})


def _named(args: dict, key: str) -> list[str]:
    return _refs(args) if key == "entries" else _item_refs(args, key)


def _total(args: dict) -> int:
    return sum(len(_named(args, key)) for key in MATCH_KINDS)


def _plural(n: int, word: str) -> str:
    plural = f"{word[:-1]}ies" if word.endswith("y") else f"{word}s"
    return f"{n} {word if n == 1 else plural}"


# ── match: "all of them" / "everything that matches" ─────────────────────────


@dataclass
class _Match:
    """One call's `match`, and what it selected."""

    key: str  # "entries" | "assets" | "resources"
    every: bool
    query: dict
    rows: list = field(default_factory=list)  # at most MAX_MATCH
    total: int = 0
    note: str | None = None

    @property
    def kind(self) -> str:
        return MATCH_KINDS[self.key]

    @property
    def remaining(self) -> int:
        return max(0, self.total - len(self.rows))

    def describe(self, *, restore: bool) -> str:
        if self.every:
            return f"every {self.kind} {'in the Trash' if restore else 'in this workspace'}"
        terms = ", ".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in self.query.items())
        return f"{self.key} matching {terms[:160]}"

    def report(self, tool: str) -> dict:
        out = {"kind": self.key, "selection": "all" if self.every else self.query, "total": self.total, "selected": len(self.rows)}
        out["remaining"] = self.remaining
        if self.note:
            out["note"] = self.note
        if self.remaining:
            out["next"] = f"{self.remaining} more match: call {tool} again with the same match to continue (the user is asked again for each call)."
        return out


def _parse_match(args: dict, *, restore: bool) -> tuple[_Match | None, str | None]:
    """The call's `match`, checked; never one that could select more than it says."""
    from marvin.services import item_query
    from marvin.services.automation.matcher import as_bool
    from marvin.services.entries.query import SPEC_KEYS, _as_list

    raw = args.get("match")
    if raw is None or raw == {}:
        return None, None
    if not isinstance(raw, dict):
        return None, 'match is one object: {"kind": "entries"|"assets"|"resources", "all": true} or {"kind": …, "query": {…}}'
    key = str(raw.get("kind") or "").strip().lower()
    key = {"entry": "entries", "asset": "assets", "resource": "resources"}.get(key, key)
    if key not in MATCH_KINDS:
        return None, "match.kind is one of entries, assets, resources (one kind per call)"
    query = raw.get("query") or {}
    if not isinstance(query, dict):
        return None, 'match.query is an object of filters, e.g. {"asset_type": "image", "unattached": true}'
    every = as_bool(str(raw.get("all"))) is True
    if every and query:
        return None, "match takes all: true (every one) or a query (some of them), not both"
    if not every and not query:
        return None, f'match needs all: true to select every {MATCH_KINDS[key]}, or a query to select some — an empty query never means "all"'
    known = SPEC_KEYS if key == "entries" else item_query.KEYS[MATCH_KINDS[key]]
    if unknown := sorted(k for k in query if k not in known):
        # Ignoring a filter would widen the selection: refuse instead.
        return None, f"match.query for {key} does not understand {', '.join(unknown)}; it takes {', '.join(known)}"
    if restore and key == "entries" and any(s != TRASHED for s in _as_list(query.get("status")) + _as_list(query.get("statuses"))):
        return None, "everything in the Trash has the status 'trashed': filter trashed entries by type, title, tags, collection or dates instead"
    return _Match(key=key, every=every, query=dict(query)), None


def _select(ctx: ToolContext, m: _Match, *, restore: bool) -> None:
    """Resolve the match: not trashed (to trash) or trashed (to restore), at most MAX_MATCH, plus the true total."""
    if m.key == "entries":
        from marvin.services.entries.query import run

        query = {k: v for k, v in m.query.items() if k not in ("status", "statuses")} if restore else m.query
        result = run(ctx.session, ctx.group_id, {**query, "statuses": [TRASHED]} if restore else query, limit=MAX_MATCH)
        m.rows, m.total, m.note = result.rows, result.total, result.note
        if result.scan_capped:
            m.note = "matched more entries than can be compared in one pass; narrow the query"
        return
    from marvin.services import item_query

    result = item_query.run(ctx.session, ctx.group_id, m.kind, m.query, trashed=restore, limit=MAX_MATCH)
    m.rows, m.total, m.note = result.rows, result.total, result.note


def _exists(ctx: ToolContext, kind: str, ref: str) -> bool:
    if kind == "entry":
        return isinstance(resolve_entity_id(ctx.session, ctx.group_id, "entry", ref), _uuid.UUID)
    return _resolve_item(ctx, kind, ref) is not None


def _wildcard_error(ctx: ToolContext, args: dict, tool: str) -> str | None:
    """A wildcard in a named list ("*", "all", …) is not a name: say to use `match` instead."""
    for key, kind in MATCH_KINDS.items():
        for ref in _named(args, key):
            if _WILDCARD.match(ref) and not _exists(ctx, kind, ref):
                return (
                    f"{ref!r} is not {'an' if kind[0] in 'aeiou' else 'a'} {kind}: `{key}` takes names, never wildcards. "
                    f'To select every {kind}, call {tool} with match: {{"kind": "{key}", "all": true}}; to select some, '
                    f'match: {{"kind": "{key}", "query": {{…}}}}. The user is asked to approve a match first.'
                )
    return None


def _call_error(ctx: ToolContext, args: dict, *, restore: bool) -> tuple[_Match | None, str | None]:
    """(the call's match, resolved, or None; None) or (None, why the call can't run at all)."""
    tool, verb = ("restore_entries", "restore") if restore else ("trash_entries", "trash")
    m, err = _parse_match(args, restore=restore)
    if err:
        return None, err
    n = _total(args)
    if not n and m is None:
        return None, (
            "name at least one entry (slug or id) in `entries`, or assets / resources in `assets` / `resources` — or "
            'select them with match (e.g. {"kind": "assets", "all": true})'
        )
    if n > MAX_TRASH_BATCH:
        return None, (
            f"at most {MAX_TRASH_BATCH} entries, assets and resources per call ({n} given) — {verb} them in smaller "
            "batches, or select them with match"
        )
    if err := _wildcard_error(ctx, args, tool):
        return None, err
    if ctx.user is None:
        return None, f"{'restoring' if restore else 'trashing'} needs a signed-in caller"
    if m is not None:
        _select(ctx, m, restore=restore)
    return m, None


# ── Planning: what one call would do, worked out without writing ──────────────


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


@dataclass
class _Plan:
    """What one call would do, worked out without writing."""

    entries: list = field(default_factory=list)  # Entries rows to move
    items: list = field(default_factory=list)  # (kind, row) assets and resources to move
    skipped: list[dict] = field(default_factory=list)  # {entry, reason} (or {asset|resource, reason})
    already: list[dict] = field(default_factory=list)  # already where the move would put them: {id, title} or an item row
    match: _Match | None = None

    @property
    def count(self) -> int:
        return len(self.entries) + len(self.items)

    @property
    def published(self) -> list:
        return [e for e in self.entries if e.status == "published"]

    def on_site(self, session) -> list:
        """The assets and resources to move that a site shows."""
        from marvin.services.publish_visibility import item_visible_to_sites

        return [(kind, row) for kind, row in self.items if item_visible_to_sites(session, kind, row)]


def _plan_entries(ctx: ToolContext, args: dict, plan: _Plan, *, restore: bool) -> None:
    """Sort every named or matched entry into the plan, with the entry page's rule for the status it would get."""
    from marvin.db.models.platform.entries import Entries
    from marvin.routes._base.checks import require_can_edit_entry
    from marvin.services.entries.entry_service import restore_status

    candidates = []
    for ref in _refs(args):
        eid = resolve_entity_id(ctx.session, ctx.group_id, "entry", ref)
        entry = ctx.session.get(Entries, eid) if isinstance(eid, _uuid.UUID) else None
        candidates.append((ref, entry if entry is not None and entry.group_id == ctx.group_id else None))
    if plan.match is not None and plan.match.key == "entries":
        candidates += [(e.slug, e) for e in plan.match.rows]

    seen: set = set()
    for ref, entry in candidates:
        if entry is None:
            plan.skipped.append({"entry": ref, "reason": "not found in this workspace"})
            continue
        if entry.id in seen:
            continue
        seen.add(entry.id)
        if (entry.status == TRASHED) != restore:
            plan.already.append({**_row(entry), "status": entry.status} if restore else _row(entry))
            continue
        try:  # the entry page's rule for the status it gets (e.g. an AUTHOR restoring to Approved)
            require_can_edit_entry(ctx.user, ctx.group_id, entry, restore_status(entry) if restore else TRASHED)
        except HTTPException as e:
            plan.skipped.append({**_row(entry), "entry": ref, "reason": str(e.detail)})
            continue
        plan.entries.append(entry)


def _plan_items(ctx: ToolContext, args: dict, plan: _Plan, *, restore: bool) -> None:
    """Sort every named or matched asset/resource into the plan. ``restore``: they must be in the Trash to move."""
    from marvin.services import trash

    seen: set = set()
    for key, kind in ITEM_ARGS.items():
        candidates = [(ref, _resolve_item(ctx, kind, ref)) for ref in _item_refs(args, key)]
        if plan.match is not None and plan.match.key == key:
            candidates += [(row.slug, row) for row in plan.match.rows]
        for ref, row in candidates:
            if row is None:
                plan.skipped.append({kind: ref, "reason": "not found in this workspace (or the name matches more than one)"})
                continue
            if row.id in seen:
                continue
            seen.add(row.id)
            if trash.is_trashed(row) != restore:
                plan.already.append(_item_row(kind, row))
                continue
            plan.items.append((kind, row))


def _plan(ctx: ToolContext, args: dict, *, restore: bool = False) -> tuple[_Plan | None, str | None]:
    """(plan, None), or (None, error) for a call that can't run at all."""
    m, err = _call_error(ctx, args, restore=restore)
    if err:
        return None, err
    plan = _Plan(match=m)
    _plan_entries(ctx, args, plan, restore=restore)
    _plan_items(ctx, args, plan, restore=restore)
    return plan, None


# ── Ask first ─────────────────────────────────────────────────────────────────


def _match_ask(ctx: ToolContext, plan: _Plan, *, restore: bool) -> AskFirst:
    """The card for a call with a `match`: how many, which (a sample), that it is the Trash — and the refusal."""
    m = plan.match
    tool = "restore_entries" if restore else "trash_entries"
    kinds = ({"entry"} if plan.entries else set()) | {kind for kind, _ in plan.items}
    noun = next(iter(kinds)) if len(kinds) == 1 else "item"
    live = [] if restore else plan.published
    shown_ids = set() if restore else {row.id for _, row in plan.on_site(ctx.session)}
    k = len(live) + len(shown_ids)
    n = plan.count
    if restore:
        summary = (
            f"Restore {_plural(n, noun)} from the Trash ({m.describe(restore=True)}). Each goes back where it was; "
            "a previously published entry comes back as a draft"
        )
    else:
        summary = f"Move {_plural(n, noun)} to the Trash ({m.describe(restore=False)})"
        if k:
            summary += f" — {k} {'is' if k == 1 else 'are'} on the site and will come off it"
        summary += ". They can be restored from the Trash; nothing is deleted forever"
    if m.remaining:
        summary += f". {m.remaining} more match and are left for another call"

    def tag(name: str, kind: str, on_site: bool) -> str:
        notes = ([kind] if noun == "item" else []) + (["on the site"] if on_site else [])
        return f"{name} ({', '.join(notes)})" if notes else name

    targets = [tag(e.title, "entry", e.status == "published" and not restore) for e in plan.entries]
    targets += [tag(row.name, kind, row.id in shown_ids) for kind, row in plan.items]
    preview = {
        "summary": summary,
        "action": "restore" if restore else "trash",
        "links": n,
        "targetType": noun,
        "targetCount": n,
        "targets": targets[:PREVIEW_MAX_TARGETS],
        "itemKind": "",
        "items": [],
    }
    refusal = json.dumps(
        {
            "error": (
                f"Not done: {summary}. A call with `match` always needs the user's approval, and this run cannot pause "
                "to ask. Tell the user how many match and ask them to do it where they can approve it (the Ask page or "
                "an agent conversation). Do not work around this by naming the items in batches."
            ),
            "matched": m.report(tool),
            "wouldMove": n,
        }
    )
    return AskFirst(preview=preview, refusal=refusal)


def _ask_first(ctx: ToolContext, args: dict) -> AskFirst | None:
    """Ask before a call with a `match`, or one that would take something off the site — a published entry, or an
    asset or resource a site shows; None for everything else."""
    plan, err = _plan(ctx, args)
    if err:
        return None
    if plan.match is not None and plan.count:
        return _match_ask(ctx, plan, restore=False)
    live, shown = plan.published, plan.on_site(ctx.session)
    if not live and not shown:
        return None
    if not plan.items:  # entries only: the wording the entry tools have always used
        n, k = len(plan.entries), len(live)
        summary = f"Move {n} {'entry' if n == 1 else 'entries'} to the Trash — {k} {'is' if k == 1 else 'are'} published and will come off the site"
    else:
        n, k = plan.count, len(live) + len(shown)
        summary = f"Move {n} {'item' if n == 1 else 'items'} to the Trash — {k} {'is' if k == 1 else 'are'} on the site and will come off it"
    shown_ids = {row.id for _, row in shown}
    targets = [f"{e.title} (published)" if e.status == "published" else e.title for e in plan.entries]
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


def _restore_ask_first(ctx: ToolContext, args: dict) -> AskFirst | None:
    """Ask before a restore with a `match`; a restore of named items runs as it always has."""
    plan, err = _plan(ctx, args, restore=True)
    if err or plan.match is None or not plan.count:
        return None
    return _match_ask(ctx, plan, restore=True)


# ── The tools ─────────────────────────────────────────────────────────────────


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


def _match_schema(restore: bool) -> dict:
    where = "in the Trash" if restore else "not in the Trash"
    return {
        "type": "object",
        "description": (
            f"select {'trashed items to restore' if restore else 'what to move to the Trash'} instead of naming them, for "
            f"'all X' or 'every X that …' — one kind per call, at most {MAX_MATCH} (the result says how many remain). "
            "Always asks the user first. Never put '*' or 'all' in the named lists: use this"
        ),
        "properties": {
            "kind": {"type": "string", "enum": list(MATCH_KINDS)},
            "all": {"type": "boolean", "description": f"true: every one of that kind {where} in this workspace"},
            "query": {
                "type": "object",
                "description": (
                    "only those matching — entries: find_entries' filters (entry_types, statuses, text, tags, collection, "
                    "fields, where, created_after/before, …); assets: asset_type(s), mime_type(s), query (name/filename "
                    "substring), tags, collection, unattached (true: attached to no entry), created_after/before; "
                    "resources: resource_type(s), query, tags, collection, unattached, created_after/before"
                ),
            },
        },
        "required": ["kind"],
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


def _with_items(args: dict, plan: _Plan) -> bool:
    """Whether the answer carries the asset/resource lists: assets or resources were named or matched."""
    return any(_item_refs(args, key) for key in ITEM_ARGS) or (plan.match is not None and plan.match.key in ITEM_ARGS)


@register_tool(
    name="trash_entries",
    description=(
        "Move entries, assets or resources to the Trash — what Delete does in Marvin. Use this whenever the user asks "
        "to delete, remove, clear out or get rid of entries (e.g. test or spam entries), assets (images, files) or "
        "resources. Trashed items leave the site, the publishing API and every listing, and can be restored from the "
        "Trash until a person empties it (an asset's file is kept until then). Name up to 50 per call in total: "
        "`entries` by slug or id, `assets` by id, slug or filename, `resources` by id, slug or name, plus an optional "
        f"short reason. For 'delete all X' or 'everything that matches Y' use `match` instead of names (up to {MAX_MATCH} "
        "per call, the result says how many remain): it always asks the user first. Trashing a published entry, or an "
        "asset or resource the site shows, asks the user first too. Items you may not change are skipped and "
        "reported. You cannot empty the Trash or delete anything forever: tell the user the items are in the Trash "
        "and how to restore them (the result's `undo`), and give them the result's trashLink verbatim. To retire an "
        "entry that should be kept, use archive_entries instead."
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
            "match": _match_schema(restore=False),
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
    for entry in plan.entries:
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
    with_items = _with_items(args, plan)
    return json.dumps(
        {
            "trashed": trashed,
            **({"trashedAssets": items["assets"], "trashedResources": items["resources"]} if with_items else {}),
            "skipped": skipped,
            "alreadyTrashed": plan.already,
            **({"matched": plan.match.report("trash_entries")} if plan.match is not None else {}),
            **({"reason": reason} if reason else {}),
            "undo": f"{UNDO_HINT} {ITEMS_UNDO_HINT}" if with_items else UNDO_HINT,
            # A finished markdown link, like revise_entry's reviewLink: models copy strings, they guess hosts.
            **({"trashLink": f"[Open the Trash]({ui_link(f'/workspace/collections/{trash[0]}')})"} if trash else {}),
        }
    )


@register_tool(
    name="restore_entries",
    description=(
        "Take entries, assets or resources out of the Trash — the Trash's Restore. Use this when the user asks to "
        "restore, undelete, bring back or undo deleting them. Each entry goes back to the status it had before it was "
        "trashed, except that a previously published entry comes back as a draft (restoring never puts an entry on "
        "the site; tell the user to publish it again if they want it live). An asset or resource comes back as it "
        "was, with its links to entries. Name up to 50 per call in total: `entries` by slug, id or exact title, "
        "`assets` by id, slug or filename, `resources` by id, slug or name. For 'restore all X' or 'everything in the "
        f"Trash that matches Y' use `match` instead of names (up to {MAX_MATCH} per call): it asks the user first. Items "
        "not in the Trash are reported as such; entries you may not change are skipped and reported."
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
            "match": _match_schema(restore=True),
        },
    },
    min_role=ROLE_EDITOR,
    read_only=False,
    ask_first=_restore_ask_first,
)
def restore_entries(ctx: ToolContext, args: dict) -> str:
    from marvin.services.entries import EntryService
    from marvin.services.ui_links import entry_edit_url

    plan, err = _plan(ctx, args, restore=True)
    if err:
        return json.dumps({"error": err})

    svc = EntryService(ctx.session, ctx.group_id, actor_id=getattr(ctx.user, "id", None))
    restored, skipped = [], list(plan.skipped)
    for entry in plan.entries:
        row = _row(entry)
        try:
            done = svc.restore_from_trash(entry.id)
        except Exception as e:  # noqa: BLE001 — one entry failing must not lose the others' results
            ctx.session.rollback()
            skipped.append({**row, "reason": str(getattr(e, "detail", e))})
            continue
        restored.append({**row, "status": getattr(done, "status", None), "editUrl": entry_edit_url(entry.id)})
    items, failed = _move_items(ctx, plan.items, restore=True)
    return json.dumps(
        {
            "restored": restored,
            **({"restoredAssets": items["assets"], "restoredResources": items["resources"]} if _with_items(args, plan) else {}),
            "skipped": skipped + failed,
            "notTrashed": plan.already,
            **({"matched": plan.match.report("restore_entries")} if plan.match is not None else {}),
        }
    )
