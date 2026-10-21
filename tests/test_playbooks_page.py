# ruff: noqa: F811 — the `workspace` fixture is imported, then named as a parameter
"""Playbooks 03: the Playbooks page's API (routes/groups/playbooks_controller.py).

The page lists a workspace's Playbooks with their status and makes sure the internal `playbook` type exists before the first one
is written; the editor itself saves through the ordinary entries API. Playbooks never show where content is listed.
"""

from marvin.db.models.platform.entry_types import EntryTypes
from marvin.db.models.users.roles import WorkspaceRole
from tests import test_content_role_gates as gates
from tests.test_playbooks import BENCH, BENCH_DESCRIPTION, _playbook

workspace = gates.workspace  # fixture: a workspace with a signed-in user

P = "/api/groups/playbooks"


def _as(workspace, role=WorkspaceRole.EDITOR):
    return gates._sign_in(workspace, role)


def _type_count(db_session, gid):
    return db_session.query(EntryTypes).filter_by(group_id=gid, slug="playbook").count()


def test_a_workspace_with_none_lists_nothing_and_reading_creates_no_type(workspace, db_session):
    res = _as(workspace).get(P)
    assert res.status_code == 200
    assert res.json() == {"entryTypeId": None, "items": []}
    assert _type_count(db_session, workspace.gid) == 0


def test_the_list_carries_each_playbook_with_its_status(workspace, db_session):
    _playbook(db_session, workspace.gid, "zeta-draft", status="draft")
    _playbook(db_session, workspace.gid, BENCH, status="published")
    gone = _playbook(db_session, workspace.gid, "in-the-trash", status="trashed")
    body = _as(workspace).get(P).json()
    assert body["entryTypeId"]
    assert [(i["name"], i["status"]) for i in body["items"]] == [(BENCH, "published"), ("zeta-draft", "draft")]
    first = body["items"][0]
    assert first["description"] == BENCH_DESCRIPTION
    assert first["manualOnly"] is False
    assert first["id"] and first["updatedAt"]
    assert str(gone.id) not in {i["id"] for i in body["items"]}


def test_a_viewer_is_turned_away(workspace):
    assert _as(workspace, WorkspaceRole.VIEWER).get(P).status_code == 403
    assert _as(workspace, WorkspaceRole.VIEWER).post(f"{P}/type").status_code == 403


def test_making_the_type_is_idempotent(workspace, db_session):
    editor = _as(workspace)
    first = editor.post(f"{P}/type")
    assert first.status_code == 200
    again = editor.post(f"{P}/type")
    assert again.json() == first.json()
    assert _type_count(db_session, workspace.gid) == 1
    assert editor.get(P).json()["entryTypeId"] == first.json()["entryTypeId"]


def test_a_playbook_saves_through_the_entries_api_and_stays_out_of_content_lists(workspace, db_session):
    editor = _as(workspace)
    type_id = editor.post(f"{P}/type").json()["entryTypeId"]
    made = editor.post(
        "/api/platform/entries",
        json={
            "entryTypeId": type_id,
            "title": "release-notes",
            "slug": "release-notes",
            "status": "draft",
            "dataJson": {"name": "release-notes", "description": "How we write release notes.", "body": "# Steps"},
        },
    )
    assert made.status_code == 201, made.text
    listed = editor.get(P).json()["items"]
    assert [(i["name"], i["status"]) for i in listed] == [("release-notes", "draft")]
    assert "release-notes" not in {e["slug"] for e in editor.get("/api/platform/entries").json()}
    counts = editor.get("/api/platform/entries/counts").json()
    assert sum(counts.values()) == 0
    query = editor.post("/api/platform/entries/query", json={"spec": {}}).json()
    assert "release-notes" not in str(query)
