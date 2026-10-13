"""End to end: a signup the newsletter provider refuses goes to Needs review with its reason.

The shape of the Buttondown integration's `subscribe-on-signup` workflow, run by the real engine on a
real entry: the integration step fails with the provider's coded error, and the workflow's on_failure
steps record it on the entry and send the entry to review. The run history keeps it as a failed run.
"""

import uuid

import pytest
from pytest import fixture

pytest.importorskip("marvin_integration_sdk", reason="integrations SDK not installed (optional feature)")

from marvin_integration_sdk import INTEGRATION_REGISTRY, IntegrationProvider, ProviderAction  # noqa: E402

from marvin.services.automation.engine import run_automations_for_event  # noqa: E402
from marvin.services.automation.recorder import ExecutionRecorder  # noqa: E402

BLOCKED = "blocked@example.com"

SIGNUP_WORKFLOW = {
    "trigger": {"type": "event", "event": "form_submission_received"},
    "conditions": [{"field": "entry.entry_type", "op": "eq", "value": "newsletter"}],
    "actions": [
        {"kind": "integration", "id": "subscribe", "integration": "news", "action": "subscribe", "args": {"email": "${event.submission_data.email}"}},
        {"kind": "entry", "op": "set_metadata", "metadata": {"subscriber_id": "${steps.subscribe.output.subscriber_id}"}},
    ],
    "on_failure": [
        {
            "kind": "entry",
            "op": "set_metadata",
            "metadata": {"subscribe_error": {"code": "${error.code}", "message": "${error.message}", "at": "${error.at}"}},
        },
        {"kind": "entry", "op": "request_review", "reason": "${error.message}"},
    ],
}


class _Refused(ValueError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class _Newsletter(IntegrationProvider):
    slug = "fake_newsletter"
    name = "Fake newsletter"
    actions = (ProviderAction(key="subscribe", label="Subscribe"),)

    def run_action(self, key, args, ctx):
        if args["email"] == BLOCKED:
            raise _Refused(f"the spam firewall refused {BLOCKED}", "blocked")
        return {"subscriber_id": "sub_1"}


@fixture
def workspace(db_session, monkeypatch):
    """A workspace with the newsletter connection, the signup workflow (on) and one signup per address."""
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform import Entries, EntryTypes

    monkeypatch.setitem(INTEGRATION_REGISTRY, _Newsletter.slug, _Newsletter())
    gid = uuid.uuid4()
    marker = gid.hex[:8]
    group = Groups(session=db_session, name=f"signup-{marker}", slug=f"signup-{marker}")
    group.id = gid
    db_session.add(group)
    db_session.flush()
    db_session.add(IntegrationModel(session=db_session, group_id=gid, provider=_Newsletter.slug, name="news", slug="news", enabled=True, config={}))
    db_session.add(
        WorkspaceAutomationModel(
            session=db_session, group_id=gid, name="Subscribe", slug="subscribe-on-signup", enabled=True, definition=SIGNUP_WORKFLOW
        )
    )
    et = EntryTypes(session=db_session, group_id=gid, name="Newsletter", slug="newsletter", schema_json={"fields": []})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entries = {}
    for email in (BLOCKED, "reader@example.com"):
        entry = Entries(
            session=db_session,
            group_id=gid,
            entry_type_id=et.id,
            title=email,
            slug=f"{email.split('@')[0]}-{marker}",
            data_json={"email": email},
            status="inbox",
        )
        db_session.add(entry)
        db_session.flush()
        entries[email] = entry.id
    db_session.commit()
    yield gid, entries

    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    db_session.query(AutomationActionExecutionModel).filter(AutomationActionExecutionModel.group_id == gid).delete()
    db_session.query(AutomationExecutionModel).filter(AutomationExecutionModel.group_id == gid).delete()
    db_session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == gid).delete()
    purge_group_dependents(db_session, gid)
    db_session.query(Groups).filter(Groups.id == gid).delete()
    db_session.commit()


def _submit(db_session, gid, entry_id, email):
    event = {"event_type": "form_submission_received", "entry_id": str(entry_id), "submission_data": {"email": email}, "user_id": None}
    run_automations_for_event(db_session, gid, event, recorder=ExecutionRecorder(db_session, gid))
    db_session.expire_all()


def test_refused_signup_goes_to_needs_review_with_the_reason(db_session, workspace):
    from marvin.db.models.platform import Entries

    gid, entries = workspace

    _submit(db_session, gid, entries[BLOCKED], BLOCKED)

    entry = db_session.get(Entries, entries[BLOCKED])
    assert entry.status == "needs_review"
    error = entry.metadata_json["subscribe_error"]
    assert (error["code"], error["message"]) == ("blocked", f"fake_newsletter.subscribe failed: the spam firewall refused {BLOCKED}")
    assert error["at"]
    assert entry.metadata_json["review_reasons"] == [error["message"]]
    assert "subscriber_id" not in entry.metadata_json


def test_refused_signup_run_is_recorded_failed_with_its_on_failure_steps(db_session, workspace):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel

    gid, entries = workspace

    _submit(db_session, gid, entries[BLOCKED], BLOCKED)

    run = db_session.query(AutomationExecutionModel).filter(AutomationExecutionModel.group_id == gid).one()
    assert (run.status, run.steps_ok, run.steps_failed) == ("failed", 0, 1)
    assert [(s.action_index, s.status, s.label) for s in run.actions] == [
        (0, "failed", "news.subscribe"),
        (2, "success", "on failure: set_metadata"),
        (3, "success", "on failure: request_review"),
    ]


def test_accepted_signup_is_unchanged(db_session, workspace):
    from marvin.db.models.platform import Entries

    gid, entries = workspace

    _submit(db_session, gid, entries["reader@example.com"], "reader@example.com")

    entry = db_session.get(Entries, entries["reader@example.com"])
    assert entry.status == "inbox"
    assert entry.metadata_json == {"subscriber_id": "sub_1"}
