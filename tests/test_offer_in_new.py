"""`capabilities_json.offer_in_new`: whether the New menu and the dashboard's Quick create offer an entry type ("Offer in the New menu"
on the entry type editor). Default on, so a type without the key is offered; a boolean only, since the dict is stored as written and the
frontend reads it with `!== false` (lib/entryTypeListing.ts isOfferedInNew). Narrower than `listed`, which it never changes.
"""

import json

import pytest
from pydantic import ValidationError

from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.platform.entry_type_rendering import CapabilitiesDefinition
from marvin.services.blueprints import packages
from tests.test_content_role_gates import _sign_in, workspace  # noqa: F401  (the `workspace` fixture)

API = "/api/platform"


def _type(ws, db_session, slug, caps):
    t = EntryTypes(session=db_session, group_id=ws.gid, slug=slug, name=slug.title(), schema_json={"fields": []}, capabilities_json=caps)
    db_session.add(t)
    db_session.commit()
    return t


def _stored(db_session, type_id):
    db_session.expire_all()
    return db_session.get(EntryTypes, type_id).capabilities_json


def test_the_key_defaults_to_on_and_takes_only_a_boolean():
    assert CapabilitiesDefinition().offer_in_new is True
    assert CapabilitiesDefinition.model_validate({"offer_in_new": False}).offer_in_new is False
    assert CapabilitiesDefinition.model_validate({"listed": True}).offer_in_new is True  # an older type, without the key
    for bad in ("false", "no", 0, None, {}):
        with pytest.raises(ValidationError):
            CapabilitiesDefinition.model_validate({"offer_in_new": bad})


def test_the_api_stores_it_as_written_and_refuses_a_non_boolean(workspace, db_session):  # noqa: F811
    note = _type(workspace, db_session, "take", {"publishable": True, "listed": True})
    admin = _sign_in(workspace, WorkspaceRole.ADMIN)
    res = admin.patch(f"{API}/entry-types/{note.id}", json={"capabilitiesJson": {"publishable": True, "listed": True, "offer_in_new": False}})
    assert res.status_code == 200, res.text
    assert res.json()["capabilitiesJson"]["offer_in_new"] is False
    assert _stored(db_session, note.id) == {"publishable": True, "listed": True, "offer_in_new": False}
    bad = admin.patch(f"{API}/entry-types/{note.id}", json={"capabilitiesJson": {"offer_in_new": "false"}})
    assert bad.status_code in (400, 422)
    assert _stored(db_session, note.id)["offer_in_new"] is False  # unchanged
    made = admin.post(f"{API}/entry-types", json={"name": "Transcript", "capabilitiesJson": {"offer_in_new": False}})
    assert made.status_code in (200, 201), made.text
    assert made.json()["capabilitiesJson"]["offer_in_new"] is False


def test_a_patch_replaces_the_whole_capabilities_object(workspace, db_session):  # noqa: F811
    """What a caller turning the switch off must know: send every key back (read, change one, send the lot)."""
    take = _type(workspace, db_session, "take", {"publishable": False, "routable": False, "listed": True})
    admin = _sign_in(workspace, WorkspaceRole.ADMIN)
    assert admin.patch(f"{API}/entry-types/{take.id}", json={"capabilitiesJson": {"offer_in_new": False}}).status_code == 200
    assert _stored(db_session, take.id) == {"offer_in_new": False}  # publishable/routable/listed dropped: back to their defaults
    other = admin.patch(f"{API}/entry-types/{take.id}", json={"name": "Take"})
    assert other.status_code == 200
    assert _stored(db_session, take.id) == {"offer_in_new": False}  # a PATCH without capabilitiesJson leaves them alone


def test_a_package_sets_it_on_a_type_it_creates(workspace, db_session):  # noqa: F811
    manifest = {
        "format": 1,
        "slug": "media-kit",
        "name": "Media kit",
        "version": "1",
        "blueprints": [
            {
                "kind": "entry_type",
                "slug": "take",
                "name": "Take",
                "payload": {"name": "Take", "schema_json": {"fields": []}, "capabilities_json": {"publishable": False, "offer_in_new": False}},
            },
            {"kind": "entry_type", "slug": "story", "name": "Story", "payload": {"name": "Story", "schema_json": {"fields": []}}},
        ],
    }
    result = packages.install(db_session, workspace.gid, packages.parse_manifest(json.dumps(manifest)), actor_id=workspace.uid)
    db_session.commit()
    assert result.created == 2
    rows = {t.slug: t for t in db_session.query(EntryTypes).filter_by(group_id=workspace.gid)}
    assert rows["take"].capabilities_json == {"publishable": False, "offer_in_new": False}
    assert (rows["story"].capabilities_json or {}).get("offer_in_new", True) is True  # not said: offered
