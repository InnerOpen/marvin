"""A schema's asset / resource fields attach what they name, with the field's key as the role (services/entries/linked_fields.py).

The sidebar, the site renderer, the completeness contract and smart collections all read attachments, so a `heroImage`
chosen in the field has to become an attachment with role `hero`; clearing the field removes it; attachments made by
hand (another role, or none) are left alone.
"""

from __future__ import annotations

import uuid

from pytest import fixture

from marvin.db.models.platform.assets import Assets
from marvin.db.models.platform.entries import Entries
from marvin.db.models.platform.entry_assets import EntryAssets
from marvin.db.models.platform.entry_resources import EntryResources
from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.platform.resources import Resources
from marvin.services.entries.entry_service import EntryService
from marvin.services.entries.linked_fields import ids_named, linked_fields

SCHEMA = {
    "fields": [
        {"key": "body", "type": "markdown", "label": "Body"},
        {"key": "heroImage", "type": "asset", "label": "Hero", "role": "hero"},
        {"key": "gallery", "type": "asset-list", "label": "Gallery"},
        {"key": "related", "type": "resource-list", "label": "Related"},
    ]
}


class _Bus:
    def dispatch(self, **_):
        pass


@fixture
def ws(db_session):
    from marvin.db.models.groups import Groups
    from marvin.db.models.users.users import Users

    gid = uuid.uuid4()
    marker = gid.hex[:8]
    g = Groups(session=db_session, name=f"lf-{marker}", slug=f"lf-{marker}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid, group_id=gid, username=f"u-{marker}", email=f"lf-{marker}@t.test",
            full_name="A", password="x", is_superuser=False, platform_role="NONE", auth_method="MARVIN"
        )
    )  # fmt: skip
    et = EntryTypes(session=db_session, group_id=gid, name="Article", slug="article", schema_json=SCHEMA)
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()

    def asset(name):
        slug = f"{name}-{uuid.uuid4().hex[:6]}"
        row = Assets(
            session=db_session, group_id=gid, slug=slug, name=name, original_filename=f"{name}.png", filename=f"{name}.png", extension="png",
            file_size=10, mime_type="image/png", asset_type="image", checksum=uuid.uuid4().hex, storage_provider="local", storage_key=f"lf/{slug}",
            uploaded_by=uid,
        )  # fmt: skip
        db_session.add(row)
        db_session.flush()
        return row.id

    a1, a2 = asset("one"), asset("two")
    res = Resources(session=db_session, group_id=gid, name="Thread", slug=f"thread-{marker}", resource_type="material", created_by=uid)
    db_session.add(res)
    db_session.commit()

    yield {"gid": gid, "uid": uid, "type": et.id, "a1": a1, "a2": a2, "res": res.id}

    for model in (EntryAssets, EntryResources):
        db_session.query(model).filter(model.entry_id.in_(db_session.query(Entries.id).filter(Entries.group_id == gid))).delete(
            synchronize_session=False
        )
    db_session.query(Entries).filter(Entries.group_id == gid).delete()
    db_session.query(Assets).filter(Assets.group_id == gid).delete()
    db_session.query(Resources).filter(Resources.group_id == gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == gid).delete()
    db_session.execute(Users.__table__.delete().where(Users.group_id == gid))
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _svc(db_session, ws):
    return EntryService(db_session, ws["gid"], event_bus=_Bus(), integration_id="automation")


def _asset_links(db_session, entry_id):
    return {(str(r.asset_id), r.role) for r in db_session.query(EntryAssets).filter(EntryAssets.entry_id == entry_id)}


def _create(db_session, ws, data_json, **extra):
    return _svc(db_session, ws).create(
        {
            "group_id": ws["gid"],
            "entry_type_id": ws["type"],
            "title": "T",
            "slug": f"t-{uuid.uuid4().hex[:6]}",
            "created_by": ws["uid"],
            "data_json": data_json,
            **extra,
        }
    )


def test_linked_fields_and_ids_named_read_the_schema_and_the_values():
    assert linked_fields(SCHEMA) == [("heroImage", "asset", "hero"), ("gallery", "asset-list", "gallery"), ("related", "resource-list", "related")]
    u = uuid.uuid4()
    assert ids_named(str(u)) == [u] and ids_named([str(u)]) == [u] and ids_named(f"{u}, junk") == [u] and ids_named(None) == []


def test_a_hero_chosen_in_the_field_is_attached_with_the_fields_role(db_session, ws):
    entry = _create(db_session, ws, {"heroImage": str(ws["a1"])})
    assert _asset_links(db_session, entry.id) == {(str(ws["a1"]), "hero")}


def test_changing_the_field_swaps_the_attachment_and_clearing_it_removes_it(db_session, ws):
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"heroImage": str(ws["a1"])})
    svc.update(entry.id, {"data_json": {"heroImage": str(ws["a2"])}})
    assert _asset_links(db_session, entry.id) == {(str(ws["a2"]), "hero")}
    svc.update(entry.id, {"data_json": {"heroImage": None}})
    assert _asset_links(db_session, entry.id) == set()


def test_a_list_field_attaches_each_id_and_an_attachment_made_by_hand_is_left_alone(db_session, ws):
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"gallery": [str(ws["a1"])]}, asset_attachments=[{"asset_id": str(ws["a2"]), "role": "thumbnail"}])
    assert _asset_links(db_session, entry.id) == {(str(ws["a1"]), "gallery"), (str(ws["a2"]), "thumbnail")}
    svc.update(entry.id, {"data_json": {"gallery": []}})
    assert _asset_links(db_session, entry.id) == {(str(ws["a2"]), "thumbnail")}


def test_the_editor_resending_every_attachment_does_not_undo_the_field(db_session, ws):
    """The entry editor posts the full attachment list on every save; the sync runs after that replace."""
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"heroImage": str(ws["a1"])})
    svc.update(entry.id, {"data_json": {"heroImage": str(ws["a1"])}, "asset_attachments": [{"asset_id": str(ws["a2"]), "role": "thumbnail"}]})
    assert _asset_links(db_session, entry.id) == {(str(ws["a1"]), "hero"), (str(ws["a2"]), "thumbnail")}


def test_an_attachment_made_by_hand_in_the_fields_role_is_adopted_not_removed(db_session, ws):
    """Grace added a second picture as `featured` in the sidebar while the Images field (role featured) named one: the
    next save used to remove hers. Now it stays, and the field takes it, so field and sidebar agree."""
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"gallery": [str(ws["a1"])]})
    svc.update(
        entry.id,
        {
            "data_json": {"gallery": [str(ws["a1"])]},
            "asset_attachments": [{"asset_id": str(ws["a1"]), "role": "gallery"}, {"asset_id": str(ws["a2"]), "role": "gallery"}],
        },
    )
    assert _asset_links(db_session, entry.id) == {(str(ws["a1"]), "gallery"), (str(ws["a2"]), "gallery")}
    db_session.expire_all()
    assert db_session.get(Entries, entry.id).data_json["gallery"] == [str(ws["a1"]), str(ws["a2"])]
    # once the field names it, clearing it from the field removes it like any other
    svc.update(entry.id, {"data_json": {"gallery": [str(ws["a1"])]}})
    assert _asset_links(db_session, entry.id) == {(str(ws["a1"]), "gallery")}


def test_an_empty_single_field_takes_an_attachment_made_by_hand_in_its_role(db_session, ws):
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"heroImage": None})
    svc.update(entry.id, {"data_json": {"heroImage": None}, "asset_attachments": [{"asset_id": str(ws["a2"]), "role": "hero"}]})
    assert _asset_links(db_session, entry.id) == {(str(ws["a2"]), "hero")}
    db_session.expire_all()
    assert db_session.get(Entries, entry.id).data_json["heroImage"] == str(ws["a2"])


def test_changing_an_attachments_role_away_in_the_sidebar_drops_it_from_the_field(db_session, ws):
    """Grace's next step: the picture the Image field showed was re-roled `gallery` in the sidebar; the field kept
    showing it. The field is the attachments in its role, so it lets go; the attachment keeps its new role."""
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"heroImage": str(ws["a1"]), "gallery": [str(ws["a2"])]})
    svc.update(
        entry.id,
        {
            "data_json": {"heroImage": str(ws["a1"]), "gallery": [str(ws["a2"])]},  # the editor resends the fields as they were
            "asset_attachments": [{"asset_id": str(ws["a1"]), "role": "thumbnail"}, {"asset_id": str(ws["a2"]), "role": "thumbnail"}],
        },
    )
    assert _asset_links(db_session, entry.id) == {(str(ws["a1"]), "thumbnail"), (str(ws["a2"]), "thumbnail")}
    db_session.expire_all()
    data = db_session.get(Entries, entry.id).data_json
    assert (data["heroImage"], data["gallery"]) == (None, [])


def test_choosing_an_already_attached_picture_in_the_field_gives_it_the_fields_role(db_session, ws):
    svc = _svc(db_session, ws)
    entry = _create(db_session, ws, {"heroImage": None}, asset_attachments=[{"asset_id": str(ws["a2"]), "role": "thumbnail"}])
    svc.update(entry.id, {"data_json": {"heroImage": str(ws["a2"])}, "asset_attachments": [{"asset_id": str(ws["a2"]), "role": "thumbnail"}]})
    assert _asset_links(db_session, entry.id) == {(str(ws["a2"]), "hero")}


def test_an_id_that_is_not_an_asset_of_this_workspace_is_skipped(db_session, ws):
    entry = _create(db_session, ws, {"heroImage": str(uuid.uuid4())})
    assert _asset_links(db_session, entry.id) == set()


def test_a_resource_list_field_attaches_resources_the_same_way(db_session, ws):
    entry = _create(db_session, ws, {"related": [str(ws["res"])]})
    rows = db_session.query(EntryResources).filter(EntryResources.entry_id == entry.id).all()
    assert [(str(r.resource_id), r.role) for r in rows] == [(str(ws["res"]), "related")]
