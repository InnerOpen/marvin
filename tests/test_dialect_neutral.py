"""Every dashboard and admin-overview widget shows its data on both engines.

The widgets swallow their own errors (a panel that cannot be read is empty, never a failed page), which is the right
rule for the page and the wrong one for finding that a query only works on one engine: `date_trunc` (Postgres only)
emptied "published by week" on SQLite, and a `date()` that came back as text zeroed the AI spend chart, with nothing
logged. So each widget is seeded here, must come back non-empty, and must get there without a rollback (what the
swallowing handlers do first). The suite runs on SQLite by default and on Postgres in CI: the same file proves both.
"""

# ruff: noqa: F811 — `ws` / `workspace` are fixtures, not redefinitions
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from marvin.db.models.groups.ai_executions import AIExecutionModel
from marvin.db.models.groups.integrations import IntegrationModel
from marvin.db.models.groups.webhook_execution_logs import WebhookExecutionLogModel
from marvin.db.models.groups.webhooks import GroupWebhooksModel
from marvin.db.models.groups.workflow_approvals import WorkflowApprovalModel
from marvin.db.models.groups.workflow_waits import WorkflowWaitModel
from marvin.db.models.platform.event_log import EventLogModel
from marvin.db.models.platform.scheduled_tasks import ScheduledTaskModel
from marvin.db.models.users.users import Users
from marvin.services import admin_overview, dashboard
from tests.test_dashboard_panels import _entry, _run, _workflow, workspace, ws  # noqa: F401 — fixtures and seeding helpers

NOW = datetime.now(UTC).replace(microsecond=0)
HOUR, DAY = timedelta(hours=1), timedelta(days=1)


@pytest.fixture
def seeded(ws, monkeypatch):
    """The workspace with a row behind every widget, and a spy on the session's rollbacks."""
    session, gid = ws.session, ws.gid
    wf = _workflow(ws, name="Publish gate")
    this_monday = NOW.date() - timedelta(days=NOW.weekday())

    post = _entry(ws, "Published now", status="published", published_at=(NOW - timedelta(minutes=5)).replace(tzinfo=None))
    _entry(ws, "Published last week", status="published", published_at=datetime.combine(this_monday - timedelta(days=3), datetime.min.time()))
    _entry(ws, "An old draft", created_at=(NOW - 10 * DAY).replace(tzinfo=None))
    _entry(ws, "Goes out tomorrow", publish_at=(NOW + DAY).replace(tzinfo=None))
    session.flush()

    session.add(
        WorkflowApprovalModel(
            session=session,
            group_id=gid,
            automation_id=wf.id,
            step_index=0,
            message="ok?",
            min_role=2,
            expires_at=(NOW + DAY).replace(tzinfo=None),
            entry_id=post.id,
        )
    )
    session.add(
        WorkflowWaitModel(
            session=session, group_id=gid, automation_id=wf.id, step_index=1, resume_at=(NOW + 2 * HOUR).replace(tzinfo=None), status="waiting"
        )
    )
    session.add(
        ScheduledTaskModel(
            session=session,
            group_id=gid,
            name="Weekly roundup",
            slug=f"weekly-{uuid.uuid4().hex[:6]}",
            enabled=True,
            schedule_type="cron",
            schedule_config={"cron": "0 9 * * 1"},
            task_type="publish",
            task_config={},
            next_run_at=NOW + 3 * DAY,
        )  # fmt: skip
    )
    session.add(
        IntegrationModel(
            session=session, group_id=gid, provider="fake", name="ig", slug="ig", enabled=True, config={}, secret_ref="X_ig", status="error"
        )
    )
    hook = GroupWebhooksModel(session=session, group_id=gid, name="Hook", enabled=True, url="https://example.com/h")
    session.add(hook)
    session.flush()
    session.add(WebhookExecutionLogModel(session=session, webhook_id=hook.id, group_id=gid, executed_at=NOW - HOUR, status="failed"))
    for status, when in (("success", NOW), ("failed", NOW - HOUR), ("waiting", NOW - 2 * HOUR), ("success", NOW - DAY)):
        _run(ws, wf, status, when)
    session.add(
        EventLogModel(
            event_id=uuid.uuid4(),
            event_type="entry_updated",
            occurred_at=NOW - HOUR,
            workspace_id=gid,
            user_id=ws.uid,
            entity_id=post.id,
            entity_type="entry",
            integration_id="test",
            event_data={},
            message_title="Published now",
        )  # fmt: skip
    )
    for cost, when in ((0.5, NOW), (0.25, NOW - DAY)):
        session.add(
            AIExecutionModel(
                session=session,
                group_id=gid,
                operation_slug="op",
                provider_type="fake",
                model_id="m",
                status="completed",
                prompt_tokens=100,
                completion_tokens=20,
                total_tokens=120,
                estimated_cost_usd=cost,
                started_at=when.replace(tzinfo=None),
            )  # fmt: skip
        )
    session.query(Users).filter(Users.id == ws.uid).update({"last_login_at": NOW})
    session.commit()

    rollbacks = []
    real_rollback = session.rollback
    monkeypatch.setattr(session, "rollback", lambda: (rollbacks.append(1), real_rollback())[1])
    yield ws
    assert rollbacks == [], "a widget swallowed an error (it rolled the session back): its query does not run on this engine"


def test_every_workspace_dashboard_widget_has_its_data(seeded):
    ws = seeded
    count, briefs = dashboard.approvals_waiting(ws.session, ws.gid, role=2)
    assert count == 1 and briefs[0].entry_title == "Published now"
    assert dashboard.parked_runs(ws.session, ws.gid) == 1
    assert dashboard.oldest_entry_days(ws.session, ws.gid, "draft", NOW) == 10
    assert {i.kind for i in dashboard.upcoming(ws.session, ws.gid, NOW)} == {"publish", "resume", "task"}
    strip = dashboard.health(ws.session, ws.gid, NOW, sees_backups=False)
    assert strip.integrations_failing >= 1 and strip.webhook_failures_24h == 1 and strip.workflow_failures_7d == 1
    days = dashboard.runs_by_day(ws.session, ws.gid, NOW)
    assert (days[-1].ok, days[-1].failed, days[-2].ok) == (1, 1, 1)
    pulse = dashboard.published_by_week(ws.session, ws.gid, NOW)
    assert pulse.total == 2 and pulse.types and pulse.weeks[-1].by_type  # this week; last week's is in the row before
    assert dashboard.recent_for_you(ws.session, ws.gid, ws.uid, NOW)
    row = next(r for r in dashboard.by_type_status(ws.session, ws.gid) if r.slug == ws.et["slug"])
    assert (row.draft, row.published) == (2, 2)


def test_every_admin_overview_widget_has_its_data(seeded):
    ws = seeded
    overview = admin_overview.overview(ws.session, NOW)
    assert overview.health, "no health dots"
    mine = next(r for r in overview.workspaces if r.id == str(ws.gid))
    assert mine.entries >= 4 and mine.ai_spend_month == pytest.approx(0.75) and mine.last_activity is not None
    assert sum(d.cost for d in overview.spend) == pytest.approx(0.75) and sum(d.runs for d in overview.spend) == 2
    assert overview.spend[-1].cost == pytest.approx(0.5)
    assert any(s.user_id == str(ws.uid) for s in overview.sign_ins)


def test_the_database_report_and_size_have_numbers_on_either_engine(seeded):
    from marvin.db.size import database_size_bytes, largest_tables
    from marvin.services.database_report import database_report

    ws = seeded
    assert database_size_bytes(ws.session) > 0
    tables = largest_tables(ws.session, 5)
    assert 0 < len(tables) <= 5 and all(t.rows >= 0 for t in tables)
    report = database_report(ws.session)
    assert report.size_bytes > 0 and report.tables
