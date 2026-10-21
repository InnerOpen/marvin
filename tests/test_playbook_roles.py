"""Playbooks 02: only an Admin publishes a Playbook; agents only draft.

Driven at the seams a person or an assistant meets: the entries REST API (editor vs admin), and the agent tool registry
(`POST /api/ai/tools/{name}/invoke`). Written in the style of `test_content_role_gates.py`.
"""

import json

import pytest

from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from tests import test_content_role_gates as gates
from tests.test_playbooks import BENCH, _playbook

workspace = gates.workspace  # fixture: a workspace with a signed-in user

P = gates.P
ED, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN
FIELDS = {"name": BENCH, "description": "How to write a bench note.", "body": "# Steps"}


@pytest.fixture
def playbook_type(workspace, db_session):
    from marvin.services.playbooks import ensure_playbook_type

    return str(ensure_playbook_type(db_session, workspace.gid))


def _create(role, workspace, playbook_type, **extra):
    return gates._sign_in(workspace, role).post(
        f"{P}/entries", json={"entry_type_id": playbook_type, "title": BENCH, "slug": BENCH, "data_json": FIELDS, **extra}
    )


# ── People: REST ─────────────────────────────────────────────────────────────


def test_editor_creates_and_edits_a_playbook_draft(workspace, playbook_type):
    editor = gates._sign_in(workspace, ED)
    made = _create(ED, workspace, playbook_type, status="draft")
    assert made.status_code == 201, made.text
    body = {"data_json": {**FIELDS, "body": "# Better steps"}}
    assert editor.patch(f"{P}/entries/{made.json()['id']}", json=body).status_code == 200
    assert editor.patch(f"{P}/entries/{made.json()['id']}", json={"status": "needs_review"}).status_code == 200


@pytest.mark.parametrize("status", ["published"])
def test_editor_cannot_create_a_published_playbook_and_is_told_why(workspace, playbook_type, status):
    res = _create(ED, workspace, playbook_type, status=status)
    assert res.status_code == 403
    assert "Playbook" in res.json()["detail"] and "ADMIN" in res.json()["detail"]


def test_editor_cannot_publish_a_playbook_draft_now_or_later(workspace, playbook_type):
    editor = gates._sign_in(workspace, ED)
    draft = _create(ED, workspace, playbook_type, status="draft").json()["id"]
    now = editor.patch(f"{P}/entries/{draft}", json={"status": "published"})
    assert now.status_code == 403 and "ADMIN" in now.json()["detail"]
    later = editor.patch(f"{P}/entries/{draft}", json={"publish_at": "2030-01-01T00:00:00Z"})
    assert later.status_code == 403
    assert editor.get(f"{P}/entries/{draft}").json()["status"] == "draft"


@pytest.mark.parametrize("role", [AD, WorkspaceRole.OWNER])
def test_admin_publishes_a_playbook(workspace, playbook_type, role):
    draft = _create(ED, workspace, playbook_type, status="draft").json()["id"]
    res = gates._sign_in(workspace, role).patch(f"{P}/entries/{draft}", json={"status": "published"})
    assert res.status_code == 200 and res.json()["status"] == "published"


def test_platform_super_admin_publishes_a_playbook(workspace, playbook_type):
    draft = _create(ED, workspace, playbook_type, status="draft").json()["id"]
    boss = gates._sign_in(workspace, ED, PlatformRole.SUPER_ADMIN)
    assert boss.patch(f"{P}/entries/{draft}", json={"status": "published"}).status_code == 200


def test_admin_creates_a_published_playbook_directly(workspace, playbook_type):
    assert _create(AD, workspace, playbook_type, status="published").status_code == 201


def test_editor_cannot_change_or_remove_a_published_playbook(workspace, playbook_type):
    live = _create(AD, workspace, playbook_type, status="published").json()["id"]
    editor = gates._sign_in(workspace, ED)
    assert editor.patch(f"{P}/entries/{live}", json={"data_json": {**FIELDS, "body": "Sneaky"}}).status_code == 403
    assert editor.patch(f"{P}/entries/{live}", json={"status": "draft"}).status_code == 403
    assert editor.delete(f"{P}/entries/{live}").status_code == 403
    assert gates._sign_in(workspace, AD).patch(f"{P}/entries/{live}", json={"title": "Renamed"}).status_code == 200


def test_other_entry_types_keep_the_editor_publish_rule(workspace, playbook_type):
    admin = gates._sign_in(workspace, AD)
    et = admin.post(f"{P}/entry-types", json={"name": "Note"}).json()["id"]
    res = gates._sign_in(workspace, ED).post(f"{P}/entries", json={"entry_type_id": et, "title": "Live note", "status": "published"})
    assert res.status_code == 201


# ── Agents: tools ────────────────────────────────────────────────────────────


def _invoke(workspace, name, args, role=AD) -> dict:
    res = gates._sign_in(workspace, role).post(f"/api/ai/tools/{name}/invoke", json={"args": args})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("role", [ED, AD])
def test_an_agent_drafts_a_playbook_even_before_the_type_exists(workspace, db_session, role):
    from marvin.db.models.platform.entries import Entries

    run = _invoke(workspace, "create_draft", {"entry_type": "playbook", "title": BENCH, "fields": FIELDS}, role)
    assert "error" not in run, run
    row = db_session.query(Entries).filter_by(group_id=workspace.gid, slug=BENCH).one()
    assert row.status == "inbox"


def test_an_agent_cannot_change_a_published_playbook(workspace, db_session):
    live = _playbook(db_session, workspace.gid, status="published")
    run = _invoke(workspace, "update_draft", {"entry": BENCH, "fields": {"body": "Rewritten"}})
    assert "error" in run
    db_session.expire_all()
    assert "Open with the bench" in db_session.get(type(live), live.id).data_json["body"]


def test_an_agent_cannot_revise_a_published_playbook(workspace, db_session):
    live = _playbook(db_session, workspace.gid, status="published")
    run = _invoke(workspace, "revise_entry", {"entry": BENCH, "instruction": "make it shorter"})
    assert "Playbook" in json.dumps(run)
    db_session.expire_all()
    assert db_session.get(type(live), live.id).suggestion_json is None


@pytest.mark.parametrize("tool", ["archive_entries", "trash_entries"])
def test_an_agent_cannot_archive_or_trash_a_published_playbook(workspace, db_session, tool):
    live = _playbook(db_session, workspace.gid, status="published")
    run = _invoke(workspace, tool, {"entries": [BENCH]})
    assert "Playbook" in json.dumps(run)
    db_session.expire_all()
    assert db_session.get(type(live), live.id).status == "published"


def test_an_agent_can_still_change_a_playbook_draft(workspace, db_session):
    draft = _playbook(db_session, workspace.gid, status="draft")
    run = _invoke(workspace, "update_draft", {"entry": BENCH, "fields": {"body": "Better"}})
    assert "error" not in run, run
    db_session.expire_all()
    assert db_session.get(type(draft), draft.id).status == "draft"


# ── Schema reconcile ─────────────────────────────────────────────────────────


def test_ensure_playbook_type_adds_missing_fields_and_keeps_the_users_changes(workspace, db_session):
    from sqlalchemy.orm.attributes import flag_modified

    from marvin.db.models.platform.entry_types import EntryTypes
    from marvin.services.playbooks import PLAYBOOK_TYPE_PAYLOAD, ensure_playbook_type

    type_id = ensure_playbook_type(db_session, workspace.gid)
    et = db_session.get(EntryTypes, type_id)
    fields = [dict(f) for f in et.schema_json["fields"] if f["key"] != "manual_only"]  # an older workspace
    for f in fields:
        if f["key"] == "license":
            f["label"] = "Licence (ours)"
    fields.append({"key": "owner", "label": "Owner", "type": "text"})  # the user's own
    et.schema_json = {**et.schema_json, "fields": fields}
    et.name = "Runbook"
    flag_modified(et, "schema_json")
    db_session.commit()

    assert ensure_playbook_type(db_session, workspace.gid) == type_id
    db_session.expire_all()
    et = db_session.get(EntryTypes, type_id)
    by_key = {f["key"]: f for f in et.schema_json["fields"]}
    assert set(by_key) == {f["key"] for f in PLAYBOOK_TYPE_PAYLOAD["schema_json"]["fields"]} | {"owner"}
    assert by_key["license"]["label"] == "Licence (ours)"
    assert by_key["manual_only"]["type"] == "boolean"
    assert et.name == "Runbook"
    assert len(et.schema_json["fields"]) == len(by_key)  # no duplicates, and a second pass changes nothing
    ensure_playbook_type(db_session, workspace.gid)
    assert len(db_session.get(EntryTypes, type_id).schema_json["fields"]) == len(by_key)


# ── People: the AI routes follow the same rule ───────────────────────────────


def test_an_editor_cannot_revise_a_published_playbook_with_ai(workspace, db_session):
    _playbook(db_session, workspace.gid, status="published")
    res = gates._sign_in(workspace, ED).post("/api/ai/revise-entry", json={"entry": BENCH, "instruction": "tighten it"})
    assert res.status_code == 403 and "ADMIN" in res.json()["detail"]


def test_ai_write_back_is_not_applied_to_a_published_playbook_for_an_editor(workspace, db_session):
    """In automatic-update mode an operation's output is written straight onto the entry, so who may change it matters."""
    from marvin.routes.ai.operations_controller import AIOperationsController

    live = _playbook(db_session, workspace.gid, status="published")
    draft = _playbook(db_session, workspace.gid, "still-a-draft", status="draft")

    def may_change(role, entry):
        gates._sign_in(workspace, role)
        ctl = object.__new__(AIOperationsController)
        ctl.user = gates.app.dependency_overrides[gates.get_current_user]()
        ctl.session = db_session
        return ctl._may_change("entry", entry)

    assert may_change(ED, live) is False
    assert may_change(ED, draft) is True
    assert may_change(AD, live) is True


# ── Workflows ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("step", [{"op": "publish"}, {"op": "archive"}, {"op": "set_data", "data": {"body": "Rewritten"}}])
def test_a_workflow_needs_an_admin_author_to_publish_or_change_a_playbook(workspace, db_session, step):
    """Workflows run as the author's live role: an author since demoted to Editor must not publish Playbooks through one."""
    from marvin.services.automation.actions.base import AutomationActionError
    from marvin.services.automation.actions.entry import run_entry_action
    from marvin.services.automation.authz import ROLE_ADMIN, ROLE_EDITOR

    row = _playbook(db_session, workspace.gid, status="draft")
    action, context = {"kind": "entry", "entity_id": str(row.id), **step}, {"event": {}, "steps": {}, "depth": 0}

    with pytest.raises(AutomationActionError, match="Playbook"):
        run_entry_action(db_session, workspace.gid, action, context, authorizer_role=ROLE_EDITOR)
    db_session.refresh(row)
    assert row.status == "draft" and row.data_json["body"] != "Rewritten"

    run_entry_action(db_session, workspace.gid, action, context, authorizer_role=ROLE_ADMIN)  # an Admin author still can


# ── Agents: no side door to a draft's text ───────────────────────────────────


def test_agents_cannot_read_a_draft_playbook_through_the_entry_tools(workspace, db_session):
    draft = _playbook(db_session, workspace.gid, "unreleased-voice", status="draft", body="TOP SECRET DRAFT STEPS")
    live = _playbook(db_session, workspace.gid, status="published")
    ordinary_id = {"id_or_slug": str(draft.id)}

    for ident in (ordinary_id, {"id_or_slug": "unreleased-voice"}, {"id_or_slug": str(live.id)}):
        out = _invoke(workspace, "get_entry", ident, ED)
        assert "load_playbook" in out["error"] and "TOP SECRET" not in json.dumps(out)
    for args in ({"entry_type": "playbook"}, {"entries": ["unreleased-voice"]}, {"entry_type": "playbook", "status": "draft"}, {"text": "voice"}):
        out = _invoke(workspace, "find_entries", args, ED)
        assert out["count"] == 0 and out["entries"] == [], args
    assert "load_playbook" in _invoke(workspace, "find_entries", {"entry_type": "playbook"}, ED)["note"]
