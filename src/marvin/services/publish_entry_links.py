"""An entry's asset and resource fields as the publishing API serves them.

An entry type's ``asset`` / ``asset-list`` / ``resource`` / ``resource-list`` fields store ids. The publishing
API has no asset or resource endpoints to look an id up with, so entries carry the objects instead: the same
``PublishedAssetRead`` / ``PublishedResourceSummary`` an entry's ``assets[]`` and ``resources[]`` hold. An
asset or resource that is in the Trash, missing, in another workspace, or an Ask file is dropped (a single
field becomes null); the list keeps its order. A value that isn't an id (already an object, a URL) passes
through unchanged. A page of entries costs one query per kind of link, however many entries it holds."""

from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from marvin.db.models.platform import Assets, Resources
from marvin.schemas.publishing import PublishedAssetRead, PublishedResourceSummary
from marvin.services.assets.scope import LIBRARY
from marvin.services.storage.provider_factory import asset_public_url

_LINK_FIELDS = {"asset": ("asset", False), "asset-list": ("asset", True), "resource": ("resource", False), "resource-list": ("resource", True)}


def published_asset(asset: Assets) -> PublishedAssetRead:
    """The asset as a site receives it."""
    return PublishedAssetRead(
        slug=asset.slug,
        name=asset.name,
        mime_type=asset.mime_type,
        asset_type=asset.asset_type,
        file_size=asset.file_size,
        width=asset.width,
        height=asset.height,
        alt_text=asset.alt_text,
        description=asset.description,
        public_url=asset_public_url(asset),
        metadata=asset.metadata_json,
        tags=list(asset.tag_names),
    )


def published_resource(resource: Resources) -> PublishedResourceSummary:
    """The resource as a site receives it."""
    return PublishedResourceSummary(
        slug=resource.slug,
        name=resource.name,
        resource_type=resource.resource_type,
        description=resource.description,
        url=resource.url,
        external_id=resource.external_id,
        metadata=resource.metadata_json,
        tags=list(resource.tag_names),
    )


def _link_fields(entry) -> list[tuple[str, str, bool]]:
    """(key, "asset"|"resource", is_list) for each link field of the entry's type that the entry has a value for."""
    schema = entry.entry_type.schema_json if entry.entry_type else None
    fields = schema.get("fields") if isinstance(schema, dict) else None
    data = entry.data_json
    if not isinstance(fields, list) or not isinstance(data, dict):
        return []
    found = []
    for field in fields:
        kind = _LINK_FIELDS.get(field.get("type")) if isinstance(field, dict) else None
        if kind and field.get("key") in data and data[field["key"]] is not None:
            found.append((field["key"], *kind))
    return found


def _as_id(value) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value.strip())
        except ValueError:
            return None
    return None


def linked_ids(entry, kind: str) -> set[UUID]:
    """The ids of the assets (``kind`` "asset") or resources the entry's link fields hold, whatever their state."""
    ids: set[UUID] = set()
    for key, field_kind, is_list in _link_fields(entry):
        if field_kind == kind:
            value = entry.data_json[key]
            ids.update(i for i in map(_as_id, value if is_list and isinstance(value, list) else [value]) if i)
    return ids


def resolve_entry_links(session: Session, group_id, entries) -> dict:
    """``{entry.id: data}`` for each entry that has link fields, with their ids resolved; other entries are absent
    (their ``data_json`` is served as stored). The entries need their ``entry_type`` loaded."""
    plan = {entry.id: _link_fields(entry) for entry in entries}
    wanted: dict[str, set[UUID]] = {"asset": set(), "resource": set()}
    for entry in entries:
        for key, kind, is_list in plan[entry.id]:
            value = entry.data_json[key]
            wanted[kind].update(i for i in map(_as_id, value if is_list and isinstance(value, list) else [value]) if i)

    served: dict[str, dict[UUID, dict]] = {"asset": {}, "resource": {}}
    if wanted["asset"]:
        rows = (
            session.query(Assets)
            .options(selectinload(Assets.tags))
            .filter(Assets.group_id == group_id, Assets.id.in_(wanted["asset"]), Assets.scope == LIBRARY, Assets.trashed_at.is_(None))
        )
        served["asset"] = {a.id: published_asset(a).model_dump(mode="json", by_alias=True) for a in rows}
    if wanted["resource"]:
        rows = (
            session.query(Resources)
            .options(selectinload(Resources.tags))
            .filter(Resources.group_id == group_id, Resources.id.in_(wanted["resource"]), Resources.trashed_at.is_(None))
        )
        served["resource"] = {r.id: published_resource(r).model_dump(mode="json", by_alias=True) for r in rows}

    resolved = {}
    for entry in entries:
        if not plan[entry.id]:
            continue
        data = dict(entry.data_json)
        for key, kind, is_list in plan[entry.id]:
            value = data[key]

            def one(item, lookup=served[kind]):
                found = _as_id(item)
                return lookup.get(found) if found else item  # an id that isn't served is None; a non-id passes through

            if is_list and isinstance(value, list):
                data[key] = [v for v in map(one, value) if v is not None]
            elif not is_list:
                data[key] = one(value)
        resolved[entry.id] = data
    return resolved
