"""Where an asset or a resource is used: the entries it is attached to, and as what (the role the link carries). The asset itself has no
role: the role belongs to the link between an entry and the asset (a beat's `still`, a take's `audio`), so the asset's page asks here."""

from sqlalchemy.orm import Session

from marvin.db.models.platform import Entries, EntryTypes
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.db.models.platform.entry_resources import EntryResources
from marvin.services.entries.entry_service import TRASHED
from marvin.services.entry_listing import unlisted_type_ids


def _used_by(session: Session, group_id, junction, target_column, target_id) -> list[dict]:
    """The live entries of the workspace linked to one target (an asset or a resource) through `junction`, by title: id, slug, title, status,
    entry type (slug and name) and the role the link carries. Entries in the Trash and those of an internal entry type are left out, as they
    are from the entries list."""
    hidden = set(unlisted_type_ids(session, group_id))
    rows = (
        session.query(junction.role, Entries.id, Entries.slug, Entries.title, Entries.status, Entries.entry_type_id, EntryTypes.slug, EntryTypes.name)
        .join(Entries, Entries.id == junction.entry_id)
        .join(EntryTypes, EntryTypes.id == Entries.entry_type_id)
        .filter(target_column == target_id, Entries.group_id == group_id, Entries.status != TRASHED)
        .order_by(Entries.title, junction.role)
        .all()
    )
    return [
        {"role": role, "entry_id": entry_id, "slug": slug, "title": title, "status": status, "entry_type": type_slug, "entry_type_name": type_name}
        for role, entry_id, slug, title, status, type_id, type_slug, type_name in rows
        if type_id not in hidden
    ]


def usage(session: Session, group_id, asset_id) -> list[dict]:
    """The live entries this asset is attached to, and as what role (the link carries it; the asset has none)."""
    return _used_by(session, group_id, EntryAssets, EntryAssets.asset_id, asset_id)


def resource_usage(session: Session, group_id, resource_id) -> list[dict]:
    """The live entries this resource is attached to, and as what role."""
    return _used_by(session, group_id, EntryResources, EntryResources.resource_id, resource_id)
