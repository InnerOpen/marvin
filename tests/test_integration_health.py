"""The Alerts & health page: open/resolved alerts, live retries (retry now, give up), handled failures and
the per-connection summary (services/integrations/health.py, and its routes on the integrations controller).

The service half is SDK-free and runs everywhere. The API half needs the integrations controller, which
is only mounted when marvin_integration_sdk is installed, so it skips without it (CI runs without it).
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import fixture

from marvin.app import app
from marvin.core.dependencies import get_current_user
from marvin.db.models.users.roles import PlatformRole, WorkspaceRole
from marvin.services.integrations import INTEGRATIONS_AVAILABLE, errors, health

NEEDS_SDK = pytest.mark.skipif(not INTEGRATIONS_AVAILABLE, reason="integration routes need marvin_integration_sdk")
API = "/api/groups/integrations"


def _now() -> datetime:
    return datetime.now(UTC)


# "Due now", give or take a wall clock that steps (WSL2 re-syncs its clock and can jump back seconds mid-test):
# what matters is that the retry moved from its scheduled time (minutes away) to about now.
NOW_SLACK = timedelta(seconds=30)


def _group(db_session, prefix: str):
    from marvin.db.models.groups import Groups

    gid = uuid.uuid4()
    slug = f"{prefix}-{gid.hex[:8]}"
    group = Groups(session=db_session, name=slug, slug=slug)
    group.id = gid
    db_session.add(group)
    db_session.flush()
    return gid, slug


def _workspace(db_session, prefix: str):
    """A workspace with a user, a connection, a workflow and an entry."""
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform import Entries, EntryTypes
    from marvin.db.models.users.users import Users

    gid, slug = _group(db_session, prefix)
    uid = uuid.uuid4()
    db_session.execute(
        Users.__table__.insert().values(
            id=uid,
            group_id=gid,
            username=slug,
            email=f"{slug}@t.test",
            full_name="Ada Admin",
            password="x",
            is_superuser=False,
            platform_role="NONE",
            auth_method="MARVIN",
        )
    )
    integration = IntegrationModel(session=db_session, group_id=gid, provider="fake_shop", name="Shop", slug="shop", enabled=True, config={})
    db_session.add(integration)
    automation = WorkspaceAutomationModel(
        session=db_session,
        group_id=gid,
        name="List it",
        slug="list-it",
        enabled=True,
        definition={"trigger": {"type": "manual"}, "actions": [{"kind": "integration", "integration": "shop", "action": "create_listing"}]},
    )
    db_session.add(automation)
    et = EntryTypes(session=db_session, group_id=gid, name="Product", slug="product", schema_json={"fields": []})
    et.id = uuid.uuid4()
    db_session.add(et)
    db_session.flush()
    entry = Entries(session=db_session, group_id=gid, entry_type_id=et.id, title="Mug", slug=f"mug-{slug}", data_json={}, status="draft")
    db_session.add(entry)
    db_session.commit()
    return SimpleNamespace(gid=gid, uid=uid, slug=slug, integration=integration, automation=automation, entry_id=entry.id)


def _purge(db_session, ws) -> None:
    from marvin.db.models.groups import Groups
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel
    from marvin.db.models.groups.automations import WorkspaceAutomationModel
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel, IntegrationRetryModel
    from marvin.db.models.groups.integrations import IntegrationModel
    from marvin.db.models.platform import Entries
    from marvin.db.models.users.users import Users
    from marvin.services.group.group_purge import purge_group_dependents

    db_session.rollback()
    for model in (IntegrationRetryModel, IntegrationAlertModel, AutomationActionExecutionModel, AutomationExecutionModel):
        db_session.query(model).filter(model.group_id == ws.gid).delete()
    db_session.query(WorkspaceAutomationModel).filter(WorkspaceAutomationModel.group_id == ws.gid).delete()
    db_session.query(Entries).filter(Entries.group_id == ws.gid).delete()
    db_session.query(IntegrationModel).filter(IntegrationModel.group_id == ws.gid).delete()
    purge_group_dependents(db_session, ws.gid)
    db_session.query(Users).filter(Users.id == ws.uid).delete()
    db_session.query(Groups).filter(Groups.id == ws.gid).delete()
    db_session.commit()


@fixture
def ws(db_session):
    workspace = _workspace(db_session, "health")
    yield workspace
    app.dependency_overrides.pop(get_current_user, None)
    _purge(db_session, workspace)


@fixture
def other(db_session):
    workspace = _workspace(db_session, "other")
    yield workspace
    _purge(db_session, workspace)


@fixture
def events(monkeypatch):
    sent = []

    def dispatch(self, integration_id, group_id, event_type, document_data, message="", **kw):
        sent.append(event_type.name)

    monkeypatch.setattr("marvin.services.event_bus_service.event_bus_service.EventBusService.dispatch", dispatch)
    return sent


def _alert(db_session, ws, code="auth", *, status="open", first_at=None, resolved_at=None, resolution=None, resolved_by=None, count=3):
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel

    first_at = first_at or _now() - timedelta(hours=2)
    row = IntegrationAlertModel(
        session=db_session,
        group_id=ws.gid,
        integration_id=ws.integration.id,
        integration_slug="shop",
        provider="fake_shop",
        code=code,
        status=status,
        open_key=f"{ws.integration.id}:{code}" if status == "open" else None,
        message="The key was refused",
        count=count,
        first_at=first_at,
        last_at=first_at + timedelta(minutes=30),
        notified_at=first_at,
        samples=[{"message": "The key was refused"}],
        channels={"email": []},
        resolved_at=resolved_at,
        resolution=resolution,
        resolved_by=resolved_by,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _retry(db_session, ws, *, status="pending", step_index=0, attempt=0, max_attempts=3, due=None, lease_until=None, entry=True, **extra):
    from marvin.db.models.groups.integration_errors import IntegrationRetryModel

    entry_id = ws.entry_id if entry else None
    row = IntegrationRetryModel(
        session=db_session,
        group_id=ws.gid,
        automation_id=ws.automation.id,
        integration_id=ws.integration.id,
        entry_id=entry_id,
        integration_slug="shop",
        provider="fake_shop",
        action="create_listing",
        step_index=step_index,
        code="unavailable",
        codes=["unavailable"],
        status=status,
        live_key=f"{ws.automation.id}:{entry_id}:{step_index}" if status in ("pending", "parked", "running") else None,
        attempt=attempt,
        max_attempts=max_attempts,
        next_attempt_at=due if due is not None else (_now() + timedelta(minutes=10) if status == "pending" else None),
        lease_until=lease_until,
        handle={"retry": {"backoff": [60, 120, 300], "max_attempts": 3}, "then": {"review": True}},
        snapshot={"entry": {"id": str(entry_id), "title": "Mug (as the run saw it)"}, "secret": "never-shown"},
        partial={"item_id": "I1"},
        idempotency_seed="seed-secret",
        last_error="Shop is down",
        **extra,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _step(db_session, ws, *, handling, status="failed", at=None, entry=True, retry_of=None, label="shop.create_listing", kind="integration"):
    """One recorded run with one step."""
    from marvin.db.models.groups.automation_executions import AutomationActionExecutionModel, AutomationExecutionModel

    at = at or _now()
    run = AutomationExecutionModel(
        session=db_session,
        group_id=ws.gid,
        automation_id=ws.automation.id,
        automation_slug="list-it",
        trigger_type="manual",
        status="failed" if status == "failed" else "success",
        started_at=at,
        handled=handling is not None,
        retry_of_id=retry_of,
    )
    db_session.add(run)
    db_session.flush()
    step = AutomationActionExecutionModel(
        session=db_session,
        execution_id=run.id,
        group_id=ws.gid,
        kind=kind,
        label=label,
        status=status,
        error="Shop is down" if status == "failed" else None,
        target_entity_type="entry" if entry else None,
        target_entity_id=str(ws.entry_id) if entry else None,
        handling=handling,
    )
    step.created_at = at
    db_session.add(step)
    db_session.commit()
    return run, step


def _handling(applied, *, retry_row=None, summary="handled by Fake Shop: sent to review", code="unavailable"):
    record = {
        "code": code,
        "integration": "shop",
        "provider": "fake_shop",
        "provider_name": "Fake Shop",
        "mode": "policy",
        "policy": {},
        "applied": applied,
        "summary": summary,
    }
    if retry_row is not None:
        record["retry"] = {"id": str(retry_row.id), "status": "pending", "attempt": 0, "max_attempts": 3, "next_attempt_at": None}
    return record


# ── alerts ──────────────────────────────────────────────────────────────────────


def test_open_alerts_show_counts_times_and_reminder_state(db_session, ws, other):
    _alert(db_session, ws, "auth")
    _alert(db_session, other, "auth")  # another workspace's alert never shows

    page = health.list_alerts(db_session, ws.gid, status="open")

    assert page.total == 1 and page.page == 1
    (alert,) = page.items
    assert (alert.code, alert.count, alert.status, alert.integration_name, alert.message) == ("auth", 3, "open", "Shop", "The key was refused")
    assert alert.provider == "fake_shop" and alert.first_at and alert.last_at
    # Reminders default to 24h: the next failure after notified_at + 24h is announced again.
    assert alert.reminder_hours == 24
    assert alert.remind_after == alert.notified_at + timedelta(hours=24)
    assert alert.open_seconds is None and alert.resolution is None


def test_reminders_off_means_no_remind_after(db_session, ws):
    from marvin.db.models.groups.preferences import GroupPreferencesModel

    _alert(db_session, ws)
    prefs = db_session.query(GroupPreferencesModel).filter_by(group_id=ws.gid).first()
    if prefs is None:
        prefs = GroupPreferencesModel(session=db_session, group_id=ws.gid)
        db_session.add(prefs)
    prefs.integration_alert_reminder_hours = 0
    db_session.commit()

    (alert,) = health.list_alerts(db_session, ws.gid).items
    assert alert.reminder_hours == 0 and alert.remind_after is None


def test_alert_history_says_how_long_each_was_open_and_how_it_resolved(db_session, ws):
    start = _now() - timedelta(days=1)
    _alert(db_session, ws, "auth", status="resolved", first_at=start, resolved_at=start + timedelta(hours=5), resolution="manual", resolved_by=ws.uid)
    _alert(db_session, ws, "unavailable", status="resolved", first_at=start, resolved_at=start + timedelta(minutes=7), resolution="check")
    _alert(db_session, ws, "rate_limited")  # still open: not history

    page = health.list_alerts(db_session, ws.gid, status="resolved")

    assert page.total == 2
    latest, earlier = page.items
    assert (latest.code, latest.resolution, latest.resolved_by_name, latest.open_seconds) == ("auth", "manual", "Ada Admin", 5 * 3600)
    assert (earlier.code, earlier.resolution, earlier.resolved_by_name, earlier.open_seconds) == ("unavailable", "check", None, 7 * 60)
    assert latest.remind_after is None


def test_alerts_paginate(db_session, ws):
    start = _now() - timedelta(days=2)
    for i in range(5):
        _alert(db_session, ws, f"code{i}", status="resolved", first_at=start, resolved_at=start + timedelta(minutes=i + 1), resolution="action")

    first = health.list_alerts(db_session, ws.gid, status="resolved", page=1, per_page=2)
    third = health.list_alerts(db_session, ws.gid, status="resolved", page=3, per_page=2)
    beyond = health.list_alerts(db_session, ws.gid, status="resolved", page=9, per_page=2)

    assert (first.total, len(first.items), [a.code for a in first.items]) == (5, 2, ["code4", "code3"])
    assert [a.code for a in third.items] == ["code0"]
    assert beyond.items == [] and beyond.total == 5
    assert health.list_alerts(db_session, ws.gid, status="resolved", per_page=10_000).per_page == health.MAX_PER_PAGE


# ── retries ─────────────────────────────────────────────────────────────────────


def test_live_retries_running_then_due_then_parked_and_never_their_secrets(db_session, ws, other):
    parked = _retry(db_session, ws, status="parked", step_index=2)
    pending = _retry(db_session, ws, status="pending", step_index=1, attempt=1)
    running = _retry(db_session, ws, status="running", step_index=0, lease_until=_now() + timedelta(minutes=5))
    _retry(db_session, ws, status="succeeded", step_index=3)  # history
    _retry(db_session, other, status="pending")

    rows = health.list_retries(db_session, ws.gid)

    assert [r.id for r in rows] == [running.id, pending.id, parked.id]
    item = rows[1]
    assert (item.attempt, item.max_attempts, item.code, item.action, item.integration_name) == (1, 3, "unavailable", "create_listing", "Shop")
    assert (item.automation_name, item.automation_enabled, item.entry_title, item.entry_exists) == ("List it", True, "Mug", True)
    dumped = str([r.model_dump() for r in rows])
    for secret in ("seed-secret", "never-shown", "item_id"):
        assert secret not in dumped


def test_a_retry_whose_entry_is_gone_shows_the_title_the_run_saw(db_session, ws):
    from marvin.db.models.platform import Entries

    _retry(db_session, ws)
    db_session.query(Entries).filter(Entries.id == ws.entry_id).delete()
    db_session.commit()

    (row,) = health.list_retries(db_session, ws.gid)
    assert row.entry_exists is False and row.entry_title == "Mug (as the run saw it)"


def test_retry_now_makes_a_pending_retry_due_without_running_it(db_session, ws):
    row = _retry(db_session, ws, status="pending", attempt=1)

    read = health.retry_now(db_session, ws.gid, row.id)

    db_session.refresh(row)
    assert row.status == "pending" and row.attempt == 1  # nothing ran: the sweep picks it up
    assert abs(errors._aware(row.next_attempt_at) - _now()) < NOW_SLACK  # was _now() + 10 minutes
    assert read.status == "pending" and abs(read.next_attempt_at - _now()) < NOW_SLACK
    # …and the sweep's claim takes it on its next tick (about a minute on).
    claimed = errors.claim_next(db_session, now=_now() + timedelta(minutes=1))
    assert claimed is not None and claimed.id == row.id and claimed.attempt == 2


def test_retry_now_unparks_a_retry_waiting_for_recovery(db_session, ws):
    row = _retry(db_session, ws, status="parked")
    health.retry_now(db_session, ws.gid, row.id)
    db_session.refresh(row)
    assert row.status == "pending" and abs(errors._aware(row.next_attempt_at) - _now()) < NOW_SLACK


def test_retry_now_refuses_a_running_retry_and_leaves_its_lease_alone(db_session, ws):
    lease = _now() + timedelta(minutes=4)
    row = _retry(db_session, ws, status="running", attempt=1, lease_until=lease)

    with pytest.raises(health.RetryConflict, match="running"):
        health.retry_now(db_session, ws.gid, row.id)

    db_session.refresh(row)
    assert row.status == "running" and row.attempt == 1 and abs((errors._aware(row.lease_until) - lease).total_seconds()) < 1


def test_retry_now_refuses_a_finished_retry_and_another_workspaces(db_session, ws, other):
    done = _retry(db_session, ws, status="succeeded")
    theirs = _retry(db_session, other, status="pending")

    with pytest.raises(health.RetryConflict, match="finished"):
        health.retry_now(db_session, ws.gid, done.id)
    assert health.retry_now(db_session, ws.gid, theirs.id) is None
    assert health.give_up(db_session, ws.gid, theirs.id) is None
    db_session.refresh(theirs)
    assert theirs.status == "pending"
    assert health.retry_now(db_session, ws.gid, uuid.uuid4()) is None


def test_give_up_ends_the_chain_and_applies_nothing_else(db_session, ws, events):
    from marvin.db.models.groups.integration_errors import IntegrationAlertModel
    from marvin.db.models.platform import Entries

    row = _retry(db_session, ws, status="pending")

    read = health.give_up(db_session, ws.gid, row.id)

    db_session.refresh(row)
    assert (row.status, row.live_key, row.next_attempt_at, row.last_error) == ("superseded", None, None, health.GIVEN_UP)
    assert row.finished_at is not None and read.status == "superseded"
    # Its `then` (review) never ran: no alert, no review, no events.
    assert db_session.query(IntegrationAlertModel).filter_by(group_id=ws.gid).count() == 0
    assert db_session.get(Entries, ws.entry_id).status == "draft"
    assert events == []
    assert health.list_retries(db_session, ws.gid) == []
    # The step can get a new live retry later (the live key is free again).
    _retry(db_session, ws, status="pending")


def test_give_up_refuses_a_running_retry_until_its_lease_runs_out(db_session, ws):
    row = _retry(db_session, ws, status="running", attempt=1, lease_until=_now() + timedelta(minutes=4))

    with pytest.raises(health.RetryConflict, match="running"):
        health.give_up(db_session, ws.gid, row.id)
    db_session.refresh(row)
    assert row.status == "running"

    row.lease_until = _now() - timedelta(seconds=5)  # the run died mid-way: the sweep would reclaim it
    db_session.commit()
    health.give_up(db_session, ws.gid, row.id)
    db_session.refresh(row)
    assert row.status == "superseded"


def test_a_claim_never_revives_a_retry_given_up_after_it_was_picked(db_session, ws, monkeypatch):
    """The sweep picks a due row, then claims it with a conditional update: a give-up in between wins."""
    from sqlalchemy.orm import Query

    row = _retry(db_session, ws, status="pending", due=_now() - timedelta(seconds=5))
    real_update = Query.update
    raced = []

    def update(self, values, *args, **kwargs):
        is_claim = any(getattr(key, "key", None) == "attempt" for key in values)
        if is_claim and not raced:  # the sweep has picked the row; an admin gives it up before the claim lands
            raced.append(True)
            health.give_up(db_session, ws.gid, row.id)
        return real_update(self, values, *args, **kwargs)

    monkeypatch.setattr(Query, "update", update)
    claimed = errors.claim_next(db_session)
    monkeypatch.undo()

    assert raced and (claimed is None or claimed.id != row.id)
    db_session.refresh(row)
    assert (row.status, row.attempt, row.lease_until) == ("superseded", 0, None)


# ── handled failures ────────────────────────────────────────────────────────────


def test_handled_failures_read_as_one_line_with_links(db_session, ws, other):
    succeeded = _retry(db_session, ws, status="succeeded", attempt=1, step_index=5)
    pending = _retry(db_session, ws, status="pending", attempt=1, step_index=6)
    _step(db_session, ws, handling=_handling(["review"]), at=_now() - timedelta(hours=3))
    _step(db_session, ws, handling=_handling(["retry"], retry_row=succeeded, code="rate_limited"), at=_now() - timedelta(hours=2))
    _step(db_session, ws, handling=_handling(["notify", "retry"], retry_row=pending), at=_now() - timedelta(hours=1))
    _step(db_session, ws, handling=None)  # a plain failure isn't "handled"
    _step(db_session, ws, handling=_handling(["review"]), at=_now() - timedelta(days=8))  # too old
    _step(db_session, other, handling=_handling(["review"]))

    page = health.handled_failures(db_session, ws.gid)

    assert page.total == 3
    newest, middle, oldest = page.items
    assert newest.outcome == "admins notified, retry 2 of 3 scheduled" and newest.retry_status == "pending"
    assert (middle.code, middle.outcome, middle.retry_status) == ("rate_limited", "retried, succeeded on retry 1", "succeeded")
    assert oldest.outcome == "sent to review" and oldest.retry_status is None
    assert (oldest.provider_name, oldest.integration_slug, oldest.integration_id, oldest.action) == (
        "Fake Shop",
        "shop",
        ws.integration.id,
        "create_listing",
    )
    assert (oldest.automation_id, oldest.automation_name, oldest.entry_id, oldest.entry_title, oldest.entry_exists) == (
        ws.automation.id,
        "List it",
        ws.entry_id,
        "Mug",
        True,
    )
    assert oldest.execution_id and oldest.run_status == "failed" and oldest.error == "Shop is down"


def test_handled_failures_outcome_falls_back_to_the_stored_summary(db_session, ws):
    gone = SimpleNamespace(id=uuid.uuid4())  # the retry row was pruned
    _step(db_session, ws, handling=_handling(["retry"], retry_row=gone, summary="handled by Fake Shop: retry 1 of 3 scheduled"))
    (item,) = health.handled_failures(db_session, ws.gid).items
    assert item.outcome == "retry 1 of 3 scheduled"


def test_handled_failures_since_and_pagination(db_session, ws):
    for hours in range(1, 6):
        _step(db_session, ws, handling=_handling(["review"], code=f"c{hours}"), at=_now() - timedelta(hours=hours))

    first = health.handled_failures(db_session, ws.gid, per_page=2)
    last = health.handled_failures(db_session, ws.gid, page=3, per_page=2)
    recent = health.handled_failures(db_session, ws.gid, since=_now() - timedelta(hours=2, minutes=30))

    assert (first.total, [i.code for i in first.items]) == (5, ["c1", "c2"])
    assert [i.code for i in last.items] == ["c5"]
    assert [i.code for i in recent.items] == ["c1", "c2"]


def test_a_retry_run_is_marked(db_session, ws):
    original, _ = _step(db_session, ws, handling=_handling(["retry"]), at=_now() - timedelta(hours=1))
    _step(db_session, ws, handling=_handling(["exhausted", "review"]), retry_of=original.id)
    newest, oldest = health.handled_failures(db_session, ws.gid).items
    assert newest.is_retry is True and newest.outcome == "sent to review, retries used up"
    assert oldest.is_retry is False


# ── health summary ──────────────────────────────────────────────────────────────


def test_health_summary_per_connection(db_session, ws, other, events):
    from marvin.db.models.groups.integrations import IntegrationModel

    quiet = IntegrationModel(session=db_session, group_id=ws.gid, provider="fake_mail", name="Mail", slug="mail", enabled=False, config={})
    db_session.add(quiet)
    db_session.commit()
    _alert(db_session, ws, "auth")
    _retry(db_session, ws, status="pending")
    _retry(db_session, ws, status="parked", step_index=1)
    _retry(db_session, ws, status="exhausted", step_index=2)
    _step(db_session, ws, handling=None)  # failed
    _step(db_session, ws, handling=_handling(["succeed"]), status="success")  # ignored failure: still a failure
    _step(db_session, ws, handling=None, status="success")  # worked
    _step(db_session, ws, handling=None, label="on failure: shop.create_listing")  # an on-failure step of this connection
    _step(db_session, ws, handling=None, at=_now() - timedelta(days=9))  # too old
    _step(db_session, other, handling=None)

    errors.connection_succeeded(ws.gid, ws.integration.id, session=db_session)  # an action worked (resolves the alert too)
    _alert(db_session, ws, "rate_limited")

    rows = {r.slug: r for r in health.health(db_session, ws.gid)}

    assert set(rows) == {"shop", "mail"}
    shop, mail = rows["shop"], rows["mail"]
    assert (shop.failures_7d, shop.open_alerts, shop.alert_codes, shop.live_retries) == (3, 1, ["rate_limited"], 2)
    assert shop.last_success_at is not None and _now() - shop.last_success_at < timedelta(minutes=1)
    assert (mail.failures_7d, mail.open_alerts, mail.live_retries, mail.last_success_at, mail.enabled) == (0, 0, 0, None, False)
    if not INTEGRATIONS_AVAILABLE:
        assert shop.status == "unavailable"


def test_a_passing_check_is_not_a_successful_action(db_session, ws):
    from marvin.db.models.groups.integrations import IntegrationModel

    errors.connection_succeeded(ws.gid, ws.integration.id, resolution="check", session=db_session)
    db_session.expire_all()
    assert db_session.get(IntegrationModel, ws.integration.id).last_success_at is None


# ── API ─────────────────────────────────────────────────────────────────────────


def _sign_in(ws, role: WorkspaceRole | None) -> TestClient:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ws.uid,
        group_id=ws.gid,
        active_group_id=ws.gid,
        admin=False,
        is_superuser=False,
        full_name="Ada Admin",
        email=f"{ws.slug}@t.test",
        platform_role=PlatformRole.NONE,
        workspace_memberships=[],
        get_workspace_role=lambda group_id: role if str(group_id) == str(ws.gid) else None,
    )
    return TestClient(app)


NOPE = "00000000-0000-4000-8000-000000000000"
ROUTES = [
    ("GET", f"{API}/health"),
    ("GET", f"{API}/alerts"),
    ("GET", f"{API}/alerts?status=resolved"),
    ("GET", f"{API}/retries"),
    ("POST", f"{API}/retries/{NOPE}/retry-now"),
    ("POST", f"{API}/retries/{NOPE}/give-up"),
    ("GET", f"{API}/handled-failures"),
]


@NEEDS_SDK
@pytest.mark.parametrize("role", [WorkspaceRole.EDITOR, WorkspaceRole.AUTHOR, WorkspaceRole.VIEWER, None])
@pytest.mark.parametrize("route", ROUTES, ids=[f"{m} {p}" for m, p in ROUTES])
def test_api_is_admin_only(ws, role, route):
    assert _sign_in(ws, role).request(*route).status_code == 403


@NEEDS_SDK
def test_api_shapes(db_session, ws, other):
    _alert(db_session, ws)
    retry = _retry(db_session, ws)
    _step(db_session, ws, handling=_handling(["review"]))
    _alert(db_session, other)
    _retry(db_session, other)
    client = _sign_in(ws, WorkspaceRole.ADMIN)

    rows = client.get(f"{API}/health").json()
    assert [r["slug"] for r in rows] == ["shop"]
    assert {"lastSuccessAt", "lastCheckedAt", "failures7d", "openAlerts", "alertCodes", "liveRetries", "providerName"} <= set(rows[0])

    alerts = client.get(f"{API}/alerts").json()
    assert (alerts["total"], alerts["page"], alerts["perPage"]) == (1, 1, 25)
    assert {"remindAfter", "firstAt", "lastAt", "count", "code", "message", "integrationId"} <= set(alerts["items"][0])
    assert client.get(f"{API}/alerts?status=resolved").json()["items"] == []
    assert client.get(f"{API}/alerts?status=bogus").status_code == 422

    retries = client.get(f"{API}/retries").json()
    assert [r["id"] for r in retries] == [str(retry.id)]
    assert {"attempt", "maxAttempts", "nextAttemptAt", "automationId", "entryId", "status"} <= set(retries[0])
    assert "snapshot" not in retries[0] and "partial" not in retries[0] and "idempotencySeed" not in retries[0]

    failures = client.get(f"{API}/handled-failures?per_page=1").json()
    assert (failures["total"], failures["perPage"], len(failures["items"])) == (1, 1, 1)
    assert failures["items"][0]["outcome"] == "sent to review" and failures["since"]


@NEEDS_SDK
def test_api_retry_levers(db_session, ws, other):
    pending = _retry(db_session, ws, status="pending")
    running = _retry(db_session, ws, status="running", step_index=1, attempt=1, lease_until=_now() + timedelta(minutes=4))
    theirs = _retry(db_session, other, status="pending")
    client = _sign_in(ws, WorkspaceRole.OWNER)

    res = client.post(f"{API}/retries/{pending.id}/retry-now")
    assert res.status_code == 200 and res.json()["status"] == "pending"
    assert client.post(f"{API}/retries/{running.id}/retry-now").status_code == 409
    assert client.post(f"{API}/retries/{running.id}/give-up").status_code == 409
    assert client.post(f"{API}/retries/{theirs.id}/retry-now").status_code == 404
    assert client.post(f"{API}/retries/{theirs.id}/give-up").status_code == 404

    res = client.post(f"{API}/retries/{pending.id}/give-up")
    assert res.status_code == 200 and res.json()["status"] == "superseded"
    assert client.post(f"{API}/retries/{pending.id}/give-up").status_code == 409
    db_session.refresh(theirs)
    assert theirs.status == "pending"
