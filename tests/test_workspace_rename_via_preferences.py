"""Settings → General's rename goes through PATCH /api/groups/{id}/preferences with a `name`. It used to set the name
on a read schema and save nothing; now it renames the workspace the way the admin route does, keeping the old slug as
an alias, and refuses a name another workspace has (409)."""

# ruff: noqa: F811 — `workspace` is a fixture
from marvin.db.models.groups.groups import Groups
from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.group.workspace_rename import find_group_by_slug
from tests.test_audit_settings import _sign_in, workspace  # noqa: F401 — fixture

P = "/api/groups"


def test_a_new_name_renames_the_workspace_and_keeps_the_old_slug_resolvable(db_session, workspace):
    client = _sign_in(workspace, WorkspaceRole.OWNER)
    old_slug = workspace.slug

    res = client.patch(f"{P}/{workspace.gid}/preferences", json={"name": "Brass & Burn"})

    assert res.status_code == 200, res.text
    db_session.expire_all()
    group = db_session.get(Groups, workspace.gid)
    assert (group.name, group.slug) == ("Brass & Burn", "brass-burn")
    assert find_group_by_slug(db_session, old_slug).id == workspace.gid  # old links still land


def test_a_name_another_workspace_has_is_refused(db_session, workspace):
    import uuid

    other = Groups(session=db_session, name="Taken", slug="taken")
    other.id = uuid.uuid4()
    db_session.add(other)
    db_session.commit()
    client = _sign_in(workspace, WorkspaceRole.OWNER)
    try:
        res = client.patch(f"{P}/{workspace.gid}/preferences", json={"name": "Taken"})
        assert res.status_code == 409 and "another workspace" in res.text.lower()
        db_session.expire_all()
        assert db_session.get(Groups, workspace.gid).slug == workspace.slug  # unchanged
    finally:
        db_session.rollback()
        db_session.query(Groups).filter(Groups.id == other.id).delete()
        db_session.commit()
