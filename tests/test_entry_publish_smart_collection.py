"""Publishing an entry that joins a smart collection returns the entry, not a 500.

The status change re-materialises smart-collection membership in the same request, so the entry read
back can have its `collections` loaded while `entry_collections` is not: `EntryRead.model_validate`
then handed bare collection ids to a field of collection summaries and validation failed.
"""

import uuid
from types import SimpleNamespace

from marvin.db.models.users.roles import WorkspaceRole
from marvin.schemas.platform.entries import EntryRead
from tests.test_content_role_gates import P, _sign_in, workspace  # noqa: F401 — `workspace` is a fixture

E = WorkspaceRole.EDITOR


def _smart_published(client):
    res = client.post(f"{P}/collections", json={"name": "Published", "is_smart": True, "smart_rules": {"statuses": ["published"]}})
    assert res.status_code < 300, res.text
    return res.json()["id"]


def test_publishing_into_a_smart_collection_returns_the_entry(workspace):  # noqa: F811
    editor = _sign_in(workspace, E)
    et = editor.post(f"{P}/entry-types", json={"name": "Note"})
    if et.status_code == 403:  # entry types are ADMIN
        et = _sign_in(workspace, WorkspaceRole.ADMIN).post(f"{P}/entry-types", json={"name": "Note"})
        editor = _sign_in(workspace, E)
    entry = editor.post(f"{P}/entries", json={"entry_type_id": et.json()["id"], "title": "Smart", "status": "draft"}).json()["id"]
    collection = _smart_published(editor)

    res = editor.patch(f"{P}/entries/{entry}", json={"status": "published"})
    assert res.status_code == 200, res.text

    # Membership is materialised by the smart-collection listener after the event; a read sees it.
    res = editor.get(f"{P}/entries/{entry}")
    assert res.status_code == 200, res.text
    assert collection in [c["id"] for c in res.json()["collections"]]

    res = editor.patch(f"{P}/entries/{entry}", json={"status": "draft"})
    assert res.status_code == 200, res.text
    assert collection not in [c["id"] for c in editor.get(f"{P}/entries/{entry}").json()["collections"]]


def test_entry_read_survives_collections_loaded_before_their_junction_rows():
    """The 500: the listener committed a membership row in its own session, so `collections` (lazy, read
    after the commit) had it while `entry_collections` (loaded before) didn't. Bare ids can't validate."""
    now = "2026-10-06T00:00:00Z"
    entry = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        entry_type_id=uuid.uuid4(),
        title="Smart",
        slug="smart",
        status="published",
        created_at=now,
        update_at=now,
        collections=[SimpleNamespace(id=uuid.uuid4())],
        entry_collections=[],
        entry_assets=[],
        entry_resources=[],
        tag_names=[],
        data_json={},
        assets=[],
        resources=[],
    )
    read = EntryRead.model_validate(entry)
    assert read.collections == []
