"""Entry types a feature is built on (services/locked_entry_types.py): the Playbook type can't be edited or deleted, whoever asks,
and says why; every other type is as editable as before."""

# ruff: noqa: F811  (the imported fixtures are used as test arguments)

from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.locked_entry_types import LOCKED_ENTRY_TYPES, lock_reason
from marvin.services.playbooks import PLAYBOOK_TYPE, ensure_playbook_type
from tests.test_audience_submissions import _client, site, verdict, workspace  # noqa: F401  (fixtures)

API = "/api/platform"


def _playbook_type(site):
    ensure_playbook_type(site.session, site.ws.gid)
    return site.session.query(EntryTypes).filter_by(group_id=site.ws.gid, slug=PLAYBOOK_TYPE).one()


def test_the_locked_slug_is_the_one_playbooks_use():
    assert set(LOCKED_ENTRY_TYPES) == {PLAYBOOK_TYPE}


def test_only_a_workspaces_own_type_is_locked():
    assert lock_reason("playbook", "some-workspace") == LOCKED_ENTRY_TYPES["playbook"]
    assert lock_reason("playbook", None) is None  # a type shipped to every workspace is guarded by is_system instead
    assert lock_reason("note", "some-workspace") is None
    assert lock_reason(None, "some-workspace") is None


def test_editing_the_playbook_type_is_refused_with_the_reason(site):
    playbook = _playbook_type(site)
    before = dict(playbook.schema_json)
    client = _client(site, WorkspaceRole.OWNER)
    for body in ({"description": "mine"}, {"name": "Procedure"}, {"schemaJson": {"fields": []}}, {"capabilities": {"listed": True}}):
        res = client.patch(f"{API}/entry-types/{playbook.id}", json=body)
        assert res.status_code == 403 and res.json()["detail"] == LOCKED_ENTRY_TYPES["playbook"], body
    site.session.expire_all()
    assert site.session.get(EntryTypes, playbook.id).schema_json == before


def test_deleting_the_playbook_type_is_refused_even_with_no_playbooks(site):
    playbook = _playbook_type(site)
    res = _client(site, WorkspaceRole.OWNER).delete(f"{API}/entry-types/{playbook.id}")
    assert res.status_code == 403 and "can't be edited or deleted" in res.json()["detail"]
    site.session.expire_all()
    assert site.session.get(EntryTypes, playbook.id) is not None


def test_the_type_reads_back_with_the_reason_and_other_types_without(site):
    playbook = _playbook_type(site)
    client = _client(site, WorkspaceRole.OWNER)
    assert client.get(f"{API}/entry-types/{playbook.id}").json()["lockedReason"] == LOCKED_ENTRY_TYPES["playbook"]
    assert client.get(f"{API}/entry-types/{site.types.note.id}").json()["lockedReason"] is None


def test_an_ordinary_type_is_still_editable(site):
    res = _client(site, WorkspaceRole.OWNER).patch(f"{API}/entry-types/{site.types.note.id}", json={"description": "Notes"})
    assert res.status_code == 200 and res.json()["description"] == "Notes"


def test_marvin_can_still_bring_the_playbook_type_up_to_date(site):
    playbook = _playbook_type(site)
    playbook.schema_json = {"fields": [f for f in playbook.schema_json["fields"] if f["key"] != "name"]}
    site.session.commit()
    ensure_playbook_type(site.session, site.ws.gid)  # its own writes bypass the lock
    site.session.expire_all()
    assert "name" in {f["key"] for f in site.session.get(EntryTypes, playbook.id).schema_json["fields"]}
