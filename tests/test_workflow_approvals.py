"""The approval step (`{"kind": "approval", …}`, services/automation/approvals.py): a run parks for a person and goes on
from the next step once they decide — approved, denied, stale (the entry changed after it was asked) or expired — with
`${steps.<id>.output.decision}`; and only an approved run may call an integration action that requires approval.

The case: a published article is featured only once an editor approves; otherwise the decision is noted on it."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction

from marvin.services.automation import approvals
from marvin.services.automation.authoring import draft_issues
from marvin.services.automation.authz import ROLE_ADMIN, ROLE_AUTHOR, ROLE_EDITOR
from tests.test_workflow_library import _entry, _entry_doc, _fire, _reload, ws  # noqa: F401 — the fixture

APPROVED = {"field": "steps.ok.output.decision", "op": "eq", "value": "approved"}
DEFINITION = {
    "trigger": {"type": "event", "event": "entry_published"},
    "actions": [
        {"kind": "approval", "id": "ok", "message": "Feature “${entry.title}” on the home page?"},
        {"kind": "entry", "op": "set_metadata", "metadata": {"featured": True}, "when": APPROVED},
        {"kind": "entry", "op": "set_metadata", "metadata": {"not_featured": "${steps.ok.output.decision}"}, "when": {"not": APPROVED}},
    ],
}


class _SignOff(IntegrationProvider):
    """An integration whose action needs a person's approval (like Instagram's private reply)."""

    slug = "signoff"
    name = "Sign-off (fake)"
    actions = (ProviderAction(key="send_contract", label="Send contract", requires_approval=True),)

    def __init__(self):
        self.calls = []

    def run_action(self, key, args, ctx):
        self.calls.append((key, dict(args)))
        return {"sent": True}


def _install(ws, definition=DEFINITION):  # noqa: F811
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    assert draft_issues(ws.session, ws.gid, definition) == []
    row = WorkspaceAutomationModel(
        session=ws.session,
        group_id=ws.gid,
        name="Feature with sign-off",
        slug=f"sign-off-{uuid.uuid4().hex[:6]}",
        enabled=True,
        definition=definition,
    )
    ws.session.add(row)
    ws.session.commit()
    return row


def _runs(ws, row):  # noqa: F811
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    rows = ws.session.query(AutomationExecutionModel).filter_by(group_id=ws.gid, automation_id=row.id).all()
    # Two runs can start in the same tick: the one resumed from another (retry_of) comes after it.
    return sorted(rows, key=lambda r: (r.started_at, r.retry_of_id is not None))


def _published(ws, title="Engraving brass"):  # noqa: F811
    article = _entry(ws, "article", title, status="published", data={"body": "x"})
    return article


def _waiting(ws):  # noqa: F811
    (row,) = approvals.pending(ws.session, ws.gid, ROLE_EDITOR)
    return row


# ── parking ──────────────────────────────────────────────────────────────────


def test_the_run_waits_at_the_step_and_the_editors_are_asked(ws, monkeypatch):  # noqa: F811
    from marvin.services.event_bus_service.event_bus_service import EventBusService

    sent = []
    monkeypatch.setattr(EventBusService, "dispatch", lambda self, **kw: sent.append((kw["event_type"].name, kw)))
    workflow = _install(ws)
    article = _published(ws)

    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

    (run,) = _runs(ws, workflow)
    assert run.status == "waiting" and [a.status for a in run.actions] == ["waiting"]  # nothing after it ran yet
    waiting = _waiting(ws)
    assert (waiting.message, waiting.min_role, waiting.entry_id) == ("Feature “Engraving brass” on the home page?", ROLE_EDITOR, article.id)
    asked = [kw for name, kw in sent if name == "workflow_approval_requested"]
    assert len(asked) == 1 and asked[0]["document_data"].message == waiting.message
    assert "featured" not in (_reload(ws, article).metadata_json or {})
    assert approvals.pending(ws.session, ws.gid, ROLE_AUTHOR) == []  # an author isn't asked


# ── deciding ─────────────────────────────────────────────────────────────────


def test_approved_goes_on_from_the_next_step_in_a_new_run(ws):  # noqa: F811
    workflow = _install(ws)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    waiting = _waiting(ws)

    approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR, note="Lovely")

    assert _reload(ws, article).metadata_json["featured"] is True
    parked, resumed = _runs(ws, workflow)
    assert (parked.status, resumed.status, resumed.retry_of_id) == ("resumed", "success", parked.id)
    assert [a.status for a in resumed.actions] == ["success", "success", "skipped"]
    assert resumed.actions[0].output_snapshot["decision"] == "approved" and resumed.actions[0].output_snapshot["note"] == "Lovely"
    ws.session.refresh(waiting)
    assert (waiting.status, waiting.decided_by, waiting.resumed_execution_id) == ("approved", ws.uid, resumed.id)


def test_denied_takes_the_other_branch(ws):  # noqa: F811
    _install(ws)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")

    approvals.decide(ws.session, ws.gid, _waiting(ws).id, "deny", user_id=ws.uid, role=ROLE_EDITOR)

    meta = _reload(ws, article).metadata_json
    assert meta["not_featured"] == "denied" and "featured" not in meta


def test_approving_an_entry_that_changed_since_is_stale_not_approved(ws):  # noqa: F811
    _install(ws)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    waiting = _waiting(ws)
    entry = _reload(ws, article)
    entry.title = "Engraving brass (rewritten)"
    entry.update_at = datetime.now(UTC) + timedelta(seconds=5)
    ws.session.commit()

    approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR)

    meta = _reload(ws, article).metadata_json
    assert meta["not_featured"] == "stale" and "featured" not in meta


def test_who_may_decide_and_only_once(ws):  # noqa: F811
    _install(ws, {**DEFINITION, "actions": [{**DEFINITION["actions"][0], "approvers": "admin"}, *DEFINITION["actions"][1:]]})
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    (waiting,) = approvals.pending(ws.session, ws.gid, ROLE_ADMIN)

    with pytest.raises(approvals.ApprovalError) as refused:
        approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR)
    assert refused.value.status == 403
    approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_ADMIN)
    with pytest.raises(approvals.ApprovalError) as again:
        approvals.decide(ws.session, ws.gid, waiting.id, "deny", user_id=ws.uid, role=ROLE_ADMIN)
    assert again.value.status == 409 and "approved" in str(again.value)


def test_nobody_deciding_in_time_goes_on_as_expired(ws):  # noqa: F811
    _install(ws)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    waiting = _waiting(ws)
    waiting.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    ws.session.commit()

    with pytest.raises(approvals.ApprovalError, match="expired"):
        approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR)
    assert approvals.expire_due(ws.session) == 1

    assert _reload(ws, article).metadata_json["not_featured"] == "expired"


def test_an_on_failure_step_cant_wait():
    from pydantic import ValidationError

    from marvin.schemas.group.automation_definition import AutomationDefinition

    with pytest.raises(ValidationError, match="can't run in on_failure"):
        AutomationDefinition.model_validate({"trigger": {"type": "manual"}, "actions": [], "on_failure": [DEFINITION["actions"][0]]})


# ── an action that needs approval ────────────────────────────────────────────


@pytest.fixture
def signoff(ws, monkeypatch):  # noqa: F811
    from marvin.db.models.groups.integrations import IntegrationModel

    provider = _SignOff()
    monkeypatch.setitem(INTEGRATION_REGISTRY, "signoff", provider)
    ws.session.add(
        IntegrationModel(session=ws.session, group_id=ws.gid, provider="signoff", name="Sign-off", slug="signoff", enabled=True, config={})
    )
    ws.session.commit()
    return provider


def test_an_action_that_needs_approval_runs_only_after_one_approves(ws, signoff):  # noqa: F811
    send = {"kind": "integration", "integration": "signoff", "action": "send_contract", "args": {"to": "${entry.title}"}}
    without = {"trigger": {"type": "event", "event": "entry_published"}, "actions": [send]}
    issues = draft_issues(ws.session, ws.gid, without)
    assert any("needs a person's approval: put an Approval step before it" in i["message"] for i in issues)

    _install(ws, {**without, "actions": [DEFINITION["actions"][0], {**send, "when": APPROVED}]})
    for decision in ("deny", "approve"):
        article = _published(ws, f"Contract {decision}")
        _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id=f"c-{decision}")
        approvals.decide(ws.session, ws.gid, _waiting(ws).id, decision, user_id=ws.uid, role=ROLE_EDITOR)

    assert signoff.calls == [("send_contract", {"to": "Contract approve"})]  # only the approved run sent it


def test_a_dry_run_previews_the_question_and_the_steps_after_it(ws, signoff):  # noqa: F811
    from marvin.services.automation.engine import dry_run_for_event

    send = {"kind": "integration", "integration": "signoff", "action": "send_contract", "args": {}}
    workflow = _install(ws, {"trigger": {"type": "event", "event": "entry_published"}, "actions": [DEFINITION["actions"][0], send]})
    article = _published(ws)

    result = dry_run_for_event(ws.session, ws.gid, workflow, _entry_doc(article) | {"event_type": "entry_published", "entry_id": str(article.id)})

    ask, call = result["plan"]
    assert ask["resolved"]["message"] == "Feature “Engraving brass” on the home page?" and ask["status"] == "success"
    assert call["status"] == "success" and call["resolved"]["action"] == "send_contract"
    assert approvals.pending(ws.session, ws.gid, ROLE_EDITOR) == [] and signoff.calls == []


# ── choices ──────────────────────────────────────────────────────────────────
PICK = {
    "trigger": {"type": "event", "event": "entry_published"},
    "actions": [
        {"kind": "approval", "id": "pick", "message": "Which cover for “${entry.title}”?", "choices": ["Dawn", "Dusk", "${entry.title} at night"]},
        {
            "kind": "entry",
            "op": "set_metadata",
            "metadata": {"cover": "${steps.pick.output.choice}", "nth": "${steps.pick.output.choice_index}"},
            "when": {"field": "steps.pick.output.decision", "op": "eq", "value": "approved"},
        },
    ],
}


def test_an_approval_with_choices_is_approved_with_one_of_them(ws):  # noqa: F811
    _install(ws, PICK)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    waiting = _waiting(ws)
    assert waiting.choices == ["Dawn", "Dusk", "Engraving brass at night"]  # each label a template

    with pytest.raises(approvals.ApprovalError, match="Pick one"):
        approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR)
    with pytest.raises(approvals.ApprovalError, match="No such choice"):
        approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR, choice="Noon")
    approvals.decide(ws.session, ws.gid, waiting.id, "approve", user_id=ws.uid, role=ROLE_EDITOR, choice=1)

    meta = _reload(ws, article).metadata_json
    assert (meta["cover"], meta["nth"]) == ("Dusk", 1)
    ws.session.refresh(waiting)
    assert waiting.choice == "Dusk"


def test_choices_from_a_list_a_template_resolves_to_and_denying_picks_none(ws):  # noqa: F811
    listed = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [
            {"kind": "approval", "id": "pick", "message": "Which?", "choices": "${event.titles}"},
            {
                "kind": "entry",
                "op": "set_metadata",
                "metadata": {"outcome": "${steps.pick.output.decision}", "picked": "${steps.pick.output.choice}"},
            },
        ],
    }
    _install(ws, listed)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article, titles=["Red", "Blue"]), entity=article.id, entity_type="entry")
    waiting = _waiting(ws)
    assert waiting.choices == ["Red", "Blue"]

    approvals.decide(ws.session, ws.gid, waiting.id, "deny", user_id=ws.uid, role=ROLE_EDITOR)

    meta = _reload(ws, article).metadata_json
    assert meta["outcome"] == "denied" and "picked" not in meta  # denied: no choice (an empty value isn't written)


def test_choices_that_resolve_to_too_few_fail_the_step(ws):  # noqa: F811
    one = {**PICK, "actions": [{**PICK["actions"][0], "choices": "${entry.metadata.nothing}"}]}
    workflow = _install(ws, one)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry")
    (run,) = _runs(ws, workflow)
    assert run.status == "failed" and "at least two" in run.actions[0].error


# ── a picture with the question, and attaching it only once approved ──────────────────────────────


def test_an_approval_can_show_a_picture_and_the_run_keeps_its_url(ws):  # noqa: F811
    from marvin.routes.automations.automations_controller import _approval_read

    definition = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [{"kind": "approval", "id": "ok", "message": "Use this?", "image": "https://pics.test/${entry.slug}.jpg"}],
    }
    row = _install(ws, definition)
    article = _published(ws)
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="pic")

    waiting = _waiting(ws)
    assert waiting.image_url == f"https://pics.test/{article.slug}.jpg"
    assert _approval_read(ws.session, waiting).image_url == waiting.image_url  # the page and the dashboard show it
    assert _runs(ws, row)[0].status == "waiting"


def test_an_empty_picture_template_shows_nothing_but_a_non_url_fails_the_step(ws):  # noqa: F811
    blank = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [{"kind": "approval", "message": "Ok?", "image": "${entry.metadata.none}"}],
    }
    blank_row = _install(ws, blank)
    article = _published(ws, "Blank picture")
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id="blank")
    assert _waiting(ws).image_url is None
    approvals.decide(ws.session, ws.gid, _waiting(ws).id, "deny", user_id=ws.uid, role=ROLE_EDITOR)
    blank_row.enabled = False  # out of the way of the next publish
    ws.session.commit()

    bad = {"trigger": {"type": "event", "event": "entry_published"}, "actions": [{"kind": "approval", "message": "Ok?", "image": "${entry.title}"}]}
    row = _install(ws, bad)
    other = _published(ws, "Not a picture")
    _fire(ws, "entry_published", _entry_doc(other), entity=other.id, entity_type="entry", correlation_id="bad")
    failed = [r for r in _runs(ws, row) if r.status == "failed"]
    assert failed and "picture URL" in (failed[0].error or "") and approvals.pending(ws.session, ws.gid, ROLE_EDITOR) == []


def test_attach_asset_links_a_picture_in_a_role_once(ws):  # noqa: F811
    from marvin.db.models.platform import EntryAssets
    from marvin.services.automation.engine import run_automation_now
    from marvin.services.automation.recorder import ExecutionRecorder
    from tests.test_workflow_library import _asset

    picture = _asset(ws, "cover-pic", mime="image/png")
    ws.session.commit()
    article = _published(ws, "Attach me")
    definition = {
        "trigger": {"type": "manual"},
        "actions": [{"kind": "entry", "op": "attach_asset", "entity_id": str(article.id), "asset": picture.slug, "role": "cover-variant"}],
    }
    row = _install(ws, definition)

    preview = run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, dry_run=True)
    assert preview["ok"] and ws.session.query(EntryAssets).filter_by(entry_id=article.id).count() == 0  # a dry run links nothing
    for _ in range(2):  # idempotent: the second run finds the link and leaves it
        assert run_automation_now(ws.session, ws.gid, row, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid))["ok"]
    (link,) = ws.session.query(EntryAssets).filter_by(entry_id=article.id).all()
    assert link.asset_id == picture.id and link.role == "cover-variant"

    missing = _install(
        ws,
        {
            "trigger": {"type": "manual"},
            "actions": [{"kind": "entry", "op": "attach_asset", "entity_id": str(article.id), "asset": "no-such-picture"}],
        },
    )
    assert run_automation_now(ws.session, ws.gid, missing, user_id=ws.uid, recorder=ExecutionRecorder(ws.session, ws.gid))["ok"] is False
    assert draft_issues(ws.session, ws.gid, {"trigger": {"type": "manual"}, "actions": [{"kind": "entry", "op": "attach_asset"}]})  # needs `asset`
    # The fixture tears the user down and assets.uploaded_by is NOT NULL, so the pictures this test made go first.
    from marvin.db.models.platform import Assets

    ws.session.query(EntryAssets).filter_by(entry_id=article.id).delete(synchronize_session=False)
    ws.session.query(Assets).filter(Assets.group_id == ws.gid).delete(synchronize_session=False)
    ws.session.commit()


@pytest.mark.parametrize(("decision", "recorded"), [("deny", "denied"), ("approve", "approved")])
def test_the_decision_is_written_onto_the_pictured_asset(ws, decision, recorded):  # noqa: F811
    """Denied pictures stay in the library, so the asset itself carries what was said: who, when, the note."""
    from marvin.db.models.platform import Assets

    key = f"lib/cover-{uuid.uuid4().hex[:6]}"
    cover = Assets(
        session=ws.session, group_id=ws.gid, slug=key.split("/")[1], name="Cover", original_filename="cover.png", filename="cover",
        extension="png", file_size=10, mime_type="image/png", asset_type="image", checksum=key, storage_provider="local", storage_key=key,
        uploaded_by=ws.uid, origin="generated", metadata_json={"generated_by": "openai_images.generate"},
    )  # fmt: skip
    ws.session.add(cover)
    ws.session.commit()
    definition = {
        "trigger": {"type": "event", "event": "entry_published"},
        "actions": [{"kind": "approval", "id": "keep", "message": "Use this?", "image": f"https://cdn.test/{key}"}],
    }
    _install(ws, definition)
    article = _published(ws, f"Pictured {recorded}")
    _fire(ws, "entry_published", _entry_doc(article), entity=article.id, entity_type="entry", correlation_id=f"pic-{recorded}")

    row = approvals.decide(
        ws.session, ws.gid, _waiting(ws).id, decision, user_id=ws.uid, role=ROLE_EDITOR, note="too dark" if decision == "deny" else None
    )

    ws.session.expire_all()
    stamp = ws.session.get(Assets, cover.id).metadata_json["approval"]
    assert stamp["decision"] == recorded and stamp["decided_by"] == str(ws.uid) and stamp["approval_id"] == str(row.id)
    assert stamp["note"] == ("too dark" if decision == "deny" else None) and stamp["decided_at"]
    assert ws.session.get(Assets, cover.id).metadata_json["generated_by"] == "openai_images.generate"  # the lineage stays
    ws.session.delete(ws.session.get(Assets, cover.id))  # the fixture's user must be deletable afterwards
    ws.session.commit()
