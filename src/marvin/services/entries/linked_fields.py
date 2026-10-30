"""A schema's asset and resource fields are a simple way to attach: what the field names is attached with the field's
key as its role.

An ``asset`` / ``asset-list`` field (``heroImage``, ``gallery``) holds asset ids in ``data_json``; a ``resource`` /
``resource-list`` field holds resource ids. The sidebar, the site renderer (a hero by role), the completeness contract and
the smart collections all read the entry's *attachments*, so a value that stayed only in ``data_json`` was invisible to
them. After every save the attachments are brought in line with the fields: each id named gets an attachment whose
role is the field's ``role`` (``hero``), or its key when none is set (kept if it is already there), and an attachment with
that role whose id the field no longer names is removed. Attachments with any other role, or none, are someone's own and are never touched.
"""

from __future__ import annotations

import uuid
from typing import Any

ASSET_TYPES = ("asset", "asset-list")
RESOURCE_TYPES = ("resource", "resource-list")


def linked_fields(schema_json: Any) -> list[tuple[str, str, str]]:
    """``(key, type, role)`` of the schema's asset and resource fields: the role is the field's ``role`` (``hero``), else its key."""
    fields = (schema_json or {}).get("fields") if isinstance(schema_json, dict) else None
    return [
        (f["key"], f["type"], str(f.get("role") or "").strip() or f["key"])
        for f in fields or []
        if isinstance(f, dict) and f.get("key") and f.get("type") in ASSET_TYPES + RESOURCE_TYPES
    ]


def ids_named(value: Any) -> list[uuid.UUID]:
    """The ids a field value names: one id, a list of them, or the comma-separated string an older form saved."""
    raw = value if isinstance(value, list) else str(value).split(",") if isinstance(value, str) else [value] if value else []
    out: list[uuid.UUID] = []
    for item in raw:
        try:
            out.append(uuid.UUID(str(item).strip()))
        except (ValueError, AttributeError):
            continue
    return out


def sync_linked_fields(session, entry, schema_json: Any) -> bool:
    """Bring the entry's attachments in line with its asset / resource fields (see the module docstring). Commits when
    anything changed; returns whether it did."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_resources import EntryResources
    from marvin.db.models.platform.resources import Resources

    fields = linked_fields(schema_json)
    if not fields:
        return False
    data = getattr(entry, "data_json", None) or {}
    changed = False
    for key, ftype, role in fields:
        wanted = ids_named(data.get(key))
        if ftype in ASSET_TYPES:
            changed |= _sync(session, entry, role, wanted, EntryAssets, "asset_id", Assets)
        else:
            changed |= _sync(session, entry, role, wanted, EntryResources, "resource_id", Resources)
    if changed:
        session.commit()
    return changed


def _sync(session, entry, role: str, wanted: list[uuid.UUID], link_model, fk: str, target_model) -> bool:
    import sqlalchemy as sa

    rows = session.query(link_model).filter(link_model.entry_id == entry.id).all()
    with_role = {getattr(r, fk): r for r in rows if r.role == role}
    linked_any = {getattr(r, fk) for r in rows}
    changed = False
    for row in with_role.values():
        if getattr(row, fk) not in wanted:
            session.delete(row)
            changed = True
    # Only ids that exist in this workspace and aren't in the Trash become attachments; a stale id is left in the field.
    valid = set()
    if wanted:
        q = session.query(target_model.id).filter(target_model.group_id == entry.group_id, target_model.id.in_(wanted))
        if hasattr(target_model, "trashed_at"):
            q = q.filter(target_model.trashed_at.is_(None))
        valid = {row.id for row in q}
    max_pos = session.query(sa.func.max(link_model.position)).filter(link_model.entry_id == entry.id).scalar()
    pos = (max_pos + 1) if max_pos is not None else 0
    for target_id in wanted:
        if target_id in with_role or target_id not in valid:
            continue
        if target_id in linked_any:  # attached by hand already: give that link the field's role rather than a second row
            row = next(r for r in rows if getattr(r, fk) == target_id)
            if row.role is None:
                row.role = role
                changed = True
            continue
        session.add(link_model(**{"entry_id": entry.id, fk: target_id, "role": role, "position": pos}))
        pos += 1
        changed = True
    return changed
