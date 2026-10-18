"""Entry snapshots — capture a version of an entry, and put it back.

A snapshot is what an entry looked like: title, summary, description, data, metadata, status, its (non-smart) collections
and its attached assets (references to the asset rows — never the files). The entry's event history says what happened;
there was no store of what it looked like, so this is one small table (`entry_snapshots`), used by a workflow's `snapshot`
step and the entries API (`/entries/{id}/snapshots`).

Restoring puts back **parts** of it, through EntryService, so the normal events fire (`entry_updated`, the collection and
asset-link events; a status change also its transition event) at the caller's reaction depth:

* `content` — title, summary, description, data, metadata. Metadata comes back whole, except the Trash record, which belongs
  to the entry's present state.
* `collections` — added to the ones it was in, removed from the ones it wasn't. A smart collection decides its own members
  and is left alone.
* `assets` — the links it had are made again (in their role), the ones added since are detached; an asset that has since
  been trashed or deleted is reported as `missing`. A pending AI suggestion is neither captured nor touched.
* `status` — **opt-in**: restoring content must not put an entry on the site, or take it off, by itself (as restoring from the
  Trash never publishes). Asked for, it goes through the publish gate like any other status change, and never moves an entry
  into or out of the Trash.

Retention: an entry keeps its latest `MAX_PER_ENTRY` snapshots; capturing past that drops the oldest. Capturing an entry whose
latest snapshot is already identical reuses it instead of adding a copy, so a run repeated for the same entry adds nothing.
Tags and resource links are not captured.
"""

from __future__ import annotations

import uuid
from typing import Any

from marvin.db.models.platform.entry_snapshots import EntrySnapshotModel

MAX_PER_ENTRY = 20
LABEL_MAX = 100
PARTS = ("content", "collections", "assets", "status")
DEFAULT_PARTS = ("content", "collections", "assets")
CONTENT_FIELDS = ("title", "summary", "description")
RESTORE_SENDS = (
    "entry_updated",
    "entry_added_to_collection",
    "entry_removed_from_collection",
    "asset_attached_to_entry",
    "asset_detached_from_entry",
)
"""What a restore may send (a status part adds the transition: entry_published, entry_unpublished, …)."""
_PREVIEW_CHARS = 200
_TRASH_KEY = "trash"
_TRASHED = "trashed"


class SnapshotError(ValueError):
    """The snapshot can't be taken or put back (the message says why, in words a workflow's run page can show)."""


def clean_label(value: Any) -> str:
    text = " ".join(str(value).split()) if value not in (None, "") else ""
    if len(text) > LABEL_MAX:
        raise SnapshotError(f"label is longer than {LABEL_MAX} characters")
    return text


def clean_parts(value: Any) -> tuple[str, ...]:
    """The parts a restore means: a list of names (or one), `DEFAULT_PARTS` when none are given."""
    if value in (None, "", []):
        return DEFAULT_PARTS
    names = [value] if isinstance(value, str) else list(value)
    bad = sorted({str(n) for n in names} - set(PARTS))
    if bad:
        raise SnapshotError(f"unknown part {', '.join(bad)}: a restore takes {', '.join(PARTS)}")
    return tuple(p for p in PARTS if p in names)


def _entry(session, group_id, entry_id):
    from marvin.db.models.platform.entries import Entries

    try:
        eid = entry_id if isinstance(entry_id, uuid.UUID) else uuid.UUID(str(entry_id))
    except ValueError:
        return None
    entry = session.get(Entries, eid)
    return entry if entry is not None and entry.group_id == group_id else None


def _meta(entry) -> dict:
    meta = entry.metadata_json if isinstance(entry.metadata_json, dict) else {}
    return {k: v for k, v in meta.items() if k != _TRASH_KEY}


def take(session, entry) -> dict:
    """What `entry` is now, as a snapshot holds it."""
    from marvin.db.models.platform.collections import Collections
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_collections import EntryCollections

    collections = (
        session.query(Collections)
        .join(EntryCollections, EntryCollections.collection_id == Collections.id)
        .filter(EntryCollections.entry_id == entry.id, Collections.is_smart.is_(False))
        .order_by(Collections.slug)
        .all()
    )
    links = session.query(EntryAssets).filter(EntryAssets.entry_id == entry.id).order_by(EntryAssets.position).all()
    return {
        "version": 1,
        "entry_type": entry.entry_type.slug if entry.entry_type else None,
        "title": entry.title,
        "summary": entry.summary,
        "description": entry.description,
        "data": dict(entry.data_json or {}),
        "metadata": _meta(entry),
        "status": entry.status,
        "collections": [{"id": str(c.id), "slug": c.slug, "name": c.name} for c in collections],
        "assets": [
            {"asset_id": str(link.asset_id), "slug": link.asset.slug, "name": link.asset.name, "role": link.role, "position": link.position}
            for link in links
            if link.asset is not None and not (link.metadata_json or {}).get("suggested")
        ],
    }


def capture(
    session, group_id, entry_id, *, label=None, user_id=None, automation_id=None, source: str = "workflow"
) -> tuple[EntrySnapshotModel, bool]:
    """Keep a snapshot of the entry. Returns (row, created): `created` is False when the entry's latest snapshot is already
    this very content (that one is returned). Prunes the entry's oldest past `MAX_PER_ENTRY`."""
    entry = _entry(session, group_id, entry_id)
    if entry is None:
        raise SnapshotError("no such entry in this workspace")
    content = take(session, entry)
    newest = latest(session, group_id, entry.id)
    if newest is not None and newest.snapshot_json == content:
        return newest, False
    row = EntrySnapshotModel(
        session=session, group_id=group_id, entry_id=entry.id, label=clean_label(label), source=source, snapshot_json=content,
        created_by=user_id, automation_id=automation_id,
    )  # fmt: skip
    session.add(row)
    session.flush()
    prune(session, group_id, entry.id)
    session.commit()
    return row, True


def prune(session, group_id, entry_id) -> int:
    """Drop the entry's oldest snapshots beyond the cap; how many went."""
    keep = [r.id for r in _query(session, group_id, entry_id).limit(MAX_PER_ENTRY)]
    if not keep:
        return 0
    return (
        session.query(EntrySnapshotModel)
        .filter(EntrySnapshotModel.group_id == group_id, EntrySnapshotModel.entry_id == entry_id, EntrySnapshotModel.id.notin_(keep))
        .delete(synchronize_session=False)
    )


def _query(session, group_id, entry_id):
    return (
        session.query(EntrySnapshotModel)
        .filter(EntrySnapshotModel.group_id == group_id, EntrySnapshotModel.entry_id == entry_id)
        .order_by(EntrySnapshotModel.created_at.desc(), EntrySnapshotModel.id.desc())
    )


def list_for(session, group_id, entry_id) -> list[EntrySnapshotModel]:
    return _query(session, group_id, entry_id).all()


def latest(session, group_id, entry_id, label: str | None = None) -> EntrySnapshotModel | None:
    query = _query(session, group_id, entry_id)
    if label:
        query = query.filter(EntrySnapshotModel.label == label)
    return query.first()


def get(session, group_id, snapshot_id, entry_id=None) -> EntrySnapshotModel | None:
    """A snapshot of this workspace by id (of that entry, when `entry_id` is given); None for any other."""
    try:
        sid = snapshot_id if isinstance(snapshot_id, uuid.UUID) else uuid.UUID(str(snapshot_id))
    except ValueError:
        return None
    row = session.get(EntrySnapshotModel, sid)
    if row is None or row.group_id != group_id or (entry_id is not None and str(row.entry_id) != str(entry_id)):
        return None
    return row


def remove(session, group_id, entry_id, snapshot_id) -> bool:
    row = get(session, group_id, snapshot_id, entry_id)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def describe(row: EntrySnapshotModel) -> dict:
    """A snapshot in brief: when, who, and what it holds (counts — the content itself stays out of listings)."""
    snap = row.snapshot_json or {}
    return {
        "id": str(row.id),
        "entry_id": str(row.entry_id),
        "label": row.label,
        "source": row.source,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "title": snap.get("title"),
        "status": snap.get("status"),
        "fields": len(snap.get("data") or {}),
        "collections": [c["slug"] for c in snap.get("collections") or []],
        "assets": len(snap.get("assets") or []),
    }


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _PREVIEW_CHARS:
        return value[:_PREVIEW_CHARS] + "…"
    if isinstance(value, dict | list):
        text = str(value)
        return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS] + "…"
    return value


def plan(session, group_id, row: EntrySnapshotModel, parts: tuple[str, ...] = DEFAULT_PARTS) -> dict:
    """What restoring `row` onto its entry would change, by part — nothing is written. `changed` says whether anything would."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.collections import Collections

    entry = _entry(session, group_id, row.entry_id)
    if entry is None:
        raise SnapshotError("the entry is gone")
    snap, now = row.snapshot_json or {}, take(session, entry)
    out: dict = {"snapshot_id": str(row.id), "entry_id": str(entry.id), "parts": list(parts), "changed": False}
    if "content" in parts:
        changes: dict = {}
        for key in (*CONTENT_FIELDS, "data", "metadata"):
            if snap.get(key) != now.get(key):
                changes[key] = {"before": _clip(now.get(key)), "after": _clip(snap.get(key))}
        out["content"] = changes
    if "status" in parts:
        before, after = now["status"], snap.get("status")
        out["status"] = {"before": before, "after": after, "changes": before != after}
    if "collections" in parts:
        have, want = {c["slug"]: c for c in now["collections"]}, {c["slug"]: c for c in snap.get("collections") or []}
        found = {c.slug for c in session.query(Collections).filter(Collections.group_id == group_id, Collections.slug.in_(list(want)))}
        out["collections"] = {
            "add": sorted(s for s in want if s not in have and s in found),
            "remove": sorted(s for s in have if s not in want),
            "missing": sorted(s for s in want if s not in have and s not in found),
        }
    if "assets" in parts:
        have, want = {a["asset_id"]: a for a in now["assets"]}, {a["asset_id"]: a for a in snap.get("assets") or []}
        usable = {
            str(a.id)
            for a in session.query(Assets).filter(
                Assets.group_id == group_id, Assets.trashed_at.is_(None), Assets.id.in_([uuid.UUID(i) for i in want])
            )
        }
        out["assets"] = {
            "attach": sorted(want[i]["slug"] for i in want if i not in have and i in usable),
            "detach": sorted(have[i]["slug"] for i in have if i not in want),
            "missing": sorted(want[i]["slug"] for i in want if i not in have and i not in usable),
        }
        out["_asset_ids"] = {"attach": [i for i in want if i not in have and i in usable], "detach": [i for i in have if i not in want]}
        out["_roles"] = {i: want[i]["role"] for i in want if i in have and have[i]["role"] != want[i]["role"]}
    out["changed"] = _changed(out)
    return out


def _changed(out: dict) -> bool:
    return bool(
        out.get("content")
        or (out.get("status") or {}).get("changes")
        or any(out.get("collections", {}).get(k) for k in ("add", "remove"))
        or any(out.get("assets", {}).get(k) for k in ("attach", "detach"))
        or out.get("_roles")
    )


def public(out: dict) -> dict:
    """The plan without its working keys."""
    return {k: v for k, v in out.items() if not k.startswith("_")}


def restore(
    session,
    group_id,
    row: EntrySnapshotModel,
    parts: tuple[str, ...] = DEFAULT_PARTS,
    *,
    actor_id=None,
    depth: int = 0,
    integration_id="entry_management",
) -> dict:
    """Put `parts` of the snapshot back on its entry (through EntryService, so the normal events go out at `depth`).
    Returns the plan it carried out; a restore that would change nothing writes nothing."""
    from fastapi import HTTPException

    from marvin.services.entries import EntryService

    entry = _entry(session, group_id, row.entry_id)
    if entry is None:
        raise SnapshotError("the entry is gone")
    if entry.status == _TRASHED:
        raise SnapshotError("the entry is in the Trash: restore it from there first")
    snap = row.snapshot_json or {}
    if "status" in parts and _TRASHED in (snap.get("status"), entry.status):
        raise SnapshotError("a restore doesn't move an entry into or out of the Trash")
    done = plan(session, group_id, row, parts)
    if not done["changed"]:
        return {**public(done), "restored": False}
    svc = EntryService(session, group_id, actor_id=actor_id, integration_id=integration_id)
    update: dict = {}
    if "content" in parts and done["content"]:
        for key in CONTENT_FIELDS:
            if key in done["content"]:
                update[key] = snap.get(key)
        if "data" in done["content"]:
            update["data_json"] = dict(snap.get("data") or {})
        if "metadata" in done["content"]:
            kept = {k: v for k, v in (entry.metadata_json or {}).items() if k == _TRASH_KEY}
            update["metadata_json"] = {**dict(snap.get("metadata") or {}), **kept}
    if "status" in parts and done["status"]["changes"]:
        update["status"] = snap.get("status")
    try:
        if update:
            svc.update(entry.id, update, reaction_depth=depth)
        if "collections" in parts:
            for slug in done["collections"]["remove"]:
                svc.remove_from_collection(entry.id, slug, reaction_depth=depth)
            for slug in done["collections"]["add"]:
                svc.add_to_collection(entry.id, slug, reaction_depth=depth)
        if "assets" in parts:
            for asset_id in done["_asset_ids"]["detach"]:
                svc.detach_asset(entry.id, asset_id, reaction_depth=depth)
            roles = {a["asset_id"]: a["role"] for a in snap.get("assets") or []}
            for asset_id in done["_asset_ids"]["attach"]:
                svc.attach_asset(entry.id, asset_id, role=roles.get(asset_id), reaction_depth=depth)
            _set_roles(session, entry.id, done["_roles"])
    except HTTPException as e:  # the type's schema or the publish gate refused what the snapshot holds
        session.rollback()
        detail = e.detail if isinstance(e.detail, dict) else {}
        raise SnapshotError("; ".join(detail.get("issues") or []) or str(detail.get("message") or e.detail)) from e
    return {**public(done), "restored": True}


def _set_roles(session, entry_id, roles: dict) -> None:
    from marvin.db.models.platform.entry_assets import EntryAssets

    for asset_id, role in roles.items():
        session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id, EntryAssets.asset_id == uuid.UUID(asset_id)).update({"role": role})
    if roles:
        session.commit()
