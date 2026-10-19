"""create_draft / update_draft: drafts whose fields the CALLER wrote (an assistant over MCP, or Marvin's own agent for
an exact edit), saved with no model of Marvin's — so they work whatever the workspace's AI provider, or with none."""

# ruff: noqa: F811 — the `ws` fixture is imported, then named as a parameter
import uuid

import pytest

from marvin.db.models.users.roles import WorkspaceRole
from tests.test_remote_mcp_oauth import ws  # noqa: F401 — the fixture

SCHEMA = {"fields": [{"key": "body", "label": "Body", "type": "text"}, {"key": "price", "label": "Price", "type": "number"}]}


@pytest.fixture
def events(monkeypatch):
    """Events captured instead of logged (a logged event would pin the test user in event_log)."""
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    sent = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append(kw))
    return sent


@pytest.fixture
def bench(db_session, ws, events):
    """An Editor's workspace with a Bench Note type and no AI provider at all."""
    from marvin.db.models.platform import EntryTypes

    editor = ws(role=WorkspaceRole.EDITOR)
    et = EntryTypes(session=db_session, group_id=editor.gid, name="Bench Note", slug="bench-note", schema_json=SCHEMA)
    db_session.add(et)
    db_session.commit()
    yield editor
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel
    from marvin.db.models.platform import Entries

    db_session.rollback()
    db_session.query(Entries).filter(Entries.group_id == editor.gid).delete()
    db_session.query(EntryTypes).filter(EntryTypes.group_id == editor.gid).delete()
    db_session.query(WorkspaceAISettingsModel).filter_by(group_id=editor.gid).delete()
    db_session.commit()


def _invoke(db_session, w, name, args):
    from marvin.repos.all_repositories import get_repositories
    from marvin.services.ai.tool_gateway import invoke_unattended

    user = get_repositories(db_session, group_id=None).users.get_one(w.uid, "id", any_case=False)
    return invoke_unattended(db_session, w.gid, user, name, args, source="mcp")


def _approval(db_session, w, mode):
    from marvin.db.models.groups.ai_settings import WorkspaceAISettingsModel

    db_session.add(WorkspaceAISettingsModel(session=db_session, group_id=w.gid, approval_mode=mode))
    db_session.commit()


def test_create_draft_saves_an_inbox_draft_with_no_ai_provider(db_session, bench, events):
    from marvin.db.models.platform import Entries
    from marvin.services.event_bus_service.event_types import EventTypes

    out = _invoke(db_session, bench, "create_draft", {"entry_type": "bench-note", "title": "Built to Wear", "summary": "On repair.",
                                                      "fields": {"body": "Read the wear first.", "price": 0}, "tags": ["Repair"]})  # fmt: skip
    assert "error" not in out, out
    entry = db_session.get(Entries, uuid.UUID(out["entryId"]))
    assert entry.status == "inbox" and entry.title == "Built to Wear" and entry.data_json == {"body": "Read the wear first.", "price": 0}
    assert "repair" in [t.lower() for t in entry.tag_names] and out["reviewLink"].startswith("[")
    assert EventTypes.entry_created in [e["event_type"] for e in events]  # smart collections, the search index…


def test_create_draft_refuses_fields_the_type_does_not_have(db_session, bench):
    out = _invoke(db_session, bench, "create_draft", {"entry_type": "bench-note", "title": "X", "fields": {"colour": "blue"}})
    assert "colour is not a field of 'bench-note'" in out["error"] and "body" in out["error"]
    assert "title is required" in _invoke(db_session, bench, "create_draft", {"entry_type": "bench-note", "title": " "})["error"]
    assert "not found" in _invoke(db_session, bench, "create_draft", {"entry_type": "nope", "title": "X"})["error"]


def test_update_draft_changes_only_what_it_is_given(db_session, bench):
    from marvin.db.models.platform import Entries

    _approval(db_session, bench, "allow-draft-update")
    made = _invoke(db_session, bench, "create_draft", {"entry_type": "bench-note", "title": "T", "fields": {"body": "old", "price": 1}})
    out = _invoke(db_session, bench, "update_draft", {"entry": made["entryId"], "fields": {"price": 450}})
    assert out["outcome"] == "applied", out
    db_session.expire_all()
    assert db_session.get(Entries, uuid.UUID(made["entryId"])).data_json == {"body": "old", "price": 450}


def test_update_draft_follows_the_approval_policy_and_leaves_published_entries_alone(db_session, bench):
    from marvin.db.models.platform import Entries

    _approval(db_session, bench, "suggest-only")
    made = _invoke(db_session, bench, "create_draft", {"entry_type": "bench-note", "title": "T", "fields": {"body": "old"}})
    staged = _invoke(db_session, bench, "update_draft", {"entry": made["entryId"], "fields": {"body": "new"}})
    assert staged["outcome"] == "staged"
    db_session.expire_all()
    entry = db_session.get(Entries, uuid.UUID(made["entryId"]))
    assert entry.data_json == {"body": "old"} and entry.suggestion_json["data_json.body"] == "new"

    entry.status = "published"
    db_session.commit()
    refused = _invoke(db_session, bench, "update_draft", {"entry": made["entryId"], "fields": {"body": "x"}})
    assert "is published" in refused["error"]


def test_a_viewer_cannot_create_drafts(db_session, ws, events):
    viewer = ws(role=WorkspaceRole.VIEWER)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as refused:
        _invoke(db_session, viewer, "create_draft", {"entry_type": "bench-note", "title": "X"})
    assert refused.value.status_code == 403
