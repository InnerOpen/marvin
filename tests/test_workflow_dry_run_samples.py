"""Event-aware dry run: an event-triggered workflow is dry-run against a sample event — a logged one
replayed, or one built for an entry — so `${entry.*}` / `$event.*` resolve, and the trigger and every
condition are checked and reported. Still executes, records and fires nothing."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.services.automation.matcher import explain, matches

HOOK_URL = "https://hooks.example.test/buttondown"
NEWSLETTER_CONDITION = {"field": "entry.entry_type", "op": "eq", "value": "newsletter-issue"}
SEND_ISSUE = {"kind": "webhook", "url": HOOK_URL, "body": {"subject": "${entry.title}", "body": "${entry.data.body}"}}


def _workspace(db_session, prefix: str) -> SimpleNamespace:
    from marvin.db.models.groups import Groups
    from marvin.db.models.platform import EntryTypes

    gid = uuid.uuid4()
    g = Groups(session=db_session, name=f"{prefix}-{gid.hex[:8]}", slug=f"{prefix}-{gid.hex[:8]}")
    g.id = gid
    db_session.add(g)
    db_session.flush()
    issue = EntryTypes(session=db_session, group_id=gid, name="Newsletter issue", slug="newsletter-issue", schema_json={})
    page = EntryTypes(session=db_session, group_id=gid, name="Page", slug="page", schema_json={})
    db_session.add_all([issue, page])
    db_session.commit()
    return SimpleNamespace(id=gid, types={"newsletter-issue": issue.id, "page": page.id})


def _entry(db_session, ws, etype: str, title: str, *, status="published", age_minutes=0, body=""):
    from marvin.db.models.platform import Entries

    e = Entries(
        session=db_session,
        group_id=ws.id,
        entry_type_id=ws.types[etype],
        title=title,
        slug=f"{title.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        status=status,
        data_json={"body": body},
    )
    db_session.add(e)
    db_session.flush()
    stamp = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=age_minutes)
    e.created_at = e.update_at = stamp
    db_session.commit()
    return e


def _log_published(ws, entry, etype: str, *, age_minutes=0):
    """Write the entry_published event to the event log the way the audit listener does."""
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventEntryData, EventOperation, EventTypes
    from marvin.services.event_bus_service.publisher import AuditLogPublisher

    event = Event(
        message=EventBusMessage.from_type(EventTypes.entry_published, body=f"Entry '{entry.title}' published"),
        event_type=EventTypes.entry_published,
        integration_id="entry_management",
        document_data=EventEntryData(
            operation=EventOperation.update,
            entry_id=entry.id,
            entry_title=entry.title,
            entry_type=etype,
            workspace_id=ws.id,
            changed_fields=["status"],
            before={"status": "draft"},
            after={"status": "published"},
        ),
        workspace_id=ws.id,
        entity_id=entry.id,
        entity_type="entry",
        timestamp=datetime.now(UTC) - timedelta(minutes=age_minutes),
    )
    AuditLogPublisher().publish(event, [])
    return event.event_id


def _log_row_id(db_session, event_id):
    from marvin.db.models.platform.event_log import EventLogModel

    return str(db_session.query(EventLogModel.id).filter(EventLogModel.event_id == event_id).scalar())


def _automation(db_session, ws, *, trigger=None, conditions=None, actions=None, target=None):
    from marvin.db.models.groups.automations import WorkspaceAutomationModel

    definition = {
        "trigger": trigger or {"type": "event", "event": "entry_published"},
        "conditions": [NEWSLETTER_CONDITION] if conditions is None else conditions,
        "actions": actions or [SEND_ISSUE],
    }
    if target:
        definition["target"] = target
    row = WorkspaceAutomationModel(
        session=db_session, group_id=ws.id, name="Send issue to Buttondown", slug=f"send-{uuid.uuid4().hex[:6]}", enabled=False, definition=definition
    )
    db_session.add(row)
    db_session.commit()
    return str(row.id)


def _drop(db_session, gid):
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.db.models.platform.event_log import EventLogModel

    db_session.rollback()
    for model, column in (
        (AutomationExecutionModel, AutomationExecutionModel.group_id),
        (WorkspaceAutomationModel, WorkspaceAutomationModel.group_id),
        (EventLogModel, EventLogModel.workspace_id),
        (Entries, Entries.group_id),
        (EntryTypes, EntryTypes.group_id),
        (Groups, Groups.id),
    ):
        db_session.query(model).filter(column == gid).delete(synchronize_session=False)
    db_session.commit()


@fixture
def workspaces(db_session):
    """Two workspaces; the caller is a workspace admin signed in to the first."""
    mine, theirs = _workspace(db_session, "dry"), _workspace(db_session, "dry-other")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), group_id=mine.id, active_group_id=mine.id, admin=True, is_superuser=False
    )
    yield mine, theirs
    app.dependency_overrides.pop(get_current_user, None)
    _drop(db_session, mine.id)
    _drop(db_session, theirs.id)


def _dry_run(automation_id, expect=200, **params):
    res = TestClient(app).post(f"/api/automations/{automation_id}/run", params={"dry_run": "true", **params})
    assert res.status_code == expect, res.text
    return res.json()


def _samples(automation_id, expect=200):
    res = TestClient(app).get(f"/api/automations/{automation_id}/samples")
    assert res.status_code == expect, res.text
    return res.json()


# ── Picking a sample ─────────────────────────────────────────────────────────


def test_dry_run_with_entry_id_resolves_entry_templates(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12", body="Hello readers")
    auto = _automation(db_session, mine)

    res = _dry_run(auto, entry_id=str(issue.id))

    assert res["plan"][0]["resolved"]["body"] == {"subject": "Issue 12", "body": "Hello readers"}


def test_dry_run_with_entry_id_and_no_logged_event_builds_the_event(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    auto = _automation(db_session, mine)

    sample = _dry_run(auto, entry_id=str(issue.id))["sample"]

    assert (sample["kind"], sample["id"], sample["synthesized"], sample["event_type"]) == ("entry", str(issue.id), True, "entry_published")


def test_dry_run_with_entry_id_prefers_its_logged_event(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    row_id = _log_row_id(db_session, _log_published(mine, issue, "newsletter-issue"))
    auto = _automation(db_session, mine)

    sample = _dry_run(auto, entry_id=str(issue.id))["sample"]

    assert (sample["kind"], sample["id"]) == ("event", row_id)


def test_dry_run_default_picks_latest_logged_event_whose_conditions_pass(db_session, workspaces):
    mine, _ = workspaces
    older_issue = _entry(db_session, mine, "newsletter-issue", "Issue 11", age_minutes=30, body="Old news")
    newer_page = _entry(db_session, mine, "page", "About", age_minutes=5)
    issue_row = _log_row_id(db_session, _log_published(mine, older_issue, "newsletter-issue", age_minutes=30))
    _log_published(mine, newer_page, "page", age_minutes=5)
    auto = _automation(db_session, mine)

    res = _dry_run(auto)

    assert res["sample"]["id"] == issue_row
    assert res["would_fire"] is True
    assert res["plan"][0]["resolved"]["body"] == {"subject": "Issue 11", "body": "Old news"}


def test_dry_run_default_falls_back_to_latest_event_flagged_as_failing(db_session, workspaces):
    mine, _ = workspaces
    page = _entry(db_session, mine, "page", "About")
    page_row = _log_row_id(db_session, _log_published(mine, page, "page"))
    auto = _automation(db_session, mine)

    res = _dry_run(auto)

    assert (res["sample"]["id"], res["sample"]["conditions_pass"]) == (page_row, False)


def test_dry_run_default_without_logged_events_uses_latest_matching_entry(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12", age_minutes=20)
    _entry(db_session, mine, "page", "About", age_minutes=10)
    _entry(db_session, mine, "newsletter-issue", "Issue 13 draft", status="draft", age_minutes=1)
    auto = _automation(db_session, mine)

    sample = _dry_run(auto)["sample"]

    assert (sample["kind"], sample["id"], sample["conditions_pass"]) == ("entry", str(issue.id), True)


def test_dry_run_with_no_sample_anywhere_says_so(db_session, workspaces):
    mine, _ = workspaces
    auto = _automation(db_session, mine)

    res = _dry_run(auto)

    assert res["sample"] is None and res["dry_run"] is True


# ── Reporting the gates ──────────────────────────────────────────────────────


def test_failing_condition_is_reported_with_its_values(db_session, workspaces):
    mine, _ = workspaces
    page = _entry(db_session, mine, "page", "About")
    auto = _automation(db_session, mine)

    res = _dry_run(auto, entry_id=str(page.id))

    assert res["would_fire"] is False
    assert res["conditions"] == [
        {"field": "entry.entry_type", "op": "eq", "value": "newsletter-issue", "actual": "page", "expected": "newsletter-issue", "pass": False}
    ]


def test_trigger_mismatch_is_reported(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    row_id = _log_row_id(db_session, _log_published(mine, issue, "newsletter-issue"))
    auto = _automation(db_session, mine, trigger={"type": "event", "event": "entry_archived"})

    res = _dry_run(auto, event_id=row_id)

    assert (res["trigger_matched"], res["would_fire"]) == (False, False)


def test_replayed_event_carries_its_change_diff(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    row_id = _log_row_id(db_session, _log_published(mine, issue, "newsletter-issue"))
    auto = _automation(db_session, mine, conditions=[{"field": "entry.status", "op": "changed_from", "value": "draft"}])

    res = _dry_run(auto, event_id=row_id)

    assert res["conditions"][0]["actual"] == "draft" and res["conditions_pass"] is True


def test_replayed_webhook_event_resolves_payload(db_session, workspaces):
    from marvin.services.event_bus_service.event_types import Event, EventBusMessage, EventIncomingWebhookData, EventOperation, EventTypes
    from marvin.services.event_bus_service.publisher import AuditLogPublisher

    mine, _ = workspaces
    event = Event(
        message=EventBusMessage.from_type(EventTypes.incoming_webhook),
        event_type=EventTypes.incoming_webhook,
        integration_id="incoming_webhook",
        document_data=EventIncomingWebhookData(
            operation=EventOperation.info,
            webhook_id=uuid.uuid4(),
            webhook_slug="square",
            webhook_name="Square",
            workspace_id=mine.id,
            payload={"type": "order.created", "data": {"id": "o-1"}},
        ),
        workspace_id=mine.id,
    )
    AuditLogPublisher().publish(event, [])
    auto = _automation(
        db_session,
        mine,
        trigger={"type": "incoming_webhook", "webhook": "square"},
        conditions=[{"field": "event.payload.type", "op": "eq", "value": "order.created"}],
        actions=[{"kind": "webhook", "url": HOOK_URL, "body": {"order": "${event.payload.data.id}"}}],
    )

    res = _dry_run(auto)

    assert res["would_fire"] is True and res["plan"][0]["resolved"]["body"] == {"order": "o-1"}


def test_target_workflow_reports_rows_not_conditions(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    _entry(db_session, mine, "page", "About")
    auto = _automation(db_session, mine, target={"entity": "entry", "query": {"entry_type": "newsletter-issue"}})

    res = _dry_run(auto, entry_id=str(issue.id))

    assert (res["conditions"], res["would_fire"], [s["target"]["title"] for s in res["plan"]]) == ([], True, ["Issue 12"])


# ── Side effects ─────────────────────────────────────────────────────────────


def test_dry_run_executes_records_and_fires_nothing(db_session, workspaces, monkeypatch):
    from marvin.db.models.groups.automation_executions import AutomationExecutionModel
    from marvin.db.models.platform.event_log import EventLogModel

    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    _log_published(mine, issue, "newsletter-issue")
    auto = _automation(db_session, mine)
    calls = []
    monkeypatch.setattr("httpx.request", lambda *a, **kw: calls.append(("http", a)))
    monkeypatch.setattr(
        "marvin.services.event_bus_service.event_bus_service.EventBusService.dispatch", lambda *a, **kw: calls.append(("event", kw.get("event_type")))
    )

    def counts():
        db_session.expire_all()
        return (
            db_session.query(AutomationExecutionModel).filter_by(group_id=mine.id).count(),
            db_session.query(EventLogModel).filter_by(workspace_id=mine.id).count(),
        )

    before = counts()
    _dry_run(auto)
    _dry_run(auto, entry_id=str(issue.id))

    assert (calls, counts()) == ([], before)


def test_dry_run_masks_literal_credentials_in_headers(db_session, workspaces):
    from marvin.db.models.groups.webhooks import GroupWebhooksModel

    mine, _ = workspaces
    hook = GroupWebhooksModel(
        session=db_session,
        group_id=mine.id,
        name="Buttondown",
        enabled=True,
        url=HOOK_URL,
        headers_json={"Authorization": "Token {{BUTTONDOWN_KEY}}", "X-Api-Key": "sk-live-123", "X-Source": "marvin"},
    )
    db_session.add(hook)
    db_session.commit()
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    auto = _automation(db_session, mine, actions=[{"kind": "webhook", "webhook_id": str(hook.id)}])

    headers = _dry_run(auto, entry_id=str(issue.id))["plan"][0]["resolved"]["headers"]

    db_session.delete(hook)
    db_session.commit()
    assert headers == {"Content-Type": "application/json", "Authorization": "Token {{BUTTONDOWN_KEY}}", "X-Api-Key": "••••••", "X-Source": "marvin"}


def test_dry_run_shows_secret_ref_auth_by_reference():
    from marvin.services.automation.actions.webhook import run_webhook

    out = run_webhook(None, "G", {"kind": "webhook", "url": HOOK_URL, "secret_ref": "{{BUTTONDOWN_KEY}}", "auth_scheme": "Token"}, {}, dry_run=True)

    assert out["headers"] == {"Content-Type": "application/json", "Authorization": "Token {{BUTTONDOWN_KEY}}"}


# ── Manual workflows ─────────────────────────────────────────────────────────


def test_manual_workflow_dry_run_is_unchanged(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    _log_published(mine, issue, "newsletter-issue")
    auto = _automation(db_session, mine, trigger={"type": "manual"}, actions=[{"kind": "webhook", "url": HOOK_URL, "body": {"t": "fixed"}}])

    res = _dry_run(auto)

    assert set(res) == {"status", "ok", "ran", "dry_run", "plan"} and res["plan"][0]["resolved"]["body"] == {"t": "fixed"}


def test_manual_workflow_rejects_a_sample(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    auto = _automation(db_session, mine, trigger={"type": "manual"})

    _dry_run(auto, expect=400, entry_id=str(issue.id))


def test_sample_needs_dry_run(db_session, workspaces):
    mine, _ = workspaces
    issue = _entry(db_session, mine, "newsletter-issue", "Issue 12")
    auto = _automation(db_session, mine)

    res = TestClient(app).post(f"/api/automations/{auto}/run", params={"entry_id": str(issue.id)})

    assert res.status_code == 400


# ── The picker's candidates ──────────────────────────────────────────────────


def test_samples_list_logged_events_then_uncovered_entries(db_session, workspaces):
    mine, _ = workspaces
    logged_issue = _entry(db_session, mine, "newsletter-issue", "Issue 11", age_minutes=30)
    page = _entry(db_session, mine, "page", "About", age_minutes=20)
    fresh_issue = _entry(db_session, mine, "newsletter-issue", "Issue 12", age_minutes=10)
    issue_row = _log_row_id(db_session, _log_published(mine, logged_issue, "newsletter-issue", age_minutes=30))
    auto = _automation(db_session, mine)

    listed = [(s["kind"], s["id"], s["conditions_pass"]) for s in _samples(auto)["samples"]]

    assert listed == [("event", issue_row, True), ("entry", str(fresh_issue.id), True), ("entry", str(page.id), False)]


def test_samples_are_workspace_scoped(db_session, workspaces):
    mine, theirs = workspaces
    their_issue = _entry(db_session, theirs, "newsletter-issue", "Their issue")
    _log_published(theirs, their_issue, "newsletter-issue")
    auto = _automation(db_session, mine)

    assert _samples(auto)["samples"] == []


def test_another_workspaces_entry_or_event_is_not_found(db_session, workspaces):
    mine, theirs = workspaces
    their_issue = _entry(db_session, theirs, "newsletter-issue", "Their issue")
    their_row = _log_row_id(db_session, _log_published(theirs, their_issue, "newsletter-issue"))
    auto = _automation(db_session, mine)

    _dry_run(auto, expect=404, entry_id=str(their_issue.id))
    _dry_run(auto, expect=404, event_id=their_row)


def test_another_workspaces_workflow_samples_are_not_found(db_session, workspaces):
    _, theirs = workspaces
    auto = _automation(db_session, theirs)

    _samples(auto, expect=404)


# ── The checklist mirrors matching ───────────────────────────────────────────


class TestExplain:
    CTX = {"event": {"changed_fields": ["status"], "before": {"status": "draft"}}, "entry": {"entry_type": "page", "title": "About"}}

    def test_nested_groups_report_each_leaf_and_agree_with_matches(self):
        conditions = [
            {"any": [NEWSLETTER_CONDITION, {"field": "entry.title", "op": "starts_with", "value": "Ab"}]},
            {"not": {"field": "entry.status", "op": "changed_from", "value": "published"}},
        ]

        nodes = explain(conditions, self.CTX)

        assert [n["pass"] for n in nodes[0]["children"]] == [False, True]
        assert all(n["pass"] for n in nodes) == matches(conditions, self.CTX) is True

    def test_changed_reports_the_changed_fields(self):
        (node,) = explain([{"field": "entry.status", "op": "changed"}], self.CTX)

        assert (node["actual"], node["expected"], node["pass"]) == (["status"], "status", True)

    def test_no_conditions_is_an_empty_checklist(self):
        assert explain(None, self.CTX) == []
