"""A schema's asset and resource fields are a simple way to attach: what the field names is attached with the field's
key as its role.

An ``asset`` / ``asset-list`` field (``heroImage``, ``gallery``) holds asset ids in ``data_json``; a ``resource`` /
``resource-list`` field holds resource ids. The sidebar, the site renderer (a hero by role), the completeness contract and
the smart collections all read the entry's *attachments*, so a value that stayed only in ``data_json`` was invisible to
them. After every save the attachments are brought in line with the fields: each id named gets an attachment whose
role is the field's ``role`` (``hero``), or its key when none is set, and an attachment with that role whose id the field
*used to name* and no longer does is removed. Then the field is set from the attachments: it is exactly the ones in its
role, in their order (a list field all of them, a single field the first). So a picture given the field's role by hand in
the sidebar appears in the field, and one whose role was changed away in the sidebar leaves the field. An id chosen in
the field that is attached in another role takes the field's role; attachments with any other role, or none, are
someone's own and are never touched.
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


def sync_linked_fields(session, entry, schema_json: Any, previous_data: Any = None) -> bool:
    """Bring the entry's attachments in line with its asset / resource fields, then the fields in line with the
    attachments (see the module docstring). ``previous_data`` is the entry's ``data_json`` before this save: an id the
    field named then and not now is removed, an id it names now and didn't then takes over a link that had another role.
    Without it (a new entry) nothing is removed and every id named is new. Commits when anything changed; returns whether
    it did."""
    from marvin.db.models.platform.assets import Assets
    from marvin.db.models.platform.entry_assets import EntryAssets
    from marvin.db.models.platform.entry_resources import EntryResources
    from marvin.db.models.platform.resources import Resources

    fields = linked_fields(schema_json)
    if not fields:
        return False
    data = getattr(entry, "data_json", None) or {}
    before = previous_data if isinstance(previous_data, dict) else None
    changed = False
    new_data: dict[str, Any] = {}
    for key, ftype, role in fields:
        wanted = ids_named(data.get(key))
        was = ids_named(before.get(key)) if before is not None else None
        dropped = [i for i in was if i not in wanted] if was is not None else []
        added = [i for i in wanted if was is None or i not in was]
        if ftype in ASSET_TYPES:
            did, final = _sync(session, entry, role, wanted, dropped, added, EntryAssets, "asset_id", Assets)
        else:
            did, final = _sync(session, entry, role, wanted, dropped, added, EntryResources, "resource_id", Resources)
        changed |= did
        # The field is exactly the attachments in its role, in their order: a list field all of them, a single field
        # the first. So a picture given the role by hand appears in the field, and one whose role was changed away leaves it.
        value: Any = [str(i) for i in final] if ftype.endswith("-list") else (str(final[0]) if final else None)
        if value != data.get(key) and not (value is None and not data.get(key)):
            new_data[key] = value
    if new_data:
        entry.data_json = {**data, **new_data}
        changed = True
    if changed:
        session.commit()
    return changed


def _sync(
    session, entry, role: str, wanted: list[uuid.UUID], dropped: list[uuid.UUID], added: list[uuid.UUID], link_model, fk: str, target_model
) -> tuple[bool, list[uuid.UUID]]:
    """Returns (changed, the ids attached in the field's role afterwards, in position order)."""
    import sqlalchemy as sa

    rows = session.query(link_model).filter(link_model.entry_id == entry.id).all()
    with_role = {getattr(r, fk): r for r in rows if r.role == role}
    by_id = {getattr(r, fk): r for r in rows}
    changed = False
    for target_id, row in with_role.items():
        if target_id in dropped and target_id not in wanted:  # the field named it and no longer does
            session.delete(row)
            changed = True
    # Only ids that exist in this workspace and aren't in the Trash become attachments; a stale id is dropped from the field.
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
        row = by_id.get(target_id)
        if row is not None:
            # Attached already in another role (or none). A choice just made in the field wins; an older one doesn't —
            # the sidebar changed the role since, and the field drops the picture below.
            if row.role is None or target_id in added:
                row.role = role
                changed = True
            continue
        session.add(link_model(**{"entry_id": entry.id, fk: target_id, "role": role, "position": pos}))
        pos += 1
        changed = True
    session.flush()
    final = (
        session.query(link_model)
        .filter(link_model.entry_id == entry.id, link_model.role == role)
        .order_by(
            sa.nulls_last(link_model.position.asc()), link_model.created_at.asc() if hasattr(link_model, "created_at") else link_model.position.asc()
        )
        .all()
    )
    return changed, [getattr(r, fk) for r in final]
