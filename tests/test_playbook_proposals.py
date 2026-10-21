"""Playbooks 11: an agent proposes a Playbook (new, or a change to a published one) into the Inbox.

* the tool: a change is a separate inbox draft naming the Playbook it would replace; the live one is untouched;
* a fake-model agent run that proposes a change, then an admin publishes it: only then does the live Playbook change;
* the guidance sentence in the catalog; publishing stays an Admin's.
"""

# ruff: noqa: F811 — imported fixtures are used as test arguments

import json

from marvin.db.models.users.roles import WorkspaceRole
from marvin.services.ai.base import ToolCall
from tests import test_content_role_gates as gates
from tests.test_playbook_roles import _invoke
from tests.test_playbooks import BENCH, BENCH_BODY, FakeModel, _playbook, _turn
from tests.test_playbooks import model as _model  # noqa: F401

workspace = gates.workspace  # fixture
P = gates.P
ED, AD = WorkspaceRole.EDITOR, WorkspaceRole.ADMIN
NEW_BODY = "# Bench Note voice\n\nOpen with the bench. One paragraph. Always sign off with the batch number and the date."


def _row(db_session, **where):
    from marvin.db.models.platform.entries import Entries

    db_session.expire_all()
    return db_session.query(Entries).filter_by(**where).one()


def _propose(workspace, **args):
    return _invoke(workspace, "propose_playbook_change", {"playbook": BENCH, **args}, ED)


def test_a_proposed_change_is_a_separate_inbox_draft_and_the_live_one_is_untouched(workspace, db_session):
    live = _playbook(db_session, workspace.gid)

    run = _propose(workspace, body=NEW_BODY, reason="People keep asking for the date.")

    assert "error" not in run, run
    change = _row(db_session, group_id=workspace.gid, slug=f"{BENCH}-change")
    assert change.status == "inbox" and change.id != live.id
    assert change.data_json["replaces"] == BENCH and change.data_json["body"] == NEW_BODY
    assert change.data_json["description"] == live.data_json["description"]  # untouched fields come from the live one
    assert change.summary == "People keep asking for the date."
    assert _row(db_session, id=live.id).data_json["body"] == BENCH_BODY and live.status == "published"


def test_a_second_proposal_gets_its_own_draft(workspace, db_session):
    _playbook(db_session, workspace.gid)
    _propose(workspace, body=NEW_BODY)
    _propose(workspace, description="Another way to describe it.")
    assert _row(db_session, group_id=workspace.gid, slug=f"{BENCH}-change-2").data_json["replaces"] == BENCH


def test_a_proposal_needs_a_published_playbook_and_a_difference(workspace, db_session):
    _playbook(db_session, workspace.gid, "still-a-draft", status="draft")
    assert "not a published Playbook" in _invoke(workspace, "propose_playbook_change", {"playbook": "still-a-draft", "body": "x"}, ED)["error"]
    _playbook(db_session, workspace.gid)
    assert "nothing differs" in _propose(workspace, body=BENCH_BODY)["error"]


def test_an_agent_can_still_draft_a_new_playbook(workspace, db_session):
    run = _invoke(
        workspace,
        "create_draft",
        {"entry_type": "playbook", "title": "label-voice", "fields": {"name": "label-voice", "description": "d", "body": "b"}},
        ED,
    )
    assert "error" not in run
    assert _row(db_session, group_id=workspace.gid, slug="label-voice").status == "inbox"


def test_publishing_a_change_replaces_the_live_content_and_keeps_its_identity_and_history(workspace, db_session):
    live = _playbook(db_session, workspace.gid)
    _propose(workspace, body=NEW_BODY, allowed_tools="find_entries")
    change = _row(db_session, group_id=workspace.gid, slug=f"{BENCH}-change")

    res = gates._sign_in(workspace, AD).patch(f"{P}/entries/{change.id}", json={"status": "published"})

    assert res.status_code == 200, res.text
    assert res.json()["id"] == str(live.id)  # the live entry comes back
    now = _row(db_session, id=live.id)
    assert now.status == "published" and now.slug == BENCH
    assert now.data_json["body"] == NEW_BODY and now.data_json["allowed_tools"] == "find_entries" and now.data_json["name"] == BENCH
    assert "replaces" not in now.data_json
    spent = _row(db_session, id=change.id)
    assert spent.status == "archived" and spent.metadata_json["replaced_playbook"] == str(live.id)
    from marvin.services.playbooks import published_playbooks

    assert [p.name for p in published_playbooks(db_session, workspace.gid)] == [BENCH]  # never a second Playbook


def test_an_editor_cannot_publish_the_change(workspace, db_session):
    live = _playbook(db_session, workspace.gid)
    _propose(workspace, body=NEW_BODY)
    change = _row(db_session, group_id=workspace.gid, slug=f"{BENCH}-change")

    res = gates._sign_in(workspace, ED).patch(f"{P}/entries/{change.id}", json={"status": "published"})

    assert res.status_code == 403
    assert _row(db_session, id=live.id).data_json["body"] == BENCH_BODY and _row(db_session, id=change.id).status == "inbox"


def test_a_change_whose_playbook_was_unpublished_is_not_published_as_a_new_one(workspace, db_session):
    live = _playbook(db_session, workspace.gid)
    _propose(workspace, body=NEW_BODY)
    change = _row(db_session, group_id=workspace.gid, slug=f"{BENCH}-change")
    live.status = "draft"
    db_session.commit()

    res = gates._sign_in(workspace, AD).patch(f"{P}/entries/{change.id}", json={"status": "published"})

    assert res.status_code == 409 and "not published any more" in res.json()["detail"]
    assert _row(db_session, id=change.id).status == "inbox"


def _scheduled_change(db_session, gid, live_status="published", **data):
    """A change draft for BENCH due for scheduled publish, plus an ordinary due entry beside it."""
    from datetime import UTC, datetime, timedelta

    live = _playbook(db_session, gid, status=live_status)
    change = _playbook(db_session, gid, f"{BENCH}-change", status="inbox", body=NEW_BODY)
    change.data_json = {**change.data_json, "replaces": BENCH, **data}
    change.publish_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    return live, change


def test_a_scheduled_change_whose_playbook_is_gone_is_skipped_and_the_run_goes_on(workspace, db_session):
    from tests.test_scheduled_publishing import run_task

    live, change = _scheduled_change(db_session, workspace.gid, live_status="draft")
    other = _playbook(db_session, workspace.gid, "label-voice", status="approved")
    other.publish_at = change.publish_at
    db_session.commit()

    summary, _events = run_task(workspace.gid)  # used to raise the 409 and abort the whole run

    stale = _row(db_session, id=change.id)
    assert stale.status == "inbox" and stale.publish_at is None  # not retried every five minutes
    assert "not published any more" in stale.metadata_json["scheduled_publish_failed"]["reason"]
    assert _row(db_session, id=other.id).status == "published"  # the entry after it still went out
    assert "label-voice" in summary and _row(db_session, id=live.id).data_json["body"] == BENCH_BODY


def test_a_scheduled_change_publishes_through_the_hook_when_its_playbook_is_live(workspace, db_session):
    from tests.test_scheduled_publishing import run_task

    live, change = _scheduled_change(db_session, workspace.gid)

    run_task(workspace.gid)

    assert _row(db_session, id=live.id).data_json["body"] == NEW_BODY and _row(db_session, id=change.id).status == "archived"


def test_a_change_still_has_to_pass_the_publish_gate(workspace, db_session):
    live, change = _scheduled_change(db_session, workspace.gid, description="")  # a required field left empty
    change.publish_at = None
    db_session.commit()

    res = gates._sign_in(workspace, AD).patch(f"{P}/entries/{change.id}", json={"status": "published"})

    assert res.status_code == 422, res.text
    assert _row(db_session, id=live.id).data_json["body"] == BENCH_BODY and _row(db_session, id=change.id).status == "inbox"


# ── An agent run ─────────────────────────────────────────────────────────────


class Proposer(FakeModel):
    """Scripted: a request to 'propose' makes the agent call propose_playbook_change, then it answers."""

    def complete_with_tools(self, messages, model, tools, options=None, tool_choice="auto"):
        self.systems.append(messages[0].content)
        self.tool_names.append({t["name"] if isinstance(t, dict) else t.name for t in tools})
        if messages[-1].role == "tool":
            return _turn(content="Proposed it for review.")
        args = {"playbook": BENCH, "body": NEW_BODY, "reason": "Repeated correction."}
        return _turn(tool_calls=[ToolCall(id="p1", name="propose_playbook_change", arguments=args)])


def test_an_agent_proposes_a_change_and_the_published_playbook_is_unchanged_until_an_admin_publishes(workspace, db_session, monkeypatch):
    from marvin.routes.ai.operations_controller import AIOperationsController

    fake = Proposer()
    monkeypatch.setattr(AIOperationsController, "_agent_provider", lambda self: fake)
    monkeypatch.setattr(AIOperationsController, "_default_model", lambda self: "m")
    live = _playbook(db_session, workspace.gid)

    res = gates._sign_in(workspace, ED).post("/api/ai/agent", json={"message": "Propose a better bench note Playbook.", "source": "api"})
    assert res.status_code == 200, res.text
    run = res.json()

    assert [s["tool"] for s in run["steps"]] == ["propose_playbook_change"]
    assert "error" not in json.loads(run["steps"][0]["result"])
    assert "propose_playbook_change" in fake.tool_names[0]
    assert "propose_playbook_change" in fake.systems[0]  # the catalog tells it when to propose
    change = _row(db_session, group_id=workspace.gid, slug=f"{BENCH}-change")
    assert change.status == "inbox"
    assert _row(db_session, id=live.id).data_json["body"] == BENCH_BODY  # unchanged

    gates._sign_in(workspace, AD).patch(f"{P}/entries/{change.id}", json={"status": "published"}).raise_for_status()

    assert _row(db_session, id=live.id).data_json["body"] == NEW_BODY


def test_the_catalog_tells_an_agent_that_can_draft_when_to_propose():
    from marvin.services.playbooks import Playbook, catalog_block

    pb = [Playbook(id="1", name=BENCH, description="d", body="b")]
    assert "propose_playbook_change" in catalog_block(pb, can_propose=True)
    assert "propose_playbook_change" not in catalog_block(pb)
    assert catalog_block([], can_propose=False) == ""  # nothing published and nothing it could draft: the prompt is untouched


def test_with_none_published_an_agent_that_can_draft_is_told_playbooks_exist_and_how_to_draft_the_first():
    from marvin.services.playbooks import catalog_block

    text = catalog_block([], can_propose=True)

    assert text.startswith("## Playbooks")
    assert "None are published yet" in text
    assert "create_draft" in text and "playbook" in text  # the entry type to draft into
    assert all(field in text for field in ("name", "description", "body"))
    assert "admin" in text.lower()  # it only drafts; an admin publishes
    assert "load_playbook" not in text  # there is nothing to load yet
